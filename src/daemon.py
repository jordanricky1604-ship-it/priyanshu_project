import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
import time
from prometheus_client import make_asgi_app
from fastapi.staticfiles import StaticFiles
import os

from src.models import CaptchaType, CaptchaChallenge, CaptchaSolution, RateLimitException
from src.router import StrategyRouter
from src.browser import get_browser, close_browser
from src.config import get_config, ProxyConfig
from src.metrics import (
    CAPTCHA_REQUESTS_TOTAL,
    CAPTCHA_RATE_LIMITS_TOTAL,
    CAPTCHA_SOLVE_DURATION_SECONDS,
    ACTIVE_SOLVES
)

logger = logging.getLogger("captcha_solver.daemon")

class SolveRequest(BaseModel):
    url: str
    captcha_type: CaptchaType
    site_key: str | None = None
    extra: dict | None = None
    visible_browser: bool | None = None

router: StrategyRouter | None = None
current_proxy_index = 0

async def rotate_proxy(profile_name: str = "default"):
    global current_proxy_index
    config = get_config()
    proxies = config.solver.proxies
    
    if proxies:
        current_proxy_index = (current_proxy_index + 1) % len(proxies)
        new_proxy = proxies[current_proxy_index]
        logger.info(f"Rotating proxy to: {new_proxy.server}")
        if router:
            profile = router.profiles.get_or_create(profile_name)
            profile.proxy = new_proxy
            router.profiles.save(profile)
    else:
        logger.warning("No proxies configured. Proxy rotation skipped.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global router
    logger.info("Initializing persistent daemon state...")
    config = get_config()
    browser = await get_browser(config.solver)
    router = StrategyRouter(config.solver, browser)
    
    # Initialize first proxy if available
    if config.solver.proxies:
        profile = router.profiles.get_or_create("default")
        profile.proxy = config.solver.proxies[current_proxy_index]
        router.profiles.save(profile)

    yield
    logger.info("Shutting down persistent daemon state...")
    await close_browser()

app = FastAPI(title="Captcha Solver Daemon", lifespan=lifespan)

# Mount Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Mount Static UI
ui_dir = os.path.join(os.path.dirname(__file__), "ui")
os.makedirs(ui_dir, exist_ok=True)
app.mount("/ui", StaticFiles(directory=ui_dir, html=True), name="ui")

@app.post("/solve", response_model=CaptchaSolution)
async def solve_captcha(req: SolveRequest):
    global router
    if not router:
        raise HTTPException(status_code=503, detail="Daemon not fully initialized")

    logger.info(f"Received solve request for {req.url} ({req.captcha_type})")
    ACTIVE_SOLVES.inc()
    start_time = time.time()
    
    # Handle dynamic foreground browser switching
    config = get_config()
    current_headless = config.solver.browser_headless
    requested_headless = not req.visible_browser if req.visible_browser is not None else current_headless
    
    if current_headless != requested_headless:
        logger.info(f"Dynamically restarting browser (headless: {current_headless} -> {requested_headless})")
        await close_browser()
        config.solver.browser_headless = requested_headless
        browser = await get_browser(config.solver)
        router.browser = browser
    
    try:
        solution = await router.solve(
            page_url=req.url,
            profile_name="default",
            force_type=req.captcha_type
        )
        
        if not solution.success and "RateLimitException" in str(solution.error):
            logger.warning("Rate limit hit! Rotating proxy and retrying...")
            
            # Record rate limit for the CURRENT proxy before we rotate
            config = get_config()
            current_ip = config.solver.proxies[current_proxy_index].server if config.solver.proxies else "direct"
            CAPTCHA_RATE_LIMITS_TOTAL.labels(proxy_ip=current_ip).inc()
            
            await rotate_proxy("default")
            
            # Retry once after rotation
            solution = await router.solve(
                page_url=req.url,
                profile_name="default",
                force_type=req.captcha_type
            )
            
        duration = time.time() - start_time
        status_label = "success" if solution.success else "failure"
        if not solution.success and "RateLimitException" in str(solution.error):
            status_label = "rate_limited"
            
        CAPTCHA_REQUESTS_TOTAL.labels(captcha_type=req.captcha_type.value, status=status_label).inc()
        
        # We record duration for successful solves, and we try to infer solver_method from router output if possible.
        # But for now, we record overall duration. We can refine method tracking inside the solver.
        if solution.success:
            CAPTCHA_SOLVE_DURATION_SECONDS.labels(
                captcha_type=req.captcha_type.value, 
                solver_method="auto"  # Can be refined if router exposes solver method used
            ).observe(duration)
            
        return solution
        
    except Exception as e:
        logger.error(f"Solve failed: {e}")
        duration = time.time() - start_time
        CAPTCHA_REQUESTS_TOTAL.labels(captcha_type=req.captcha_type.value, status="failure").inc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        ACTIVE_SOLVES.dec()

def run_daemon(host: str = "127.0.0.1", port: int = 8000):
    logger.info(f"Starting captcha-solver daemon on {host}:{port}")
    uvicorn.run("src.daemon:app", host=host, port=port, log_level="info")
