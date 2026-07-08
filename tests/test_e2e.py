import asyncio
import pytest
import pytest_asyncio
from src.config import get_config
from src.router import StrategyRouter
from src.browser import get_browser, close_browser

@pytest_asyncio.fixture(scope="module")
async def e2e_router():
    config = get_config()
    config.solver.browser_headless = True
    browser = await get_browser(config.solver)
    router = StrategyRouter(config.solver, browser)
    yield router
    await close_browser()


@pytest.mark.e2e
@pytest.mark.skip(reason="Live Captcha endpoints rate limit CI. Run locally.")
@pytest.mark.asyncio
async def test_recaptcha_v2_live(e2e_router: StrategyRouter):
    # Navigate to the official Google reCAPTCHA v2 demo
    url = "https://www.google.com/recaptcha/api2/demo"
    
    solution = await e2e_router.solve(url, profile_name="test_e2e")
    
    assert solution.success is True
    assert solution.token != ""
    assert "no captcha detected" not in solution.error


@pytest.mark.e2e
@pytest.mark.skip(reason="Live Captcha endpoints rate limit CI. Run locally.")
@pytest.mark.asyncio
async def test_hcaptcha_live(e2e_router: StrategyRouter):
    # Navigate to the official hCaptcha demo
    url = "https://accounts.hcaptcha.com/demo"
    
    solution = await e2e_router.solve(url, profile_name="test_e2e")
    
    assert solution.success is True
    assert solution.token != ""
    assert "no captcha detected" not in solution.error


@pytest.mark.e2e
@pytest.mark.skip(reason="Live Captcha endpoints rate limit CI. Run locally.")
@pytest.mark.asyncio
async def test_turnstile_live(e2e_router: StrategyRouter):
    # Navigate to a public Turnstile demo
    url = "https://peet.ws/turnstile-test/non-interactive.html"
    
    solution = await e2e_router.solve(url, profile_name="test_e2e")
    
    assert solution.success is True
    assert solution.token != ""
    assert "no captcha detected" not in solution.error
