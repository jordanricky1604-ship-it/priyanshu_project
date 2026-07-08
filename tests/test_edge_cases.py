import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.models import CaptchaChallenge, CaptchaType, CaptchaSolution, RateLimitException
from src.solvers.browser_token import BrowserTokenSolver
from src.config import SolverConfig
from src.utils.retry import PlaywrightTimeoutError

# Helper to create async mock locators
def create_locator(visible=True, text="", attribute_val="", count_val=0):
    loc = AsyncMock()
    loc.is_visible.return_value = visible
    loc.inner_text.return_value = text
    loc.text_content.return_value = text
    loc.get_attribute.return_value = attribute_val
    loc.count.return_value = count_val
    loc.screenshot.return_value = b"fake_screenshot_bytes"
    
    # Sync properties/methods
    loc.first = loc
    loc.nth = MagicMock(return_value=loc)
    return loc

@pytest.fixture
def mock_page():
    page = AsyncMock()
    page.url = "https://example.com"
    page.locator = MagicMock(return_value=create_locator())
    return page

@pytest.fixture
def solver(mock_page):
    config = SolverConfig(max_retries=2, retry_delay_ms=10)
    model_manager = MagicMock()
    
    s = BrowserTokenSolver(config=config, page=mock_page, model_manager=model_manager)
    s._click_checkbox = AsyncMock()
    
    return s

@pytest.mark.asyncio
async def test_rate_limit_propagation(solver, mock_page):
    anchor_frame = AsyncMock()
    anchor_frame.url = "recaptcha/api2/anchor"
    anchor_frame.locator = MagicMock(return_value=create_locator())
    
    bframe = AsyncMock()
    bframe.url = "recaptcha/api2/bframe"
    bframe.locator = MagicMock(return_value=create_locator(text="Try again later"))
    
    mock_page.frames = [anchor_frame, bframe]
    
    # Mock token extraction to always fail so it triggers the solve loop
    solver._extract_recaptcha_response = AsyncMock(return_value=None)
    
    challenge = CaptchaChallenge(type=CaptchaType.RECAPTCHA_V2)
    
    # Execute solve
    solution = await solver.solve(challenge)
    
    # It should catch RateLimitException and return it in the error WITHOUT exhausting max_retries retries!
    assert solution.success is False
    assert "RateLimitException" in solution.error
    assert "Try again later" in solution.error

@pytest.mark.asyncio
async def test_audio_fallback_to_image(solver, mock_page):
    # Setup mock frames where Audio button is NOT visible
    anchor_frame = AsyncMock()
    anchor_frame.url = "recaptcha/api2/anchor"
    anchor_frame.locator = MagicMock(return_value=create_locator())
    
    bframe = AsyncMock()
    bframe.url = "recaptcha/api2/bframe"
    
    # When locator is called, if it's the audio button, say it's not visible
    def locator_side_effect(selector):
        if "audio" in selector:
            loc = create_locator(visible=False)
            loc.is_visible.side_effect = PlaywrightTimeoutError("Timeout")
            return loc
        if "rc-imageselect-tile" in selector:
            return create_locator(count_val=9)
        return create_locator(text="Select all crosswalks")
        
    bframe.locator = MagicMock(side_effect=locator_side_effect)
    mock_page.frames = [anchor_frame, bframe]
    
    solver._extract_recaptcha_response = AsyncMock(side_effect=[None, None, "fake-image-token"])
    
    # Mock the image solver specifically
    mock_image_solution = CaptchaSolution(type=CaptchaType.IMAGE_CAPTCHA, success=True, extra={"selected_tiles": [0, 1, 2]})
    solver._image_solver.solve = AsyncMock(return_value=mock_image_solution)
    
    challenge = CaptchaChallenge(type=CaptchaType.RECAPTCHA_V2)
    
    with patch("src.solvers.browser_token.human_click", new_callable=AsyncMock) as mock_click:
        solution = await solver.solve(challenge)
        
        # It should succeed via the fallback image token
        assert solution.success is True
        assert solution.token == "fake-image-token"
        
        # Verify the image solver was called
        assert solver._image_solver.solve.called
        assert mock_click.call_count == 8

@pytest.mark.asyncio
async def test_timeout_exhaustion(solver, mock_page):
    # Simulate a generic playwright timeout when looking for the bframe
    anchor_frame = AsyncMock()
    anchor_frame.url = "recaptcha/api2/anchor"
    mock_page.frames = [anchor_frame]
    
    solver._extract_recaptcha_response = AsyncMock(return_value=None)
    solver._find_recaptcha_bframe = AsyncMock(return_value=None)
    
    challenge = CaptchaChallenge(type=CaptchaType.RECAPTCHA_V2)
    
    solution = await solver.solve(challenge)
    
    assert solution.success is False
    assert solution.error == "max retries exhausted"
    assert solution.attempts == solver.config.max_retries

@pytest.mark.asyncio
async def test_malformed_audio_payload(solver, mock_page):
    anchor_frame = AsyncMock()
    anchor_frame.url = "recaptcha/api2/anchor"
    anchor_frame.locator = MagicMock(return_value=create_locator())
    
    bframe = AsyncMock()
    bframe.url = "recaptcha/api2/bframe"
    
    # Mock locator so it finds the audio button, but fetch_audio_base64_stealth returns None
    def locator_side_effect(selector):
        if "audio" in selector:
            return create_locator(visible=True)
        if "rc-imageselect-tile" in selector:
            return create_locator(count_val=9)
        return create_locator(text="Select all crosswalks")
        
    bframe.locator = MagicMock(side_effect=locator_side_effect)
    mock_page.frames = [anchor_frame, bframe]
    
    solver._extract_recaptcha_response = AsyncMock(side_effect=[None, None, "fake-image-token"])
    
    # Mock the image solver specifically
    mock_image_solution = CaptchaSolution(type=CaptchaType.IMAGE_CAPTCHA, success=True, extra={"selected_tiles": [0, 1, 2]})
    solver._image_solver.solve = AsyncMock(return_value=mock_image_solution)
    
    challenge = CaptchaChallenge(type=CaptchaType.RECAPTCHA_V2)
    
    with patch("src.solvers.browser_token.fetch_audio_base64_stealth", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = None # Simulating a malformed payload
        
        with patch("src.solvers.browser_token.human_click", new_callable=AsyncMock) as mock_click:
            solution = await solver.solve(challenge)
            
            assert solution.success is True
            assert solution.token == "fake-image-token"
            assert solver._image_solver.solve.called

@pytest.mark.asyncio
async def test_unexpected_iframe_navigation(solver, mock_page):
    from playwright.async_api import Error as PlaywrightError
    
    anchor_frame = AsyncMock()
    anchor_frame.url = "recaptcha/api2/anchor"
    anchor_frame.locator = MagicMock(return_value=create_locator())
    
    bframe = AsyncMock()
    bframe.url = "recaptcha/api2/bframe"
    
    # Simulate Playwright throwing TargetClosedError (using general Error as TargetClosedError is just an Error in Playwright python sometimes)
    loc = create_locator()
    loc.click.side_effect = PlaywrightError("Execution context was destroyed")
    bframe.locator = MagicMock(return_value=loc)
    
    mock_page.frames = [anchor_frame, bframe]
    solver._extract_recaptcha_response = AsyncMock(return_value=None)
    
    challenge = CaptchaChallenge(type=CaptchaType.RECAPTCHA_V2)
    
    solution = await solver.solve(challenge)
    
    assert solution.success is False
    # The solver loop should exhaust retries, meaning it successfully caught the PlaywrightError without hard-crashing
    assert solution.error == "max retries exhausted"

@pytest.mark.asyncio
async def test_phantom_captcha(solver, mock_page):
    # Empty frames list, simulating a blocked iframe
    mock_page.frames = []
    
    challenge = CaptchaChallenge(type=CaptchaType.RECAPTCHA_V2)
    
    solution = await solver.solve(challenge)
    
    # It should cleanly fail saying it couldn't find the frame, NOT throw a NoneType error
    assert solution.success is False
    assert solution.error == "max retries exhausted"
