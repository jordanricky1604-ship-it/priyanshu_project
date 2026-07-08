import asyncio
import logging
from src.config import get_config
from src.browser import get_browser, close_browser
from src.router import StrategyRouter
import src.solvers  # Register solvers

URLS = [
    ("Distorted text", "https://captcha.com/demos/features/captcha-demo.aspx"),
    ("Simple image-text", "https://2captcha.com/demo/normal"),
    ("Audio", "https://captcha.com/audio-captcha-examples.html"),
    ("Image selection", "https://www.google.com/recaptcha/api2/demo"),
    ("hCaptcha", "https://accounts.hcaptcha.com/demo"),
    ("Text question", "https://2captcha.com/demo/text"),
    ("Math", "https://democaptcha.com/demo-form-eng/math-image.html"),
    ("Click objects", "https://2captcha.com/demo/clickcaptcha"),
    ("Rotate image", "https://2captcha.com/demo/rotatecaptcha"),
    ("Slider", "https://www.geetest.com/en/adaptive-captcha-demo"),
    ("Multiple Geetest", "https://gt4.geetest.com/demov4/more-float-en.html"),
    ("KeyCAPTCHA", "https://2captcha.com/demo/keycaptcha"),
    ("Turnstile", "https://2captcha.com/demo/cloudflare-turnstile"),
    ("reCAPTCHA demo appspot", "https://recaptcha-demo.appspot.com/")
]

async def run_tests():
    logging.basicConfig(level=logging.ERROR)
    config = get_config()
    browser = await get_browser(config.solver)
    router = StrategyRouter(config.solver, browser)
    
    from src.models import CaptchaType
    
    print(f"{'Type':<20} | {'Status':<15} | {'Time (ms)':<10} | {'Error'}")
    print("-" * 75)
    
    try:
        for name, url in URLS:
            try:
                force_type = CaptchaType.AUDIO_CAPTCHA if name == "Audio" else None
                for attempt in range(3):
                    solution = await asyncio.wait_for(router.solve(page_url=url, force_type=force_type), timeout=120.0)
                    if solution.success:
                        break
                    await asyncio.sleep(2.0)
                    
                status = "SUCCESS" if solution.success else "FAILED"
                err = solution.error if not solution.success else ""
                print(f"{name:<20} | {status:<15} | {int(solution.elapsed_ms):<10} | {err}")
            except asyncio.TimeoutError:
                print(f"{name:<20} | TIMEOUT         | >120000    | Captcha solver hung or took too long")
            except Exception as e:
                print(f"{name:<20} | ERROR           | N/A        | {str(e)}")
    finally:
        await close_browser()

if __name__ == "__main__":
    asyncio.run(run_tests())
