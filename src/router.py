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
                await page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3.0)

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
                    return CaptchaSolution(
                        type=CaptchaType.UNKNOWN,
                        success=False,
                        error="no captcha detected on page",
                    )

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
