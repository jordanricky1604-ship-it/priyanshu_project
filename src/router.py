from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from playwright.async_api import Browser

from src.models import CaptchaChallenge, CaptchaSolution, CaptchaType
from src.solvers.base import SolverRegistry
from src.solvers.browser_token import BrowserTokenSolver
from src.browser import create_context
from src.config import SolverConfig, BrowserProfile
from src.detector import detect_captcha
from src.profiles import ProfileManager

logger = logging.getLogger("captcha_solver")


class StrategyRouter:
    def __init__(
        self,
        config: SolverConfig,
        browser: Browser,
        profile_manager: Optional[ProfileManager] = None,
    ):
        self.config = config
        self.browser = browser
        self.profiles = profile_manager or ProfileManager()

    async def solve(
        self,
        page_url: str,
        profile_name: str = "default",
        force_type: Optional[CaptchaType] = None,
    ) -> CaptchaSolution:
        start = time.time()
        profile = self.profiles.get_or_create(profile_name)
        proxy_config = profile.proxy.as_playwright() if profile.proxy else None

        async with create_context(self.browser, profile, proxy_config) as context:
            page = await context.new_page()

            try:
                await self._prewarm_page(page, page_url)
                try:
                    await page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
                except Exception as goto_err:
                    logger.warning(f"page.goto timeout or error: {goto_err}")
                await asyncio.sleep(3.0)

                # Capture screenshot for the UI
                try:
                    screenshot_bytes = await page.screenshot(type='jpeg', quality=80)
                except Exception:
                    screenshot_bytes = None

                if force_type:
                    challenge = CaptchaChallenge(
                        type=force_type,
                        page_url=page_url,
                    )
                    await self._enhance_challenge(challenge, page)
                else:
                    challenge = await detect_captcha(page, page_url)
                    logger.info(f"detected captcha type: {challenge.type.name}")

                if challenge.type == CaptchaType.UNKNOWN:
                    sol = CaptchaSolution(
                        type=challenge.type,
                        success=False,
                        token="",
                        elapsed_ms=0
                    )
                    sol.image_bytes = screenshot_bytes
                    return sol

                solver = SolverRegistry.find(challenge)
                if not solver:
                    logger.info(f"no specialized solver for {challenge.type.name}, using browser token solver")
                    browser_solver = BrowserTokenSolver(self.config, page)
                    solution = await browser_solver.solve(challenge)
                else:
                    if solver.name == "browser_token":
                        browser_solver = BrowserTokenSolver(self.config, page)
                        solution = await browser_solver.solve(challenge)
                    else:
                        challenge.extra["page"] = page
                        solution = await solver.solve(challenge)

                if screenshot_bytes and not solution.image_bytes:
                    solution.image_bytes = screenshot_bytes

                if solution.success:
                    try:
                        # Try to click a generic submit button on the demo page to show the final result screen
                        submit_btn = page.locator("button[type='submit'], button:has-text('Check'), button:has-text('Submit'), button:has-text('Verify'), input[type='submit']").first
                        if await submit_btn.is_visible(timeout=1000):
                            await submit_btn.click()
                            await asyncio.sleep(2.0)
                    except Exception:
                        pass

                if solution.success:
                    try:
                        # Capture cookies to return to caller
                        raw_cookies = await context.cookies()
                        cookie_dict = {c['name']: c['value'] for c in raw_cookies}
                        solution.cookies = cookie_dict
                    except Exception as e:
                        logger.error(f"failed to extract cookies: {e}")

                self.profiles.record_use(profile_name, solution.success)
                return solution

            except Exception as e:
                elapsed = (time.time() - start) * 1000
                logger.error(f"routing error: {e}")
                return CaptchaSolution(
                    type=challenge.type if "challenge" in dir() else CaptchaType.UNKNOWN,
                    success=False,
                    error=str(e),
                    elapsed_ms=elapsed,
                )

    async def _prewarm_page(self, page, target_url: str) -> None:
        prewarm_sites = [
            "https://www.google.com",
            "https://en.wikipedia.org",
        ]
        for site in prewarm_sites[:1]:
            try:
                await page.goto(site, wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(1.5)
                await page.evaluate("window.scrollBy(0, 300)")
                await asyncio.sleep(0.5)
                await page.evaluate("window.scrollBy(0, -200)")
                await asyncio.sleep(0.5)
            except Exception:
                pass

    async def _enhance_challenge(self, challenge: CaptchaChallenge, page) -> None:
        try:
            detected = await detect_captcha(page, challenge.page_url)
            if detected.sitekey:
                challenge.sitekey = detected.sitekey
            if detected.action:
                challenge.action = detected.action
            if detected.is_invisible:
                challenge.is_invisible = detected.is_invisible
            challenge.extra.update(detected.extra)
        except Exception:
            pass
