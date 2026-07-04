import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

from src.models import CaptchaType, CaptchaChallenge, CaptchaSolution, RateLimitException
from src.router import StrategyRouter
from src.browser import get_browser, close_browser
from src.config import get_config, ProxyConfig

logger = logging.getLogger("captcha_solver.daemon")

class SolveRequest(BaseModel):
    url: str
    captcha_type: CaptchaType
    site_key: str | None = None
    extra: dict | None = None

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

@app.post("/solve", response_model=CaptchaSolution)
async def solve_captcha(req: SolveRequest):
    global router
    if not router:
        raise HTTPException(status_code=503, detail="Daemon not fully initialized")

    logger.info(f"Received solve request for {req.url} ({req.captcha_type})")
    
    try:
        solution = await router.solve(
            page_url=req.url,
            profile_name="default",
            force_type=req.captcha_type
        )
        # If it failed due to RateLimitException (which isn't caught if router.solve catches it?)
        # Let's check if the solution error contains RateLimitException.
        # Actually StrategyRouter catches all exceptions and returns a CaptchaSolution(success=False, error=str(e))
        if not solution.success and "RateLimitException" in str(solution.error):
            logger.warning("Rate limit hit! Rotating proxy and retrying...")
            await rotate_proxy("default")
            
            # Retry once after rotation
            solution = await router.solve(
                page_url=req.url,
                profile_name="default",
                force_type=req.captcha_type
            )
            
        return solution
        
    except Exception as e:
        logger.error(f"Solve failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def run_daemon(host: str = "127.0.0.1", port: int = 8000):
    logger.info(f"Starting captcha-solver daemon on {host}:{port}")
    uvicorn.run("src.daemon:app", host=host, port=port, log_level="info")
