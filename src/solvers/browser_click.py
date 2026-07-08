from __future__ import annotations

import logging
import time
import base64
import io
from PIL import Image

from playwright.async_api import Page

from src.models import CaptchaChallenge, CaptchaSolution, CaptchaType
from src.solvers.base import BaseSolver, SolverRegistry
from src.behavior import human_mouse_move
from src.utils.image import decode_image
from src.utils.retry import PlaywrightError

logger = logging.getLogger("captcha_solver")


from src.utils.model_manager import ModelManager

class BrowserClickSolver(BaseSolver):
    name = "browser_click"

    def __init__(self, model_manager: ModelManager | None = None):
        self.model_manager = model_manager or ModelManager()

    def can_solve(self, challenge: CaptchaChallenge) -> bool:
        return challenge.type == CaptchaType.CLICK_OBJECTS

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
            img_locator = page.locator("img[alt*='clickcaptcha' i], #rc-imageselect-target").first
            count = await img_locator.count()
            if count == 0:
                return CaptchaSolution(
                    type=challenge.type,
                    success=False,
                    error="could not find click captcha image on page",
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
                    error="could not extract base64 from click image",
                )

            image = decode_image(b64_img)

            prompt = challenge.extra.get("prompt", ["a distinct object"])
            if isinstance(prompt, str):
                prompt_list = [prompt]
            else:
                prompt_list = prompt

            # 3. Predict coordinates with OwlViT
            processor, model, device = self.model_manager.get_owlvit()
            inputs = processor(text=[prompt_list], images=image, return_tensors="pt").to(device)
            
            # Inference
            import torch
            with torch.no_grad():
                outputs = model(**inputs)
            
            # Get predictions
            target_sizes = torch.tensor([image.size[::-1]])
            results = processor.post_process_grounded_object_detection(outputs, target_sizes=target_sizes, threshold=0.1)[0]
            
            boxes = results["boxes"].tolist()
            scores = results["scores"].tolist()
            labels = results.get("labels", torch.tensor([])).tolist()

            # Get bounding box of the element on the page to calculate absolute coordinates
            box = await img_locator.bounding_box()
            if not box:
                return CaptchaSolution(
                    type=challenge.type,
                    success=False,
                    error="could not get bounding box of click image on page",
                )

            img_x, img_y = box['x'], box['y']

            # Scale factors because the displayed image might be scaled vs the natural image we analyzed
            display_w, display_h = box['width'], box['height']
            natural_w, natural_h = image.size
            scale_x = display_w / natural_w
            scale_y = display_h / natural_h

            if not boxes:
                # Try fallback composite match for 2captcha style demo images
                fallback_coords = self._fallback_composite_match(image)
                if fallback_coords:
                    logger.info(f"OwlViT found nothing, but composite fallback found {len(fallback_coords)} targets.")
                    for (cx, cy) in fallback_coords:
                        target_x = img_x + (cx * scale_x)
                        target_y = img_y + (cy * scale_y)

                        await human_mouse_move(page, target_x, target_y)
                        await page.mouse.click(target_x, target_y)
                        await page.wait_for_timeout(200)

                    # Click submit if available
                    submit_btn = page.locator("button[type='submit'], button:has-text('Check'), button:has-text('Verify')").first
                    if await submit_btn.count() > 0:
                        await human_mouse_move(page, (await submit_btn.bounding_box())['x'] + 10, (await submit_btn.bounding_box())['y'] + 10)
                        await submit_btn.click()
                        await page.wait_for_timeout(1000)

                    elapsed = (time.time() - start) * 1000
                    return CaptchaSolution(
                        type=challenge.type,
                        success=True,
                        token="clicked_fallback",
                        elapsed_ms=elapsed,
                    )

                return CaptchaSolution(
                    type=challenge.type,
                    success=False,
                    error="no objects detected matching prompt and fallback failed",
                )

            logger.info(f"OwlViT detected {len(boxes)} objects matching '{prompt_list}'")

            # Click all detected boxes
            for label_idx, query in enumerate(prompt_list):
                if label_idx not in objects_by_label:
                    logger.warning(f"Object '{query}' not found above threshold, skipping.")
                    continue
                # Get the highest scoring box for this label
                best_box = max(objects_by_label[label_idx], key=lambda x: x[0])[1]
                
                cx = (best_box[0] + best_box[2]) / 2.0
                cy = (best_box[1] + best_box[3]) / 2.0
                
                target_x = img_x + (cx * scale_x)
                target_y = img_y + (cy * scale_y)

                await human_mouse_move(page, target_x, target_y)
                await page.mouse.click(target_x, target_y)
                await page.wait_for_timeout(200)

            # Click submit if available
            submit_btn = page.locator("button[type='submit'], button:has-text('Check'), button:has-text('Verify')").first
            if await submit_btn.count() > 0:
                await human_mouse_move(page, (await submit_btn.bounding_box())['x'] + 10, (await submit_btn.bounding_box())['y'] + 10)
                await submit_btn.click()
                await page.wait_for_timeout(1000)

            elapsed = (time.time() - start) * 1000
            return CaptchaSolution(
                type=challenge.type,
                success=True,
                token="clicked",
                elapsed_ms=elapsed,
            )

        except Exception as e:
            logger.error(f"Click logic solve failed: {e}")
            return CaptchaSolution(
                type=challenge.type,
                success=False,
                error=str(e),
            )

    def _fallback_composite_match(self, image: Image.Image) -> list[tuple[float, float]]:
        import cv2
        import numpy as np
        
        # Convert PIL to CV2 grayscale
        img_np = np.array(image)
        if len(img_np.shape) == 3:
            gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
        else:
            gray = img_np
            
        # Top 50px usually contains the instruction and icons
        top = gray[:50, :]
        bottom = gray[50:, :]
        
        # Binarize top part
        _, thresh = cv2.threshold(top, 200, 255, cv2.THRESH_BINARY_INV)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        icons = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if 10 < w < 40 and 10 < h < 40:
                # Text usually on left, icons on right (x > 50)
                if x > 50:
                    icon_img = gray[y:y+h, x:x+w]
                    icons.append({'x': x, 'img': icon_img, 'rect': (x,y,w,h)})
                    
        # Sort by x coordinate to click in order
        icons.sort(key=lambda i: i['x'])
        
        target_coords = []
        for icon in icons:
            res = cv2.matchTemplate(bottom, icon['img'], cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
            if max_val > 0.4:
                target_x = max_loc[0] + icon['img'].shape[1] / 2.0
                target_y = 50 + max_loc[1] + icon['img'].shape[0] / 2.0
                target_coords.append((target_x, target_y))
                
        return target_coords

SolverRegistry.register(BrowserClickSolver())

