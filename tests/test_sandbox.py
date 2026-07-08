import pytest
import pytest_asyncio
import asyncio
from unittest.mock import patch, AsyncMock

from src.config import get_config
from src.router import StrategyRouter
from src.browser import get_browser, close_browser
from src.models import CaptchaSolution, CaptchaType
from tests.sandbox_server import SandboxServer

@pytest_asyncio.fixture(scope="function")
async def sandbox_env():
    # Start the sandbox server
    server = SandboxServer(port=8080)
    server.start()
    
    # Wait for server to boot
    await asyncio.sleep(1.0)
    
    config = get_config()
    config.solver.browser_headless = True
    config.solver.max_retries = 2 # Speed up failures if any
    
    browser = await get_browser(config.solver)
    router = StrategyRouter(config.solver, browser)
    
    yield router
    
    await close_browser()
    server.stop()


@pytest.mark.asyncio
async def test_sandbox_audio_solve(sandbox_env):
    router = sandbox_env
    url = "http://localhost:8080/index.html"
    
    mock_audio_solution = CaptchaSolution(
        type=CaptchaType.IMAGE_CAPTCHA,
        success=True,
        token="mock-transcription"
    )
    
    # We patch the audio solver so we don't need actual Whisper ML weights to run this test
    with patch("src.solvers.audio.AudioSolver.solve", new_callable=AsyncMock) as mock_solve:
        mock_solve.return_value = mock_audio_solution
        
        # We also patch `fetch_audio_base64_stealth` to just return fake base64 immediately
        # because our sandbox server returns a dummy mp3 which might trip up stealth fetching mechanisms
        with patch("src.solvers.browser_token.fetch_audio_base64_stealth", new_callable=AsyncMock) as mock_stealth_fetch:
            mock_stealth_fetch.return_value = "fake_base64_data_here"
            
            solution = await router.solve(url, profile_name="test_sandbox", force_type=CaptchaType.RECAPTCHA_V2)
            
            assert solution.success is True
            assert solution.token == "sandbox-success-token"
            assert mock_solve.called

@pytest.mark.asyncio
async def test_sandbox_image_fallback(sandbox_env):
    router = sandbox_env
    url = "http://localhost:8080/index.html"
    
    mock_image_solution = CaptchaSolution(
        type=CaptchaType.IMAGE_CAPTCHA,
        success=True,
        extra={"selected_tiles": [0, 1, 2]}
    )
    
    # We patch the audio button to be missing to force image fallback
    # And we patch the ImageClassifierSolver so we don't need CLIP weights
    with patch("src.solvers.image_classifier.ImageClassifierSolver.solve", new_callable=AsyncMock) as mock_img_solve:
        mock_img_solve.return_value = mock_image_solution
        
        # Patch the audio locator to timeout, mimicking it not being on page
        with patch("playwright.async_api.Locator.is_visible", new_callable=AsyncMock) as mock_visible:
            # Only timeout if it's checking the audio button
            async def side_effect(*args, **kwargs):
                return False
                
            mock_visible.side_effect = side_effect
            
            solution = await router.solve(url, profile_name="test_sandbox_img", force_type=CaptchaType.RECAPTCHA_V2)
            
            assert solution.success is True
            assert solution.token == "sandbox-success-token"
            assert mock_img_solve.called
