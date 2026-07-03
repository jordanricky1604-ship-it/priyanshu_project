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

router = None
browser_page = None
current_proxy_index = 0

async def rotate_proxy():
    global browser_page, current_proxy_index
    config = get_config()
    proxies = config.solver.proxies
    
    logger.info("Rotating proxy due to rate limit...")
    await close_browser()
    
    if proxies:
        current_proxy_index = (current_proxy_index + 1) % len(proxies)
        new_proxy = proxies[current_proxy_index].as_playwright()
        logger.info(f"Switched to proxy: {new_proxy['server'] if new_proxy else 'None'}")
        browser_page = await get_browser(proxy=new_proxy)
    else:
        logger.warning("No proxies configured in solver.proxies. Restarting browser with no proxy.")
        browser_page = await get_browser()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global router, browser_page
    logger.info("Initializing persistent daemon state...")
    router = StrategyRouter()
    browser_page = await get_browser()
    yield
    logger.info("Shutting down persistent daemon state...")
    await close_browser()

app = FastAPI(title="Captcha Solver Daemon", lifespan=lifespan)

@app.post("/solve", response_model=CaptchaSolution)
async def solve_captcha(req: SolveRequest):
    global router, browser_page
    if not router or not browser_page:
        raise HTTPException(status_code=503, detail="Daemon not fully initialized")

    logger.info(f"Received solve request for {req.url} ({req.captcha_type})")
    
    # We navigate to the URL before solving
    try:
        await browser_page.goto(req.url, wait_until="networkidle")
    except Exception as e:
        logger.error(f"Failed to navigate to {req.url}: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to navigate: {e}")

    extra = req.extra or {}
    extra["page"] = browser_page

    challenge = CaptchaChallenge(
        type=req.captcha_type,
        url=req.url,
        site_key=req.site_key,
        extra=extra
    )

    try:
        solution = await router.route(challenge)
        return solution
    except RateLimitException as e:
        logger.warning(f"Rate limit hit! Rotating proxy and retrying... {e}")
        await rotate_proxy()
        # Retry once after rotation
        try:
            extra["page"] = browser_page
            await browser_page.goto(req.url, wait_until="networkidle")
            solution = await router.route(challenge)
            return solution
        except Exception as e2:
            logger.error(f"Solve failed after proxy rotation: {e2}")
            raise HTTPException(status_code=500, detail=str(e2))
    except Exception as e:
        logger.error(f"Solve failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def run_daemon(host: str = "127.0.0.1", port: int = 8000):
    logger.info(f"Starting captcha-solver daemon on {host}:{port}")
    uvicorn.run("src.daemon:app", host=host, port=port, log_level="info")
