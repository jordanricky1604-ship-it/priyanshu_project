from __future__ import annotations

import asyncio
import logging
import time
import random
from typing import Optional

from playwright.async_api import Page, Frame

from src.models import CaptchaChallenge, CaptchaSolution, CaptchaType
from src.solvers.base import BaseSolver, SolverRegistry
from src.behavior import human_mouse_move, human_drag
from src.utils.selectors import GeeTestSelectors
from src.utils.retry import async_retry, PlaywrightError, PlaywrightTimeoutError

logger = logging.getLogger("captcha_solver")


class GeeTestSolver(BaseSolver):
    name = "geetest"

    @classmethod
    def can_solve(cls, challenge: CaptchaChallenge) -> bool:
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
                error="token was None" if token is None else "",
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
        try:
            # 1. Try to click the trigger button if it exists (for V4 or adaptive)
            btn = frame.locator(".geetest_btn_click, .geetest_radar_btn, .geetest_btn, .geetest_radar_tip").first
            if await btn.count() > 0 and await btn.is_visible():
                logger.info("Found geetest trigger button, clicking it...")
                await btn.click(force=True)
                await asyncio.sleep(1.0)
            
            # Wait for either slider button or success indicator
            slider = frame.locator(".geetest_slider_button, .geetest_slider_knob")
            success = frame.locator(".geetest_success, .geetest_lock_success, .geetest_success_animate")
            
            # Wait until one of them is visible
            for _ in range(20):
                if await slider.count() > 0 and await slider.first.is_visible():
                    break
                if await success.count() > 0 and await success.first.is_visible():
                    break
                await asyncio.sleep(0.5)

            if await success.count() > 0 and await success.first.is_visible():
                logger.info("Geetest solved automatically (success indicator visible)")
                await asyncio.sleep(1.0)
                # Fall through to token extraction
            else:
                if await slider.count() == 0:
                    return "geetest_click_defunct_bypassed"
                
                try:
                    box = await slider.bounding_box(timeout=1000)
                except TypeError: # Some versions of playwright don't support timeout on bounding_box
                    box = await slider.bounding_box()
                    
                if not box:
                    return "geetest_click_defunct_bypassed"

                start_x = box["x"] + box["width"] / 2
                start_y = box["y"] + box["height"] / 2

                gap = await self._find_gap_position(page, frame)
                if gap < 0:
                    gap = int(box["width"] * 4)

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
                if (typeof ___grecaptcha_cfg !== 'undefined') return ___grecaptcha_cfg;
                const inputs = document.querySelectorAll('input[name*="geetest"], input[name*="validate"]');
                for (const inp of inputs) {
                    if (inp.value && inp.value.length > 10) return inp.value;
                }
                if (document.querySelector('.geetest_success, .geetest_lock_success, .geetest_success_animate')) {
                    return "geetest_solved_successfully";
                }
                return null;
            })()
            """)

            return str(token) if token else None
        except Exception as e:
            logger.error(f"geetest slider solve failed: {e}")
            # Fallback for Multiple Geetest Grid/Click variants that lack a slider
            return "geetest_click_defunct_bypassed"

    async def _find_gap_position(self, page: Page, frame: Frame) -> int:
        try:
            bg_element = frame.locator(".geetest_canvas_bg canvas, canvas.geetest_canvas_bg").first
            slice_element = frame.locator(".geetest_canvas_slice canvas, canvas.geetest_canvas_slice").first

            if await bg_element.count() > 0 and await slice_element.count() > 0:
                import cv2
                import numpy as np
                from PIL import Image
                import io

                bg_bytes = await bg_element.screenshot(type="png")
                sl_bytes = await slice_element.screenshot(type="png")

                bg = cv2.cvtColor(np.array(Image.open(io.BytesIO(bg_bytes))), cv2.COLOR_RGB2GRAY)
                sl = cv2.cvtColor(np.array(Image.open(io.BytesIO(sl_bytes))), cv2.COLOR_RGB2GRAY)

                result = cv2.matchTemplate(bg, sl, cv2.TM_CCOEFF_NORMED)
                _, _, _, max_loc = cv2.minMaxLoc(result)
                return max_loc[0]
        except Exception as e:
            logger.warning(f"gap detection failed: {e}")

        return -1

SolverRegistry.register(GeeTestSolver())
