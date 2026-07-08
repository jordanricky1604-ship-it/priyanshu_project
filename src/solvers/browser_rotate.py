from __future__ import annotations

import logging
import time
import base64
import io
import math
from PIL import Image

from playwright.async_api import Page

from src.models import CaptchaChallenge, CaptchaSolution, CaptchaType
from src.solvers.base import BaseSolver, SolverRegistry
from src.utils.image import decode_image
from src.utils.retry import PlaywrightError

logger = logging.getLogger("captcha_solver")


from src.utils.model_manager import ModelManager

class BrowserRotateSolver(BaseSolver):
    name = "browser_rotate"

    def __init__(self, model_manager: ModelManager | None = None):
        self.model_manager = model_manager or ModelManager()

    def can_solve(self, challenge: CaptchaChallenge) -> bool:
        return challenge.type == CaptchaType.ROTATE_IMAGE

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

            # Find the image
            img_locator = page.locator("img[alt*='rotatecaptcha' i], img[class*='rotate' i]").first
            count = await img_locator.count()
            if count == 0:
                return CaptchaSolution(
                    type=challenge.type,
                    success=False,
                    error="could not find rotate captcha image on page",
                )
            
            # Wait for image to load
            await img_locator.wait_for(state="visible", timeout=5000)

            # Extract the image
            b64_img = await page.evaluate("""(img) => {
                let canvas = document.createElement('canvas');
                canvas.width = img.naturalWidth || img.width;
                canvas.height = img.naturalHeight || img.height;
                let ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0);
                return canvas.toDataURL('image/png').split(',')[1];
            }""", await img_locator.element_handle())

            if not b64_img:
                return CaptchaSolution(
                    type=challenge.type,
                    success=False,
                    error="could not extract base64 from rotate image",
                )

            original_image = decode_image(b64_img)

            # Create multiple rotations to evaluate
            angles = [0, 45, 90, 135, 180, 225, 270, 315]
            
            # Predict best rotation with CLIP
            model, preprocess, tokenizer, device = self.model_manager.get_clip()
            
            # Rotate image at multiple angles and find highest CLIP confidence for "an upright photo"
            import torch
            best_angle = 0
            best_score = -1.0
            
            # Test 8 angles (0, 45, 90, 135, 180, 225, 270, 315)
            angles = [0, 45, 90, 135, 180, 225, 270, 315]
            images = []
            for angle in angles:
                rotated = original_image.rotate(-angle, resample=Image.BICUBIC, expand=True) # rotate counter-clockwise
                images.append(preprocess(rotated).unsqueeze(0))
            
            image_input = torch.cat(images).to(device)
            text_input = tokenizer(["an upright photo"]).to(device)
            
            with torch.no_grad():
                image_features = model.encode_image(image_input)
                text_features = model.encode_text(text_input)
                
                image_features /= image_features.norm(dim=-1, keepdim=True)
                text_features /= text_features.norm(dim=-1, keepdim=True)
                
                similarity = (100.0 * image_features @ text_features.T).squeeze()
                
            scores = similarity.tolist()
            if not isinstance(scores, list):
                scores = [scores]
                
            best_idx = scores.index(max(scores))
            best_angle = angles[best_idx]
            
            logger.info(f"Determined best angle to rotate is {best_angle} degrees")

            # Click the rotate button to match the angle
            # For 2captcha demo, each click of the right button rotates by ~40-45 degrees.
            clicks_needed = round(best_angle / 45)
            
            right_btn = page.locator("button[class*='rotateRightBtn'], button[title*='right']").first
            if await right_btn.count() > 0:
                for _ in range(clicks_needed):
                    await right_btn.click()
                    await page.wait_for_timeout(200)

            # Submit
            submit_btn = page.locator("button[type='submit'], button:has-text('Check'), button:has-text('Verify')").first
            if await submit_btn.count() > 0:
                await submit_btn.click()
                await page.wait_for_timeout(1000)

            elapsed = (time.time() - start) * 1000
            return CaptchaSolution(
                type=challenge.type,
                success=True,
                token=f"rotated {best_angle}deg",
                elapsed_ms=elapsed,
            )

        except Exception as e:
            logger.error(f"Rotate logic solve failed: {e}")
            return CaptchaSolution(
                type=challenge.type,
                success=False,
                error=str(e),
            )

SolverRegistry.register(BrowserRotateSolver())
