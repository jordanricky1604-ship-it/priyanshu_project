from __future__ import annotations

import asyncio
import logging
import time
import random
from typing import Optional

from playwright.async_api import Page, Frame

from src.models import CaptchaChallenge, CaptchaSolution, CaptchaType
from src.solvers.base import BaseSolver, SolverRegistry
from src.behavior import human_click, human_mouse_move

logger = logging.getLogger("captcha_solver")


class FunCaptchaSolver(BaseSolver):
    name = "funcaptcha"

    def can_solve(self, challenge: CaptchaChallenge) -> bool:
        return challenge.type == CaptchaType.FUNCAPTCHA

    async def solve(self, challenge: CaptchaChallenge) -> CaptchaSolution:
        start = time.time()
        try:
            page = challenge.extra.get("page")
            if not page:
                return CaptchaSolution(
                    type=challenge.type,
                    success=False,
                    error="no playwright Page in challenge.extra",
                )

            frame = await self._find_funcaptcha_frame(page)
            if not frame:
                return CaptchaSolution(
                    type=challenge.type,
                    success=False,
                    error="funcaptcha frame not found",
                )

            token = await self._solve_orientation(page, frame)
            elapsed = (time.time() - start) * 1000

            return CaptchaSolution(
                type=challenge.type,
                token=token or "",
                solved_via="funcaptcha",
                attempts=1,
                elapsed_ms=elapsed,
                success=token is not None,
            )
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            return CaptchaSolution(
                type=challenge.type,
                success=False,
                error=str(e),
                attempts=1,
                elapsed_ms=elapsed,
            )

    async def _find_funcaptcha_frame(self, page: Page) -> Optional[Frame]:
        for _ in range(5):
            for frame in page.frames:
                if "funcaptcha" in frame.url or "arkoselabs" in frame.url:
                    return frame
            await asyncio.sleep(1.0)
        return None

    async def _solve_orientation(self, page: Page, frame: Frame) -> Optional[str]:
        for _ in range(5):
            try:
                verify_btn = frame.locator("button[type='submit'], .button-submit")
                if await verify_btn.count():
                    await human_click(page, verify_btn)
                    await asyncio.sleep(2.0)
            except Exception:
                pass

            token = await page.evaluate("""
            (() => {
                try { return _funcaptcha_token || _funcaptcha_response; } catch(e) {}
                try { return _arkose_token || _arkose_response; } catch(e) {}
                return null;
            })()
            """)

            if token and isinstance(token, str) and len(token) > 10:
                return str(token)

            images = frame.locator(".fc-image, .fc-image-wrapper img, img[src*='arkose']")
            count = await images.count()
            for i in range(min(count, 3)):
                try:
                    img = images.nth(i)
                    box = await img.bounding_box()
                    if box:
                        x = box["x"] + box["width"] / 2
                        y = box["y"] + box["height"] / 2
                        await human_mouse_move(page, x, y)
                        await asyncio.sleep(random.uniform(0.3, 0.8))
                        await page.mouse.click(x, y, delay=random.randint(50, 150))
                except Exception:
                    pass

            await asyncio.sleep(1.0)

        return None
