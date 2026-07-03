from __future__ import annotations

import asyncio
import logging
import time
import random
from typing import Optional

from playwright.async_api import Page, Frame

from src.models import CaptchaChallenge, CaptchaSolution, CaptchaType
from src.solvers.base import BaseSolver, SolverRegistry
from src.solvers.image_classifier import ImageClassifierSolver
from src.behavior import human_click, human_mouse_move
from src.utils.selectors import FunCaptchaSelectors
from src.utils.retry import async_retry, PlaywrightError, PlaywrightTimeoutError

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

            token = await self._solve_challenge(page, frame)
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

    @async_retry(max_retries=2, exceptions=(PlaywrightError, PlaywrightTimeoutError))
    async def _click_verify_btn(self, page: Page, frame: Frame) -> None:
        verify_btn = frame.locator(FunCaptchaSelectors.SUBMIT_BUTTON)
        if await verify_btn.count():
            await human_click(page, verify_btn)
            await asyncio.sleep(2.0)

    @async_retry(max_retries=2, exceptions=(PlaywrightError, PlaywrightTimeoutError))
    async def _click_image(self, page: Page, img: Any) -> None:
        box = await img.bounding_box()
        if box:
            x = box["x"] + box["width"] / 2
            y = box["y"] + box["height"] / 2
            await human_mouse_move(page, x, y)
            await asyncio.sleep(random.uniform(0.3, 0.8))
            await page.mouse.click(x, y, delay=random.randint(50, 150))

    async def _solve_challenge(self, page: Page, frame: Frame) -> Optional[str]:
        for attempt in range(5):
            try:
                await self._click_verify_btn(page, frame)
            except Exception as e:
                logger.warning(f"Failed to click FunCaptcha verify: {e}")

            token = await page.evaluate("""
            (() => {
                try { return _funcaptcha_token || _funcaptcha_response; } catch(e) {}
                try { return _arkose_token || _arkose_response; } catch(e) {}
                return null;
            })()
            """)
            if token and isinstance(token, str) and len(token) > 10:
                return str(token)

            # 1. Extract Prompt
            prompt_loc = frame.locator(FunCaptchaSelectors.PROMPT).first
            if await prompt_loc.count() > 0:
                prompt_text = await prompt_loc.inner_text()
            else:
                prompt_text = "pick the correct object"

            logger.info(f"FunCaptcha prompt: {prompt_text}")

            # 2. Extract Images
            images = frame.locator(FunCaptchaSelectors.IMAGES)
            count = await images.count()
            if count == 0:
                await asyncio.sleep(1.0)
                continue

            best_index = 0
            # If multiple images, use CLIP to score each and pick the best one
            if count > 1:
                logger.info(f"Scoring {count} images with CLIP...")
                # We instantiate the image classifier solver to reuse its CLIP logic
                classifier = ImageClassifierSolver()
                model, preprocess, tokenizer, device = classifier.model_manager.get_clip()
                import torch
                
                labels = classifier._get_labels_for_prompt(prompt_text)
                text_tokens = tokenizer(labels).to(device)
                
                with torch.no_grad():
                    text_features = model.encode_text(text_tokens)
                    text_features = text_features / text_features.norm(dim=-1, keepdim=True)
                
                best_score = -1.0
                
                for i in range(count):
                    try:
                        img_loc = images.nth(i)
                        # Some Arkose implementations use background-image, others use img src
                        b64_data = await img_loc.evaluate('''el => {
                            if (el.tagName === 'IMG') {
                                if (el.src.startsWith('data:image')) return el.src;
                                const canvas = document.createElement('canvas');
                                canvas.width = el.width; canvas.height = el.height;
                                const ctx = canvas.getContext('2d');
                                ctx.drawImage(el, 0, 0);
                                return canvas.toDataURL();
                            } else {
                                const bg = window.getComputedStyle(el).backgroundImage;
                                return bg.replace('url("', '').replace('")', '');
                            }
                        }''')
                        
                        if b64_data and b64_data.startswith('data:image'):
                            from src.utils.image import decode_image
                            img_obj = decode_image(b64_data)
                            tile = preprocess(img_obj).unsqueeze(0).to(device)
                            
                            with torch.no_grad():
                                image_features = model.encode_image(tile)
                                image_features = image_features / image_features.norm(dim=-1, keepdim=True)
                                similarity = (100.0 * image_features @ text_features.T).softmax(dim=-1)
                                score = similarity[0].max().item()
                                
                                if score > best_score:
                                    best_score = score
                                    best_index = i
                    except Exception as e:
                        logger.warning(f"Error extracting/scoring image {i}: {e}")

            logger.info(f"Clicking image at index {best_index}")
            try:
                await self._click_image(page, images.nth(best_index))
            except Exception as e:
                logger.warning(f"Failed to click FunCaptcha image: {e}")

            await asyncio.sleep(2.0)

        return None
