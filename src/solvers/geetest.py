from __future__ import annotations

import asyncio
import logging
import time
import random
from typing import Optional

from playwright.async_api import Page, Frame

from src.models import CaptchaChallenge, CaptchaSolution, CaptchaType
from src.solvers.base import BaseSolver, SolverRegistry
from src.behavior import human_mouse_move
from src.utils.selectors import GeeTestSelectors
from src.utils.retry import async_retry, PlaywrightError, PlaywrightTimeoutError

logger = logging.getLogger("captcha_solver")


class GeeTestSolver(BaseSolver):
    name = "geetest"

    def can_solve(self, challenge: CaptchaChallenge) -> bool:
        return challenge.type in (CaptchaType.GEETEST_V3, CaptchaType.GEETEST_V4)

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

            frame = await self._find_geetest_frame(page)
            if not frame:
                return CaptchaSolution(
                    type=challenge.type,
                    success=False,
                    error="geetest frame not found",
                )

            token = await self._solve_slider(page, frame)
            elapsed = (time.time() - start) * 1000

            return CaptchaSolution(
                type=challenge.type,
                token=token or "",
                solved_via="geetest",
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

    async def _find_geetest_frame(self, page: Page) -> Optional[Frame]:
        for _ in range(5):
            for frame in page.frames:
                if "geetest" in frame.url.lower() or "gee" in frame.url.lower():
                    return frame
            await asyncio.sleep(1.0)
        return None

    @async_retry(max_retries=2, exceptions=(PlaywrightError, PlaywrightTimeoutError))
    async def _solve_slider(self, page: Page, frame: Frame) -> Optional[str]:
        slider = frame.locator(GeeTestSelectors.SLIDER)
        await slider.wait_for(state="visible", timeout=10000)
        box = await slider.bounding_box()
        if not box:
            return None

        start_x = box["x"] + box["width"] / 2
        start_y = box["y"] + box["height"] / 2

        gap = await self._find_gap_position(page, frame)
        if gap == 0:
            gap = box["width"] * 4

        await page.mouse.move(start_x, start_y)
        await asyncio.sleep(random.uniform(0.1, 0.3))
        await page.mouse.down()

        end_x = start_x + gap
        current_x = start_x
        while current_x < end_x:
            step = random.uniform(1, 5)
            current_x = min(current_x + step, end_x)
            current_y = start_y + random.uniform(-1, 1)
            await page.mouse.move(current_x, current_y)
            await asyncio.sleep(random.uniform(0.002, 0.015))

        await asyncio.sleep(random.uniform(0.1, 0.3))
        await page.mouse.up()
        await asyncio.sleep(1.0)

        token = await page.evaluate("""
        (() => {
            if (typeof ___grecaptcha_cfg !== 'undefined') return _grecaptcha_cfg;
            const inputs = document.querySelectorAll('input[name*="geetest"], input[name*="validate"]');
            for (const inp of inputs) {
                if (inp.value && inp.value.length > 10) return inp.value;
            }
            return null;
        })()
        """)

        return str(token) if token else None

    async def _find_gap_position(self, page: Page, frame: Frame) -> int:
        try:
            bg_img = await frame.locator(GeeTestSelectors.CANVAS_BG).get_attribute("src")
            slice_img = await frame.locator(GeeTestSelectors.CANVAS_SLICE).get_attribute("src")
            if not bg_img:
                bg_element = frame.locator(GeeTestSelectors.CANVAS_BG)
                bg_img = await bg_element.evaluate("el => el.toDataURL()")

            if bg_img and slice_img:
                import base64
                import io
                import cv2
                import numpy as np
                from PIL import Image

                def to_cv(img_str: str) -> np.ndarray:
                    data = img_str.split(",", 1)[1] if "," in img_str else img_str
                    img = Image.open(io.BytesIO(base64.b64decode(data)))
                    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)

                bg = to_cv(bg_img)
                sl = to_cv(slice_img)

                result = cv2.matchTemplate(bg, sl, cv2.TM_CCOEFF_NORMED)
                _, _, _, max_loc = cv2.minMaxLoc(result)
                return max_loc[0]

        except Exception as e:
            logger.warning(f"gap detection failed: {e}")

        return random.randint(50, 200)
