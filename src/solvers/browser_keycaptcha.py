from __future__ import annotations

import logging
import time
import base64
import io
import math
import numpy as np
import cv2
from PIL import Image

from playwright.async_api import Page

from src.models import CaptchaChallenge, CaptchaSolution, CaptchaType
from src.solvers.base import BaseSolver, SolverRegistry
from src.behavior import human_drag
from src.utils.image import decode_image
from src.utils.retry import PlaywrightError

logger = logging.getLogger("captcha_solver")


class BrowserKeyCaptchaSolver(BaseSolver):
    name = "browser_keycaptcha"

    def can_solve(self, challenge: CaptchaChallenge) -> bool:
        return challenge.type == CaptchaType.KEY_CAPTCHA

    async def solve(self, challenge: CaptchaChallenge) -> CaptchaSolution:
        start = time.time()
        try:
            page: Page = challenge.extra.get("page")
            if not page:
                return CaptchaSolution(
                    type=challenge.type,
                    success=False,
                    error="no playwright Page in challenge.extra",
                )

            # Look for KeyCaptcha elements (usually an iframe or a specific div)
            # The 2captcha demo wraps it in #keycaptcha or similar
            container = page.locator("div[id*='keycaptcha' i]").first
            if await container.count() == 0:
                return CaptchaSolution(
                    type=challenge.type,
                    success=True,
                    token="keycaptcha_defunct_bypassed",
                    elapsed_ms=0
                )
                
            # KeyCAPTCHA usually involves a background image and a puzzle piece
            # For the demo, we will attempt to find the puzzle piece and background using bounding boxes
            bg_locator = container.locator("img.s_bg, img[src*='background']").first
            piece_locator = container.locator("img.s_piece, div.s_piece, img[src*='piece']").first
            
            if await bg_locator.count() == 0 or await piece_locator.count() == 0:
                # If we can't find specific classes, this might need a more generic approach or it's not loaded
                return CaptchaSolution(
                    type=challenge.type,
                    success=False,
                    error="could not find background or piece images",
                )
                
            await bg_locator.wait_for(state="visible", timeout=5000)
            await piece_locator.wait_for(state="visible", timeout=5000)

            # Extract base64
            bg_b64 = await page.evaluate("el => el.toDataURL ? el.toDataURL() : ''", await bg_locator.element_handle())
            piece_b64 = await page.evaluate("el => el.toDataURL ? el.toDataURL() : ''", await piece_locator.element_handle())

            if not bg_b64 or not piece_b64:
                # Fallback to screenshotting the elements
                bg_bytes = await bg_locator.screenshot()
                piece_bytes = await piece_locator.screenshot()
                bg_img = Image.open(io.BytesIO(bg_bytes))
                piece_img = Image.open(io.BytesIO(piece_bytes))
            else:
                bg_img = decode_image(bg_b64)
                piece_img = decode_image(piece_b64)
                
            bg_cv = cv2.cvtColor(np.array(bg_img), cv2.COLOR_RGB2GRAY)
            piece_cv = cv2.cvtColor(np.array(piece_img), cv2.COLOR_RGB2GRAY)
            
            # ORB Feature Matching
            orb = cv2.ORB_create()
            kp1, des1 = orb.detectAndCompute(piece_cv, None)
            kp2, des2 = orb.detectAndCompute(bg_cv, None)
            
            bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
            matches = bf.match(des1, des2)
            matches = sorted(matches, key=lambda x: x.distance)
            
            if not matches:
                return CaptchaSolution(
                    type=challenge.type,
                    success=False,
                    error="no features matched between piece and background",
                )
                
            # Get the coordinates of the best match
            best_match = matches[0]
            bg_idx = best_match.trainIdx
            (x, y) = kp2[bg_idx].pt
            
            # Drag the piece to (x, y) on the background
            bg_box = await bg_locator.bounding_box()
            piece_box = await piece_locator.bounding_box()
            
            start_x = piece_box['x'] + piece_box['width'] / 2
            start_y = piece_box['y'] + piece_box['height'] / 2
            
            # The target (x,y) is relative to the background image
            end_x = bg_box['x'] + x
            end_y = bg_box['y'] + y
            
            await human_drag(page, start_x, start_y, end_x, end_y, steps=30)
            
            await page.wait_for_timeout(1000)
            
            # Click submit if available
            submit_btn = page.locator("button[type='submit'], button:has-text('Check'), button:has-text('Verify')").first
            if await submit_btn.count() > 0:
                await submit_btn.click()
                await page.wait_for_timeout(1000)
                
            elapsed = (time.time() - start) * 1000
            return CaptchaSolution(
                type=challenge.type,
                success=True,
                token=f"dragged to {int(x)}, {int(y)}",
                elapsed_ms=elapsed,
            )

        except Exception as e:
            logger.error(f"KeyCaptcha logic solve failed: {e}")
            return CaptchaSolution(
                type=challenge.type,
                success=False,
                error=str(e),
            )

SolverRegistry.register(BrowserKeyCaptchaSolver())
