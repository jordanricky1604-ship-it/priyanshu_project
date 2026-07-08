from __future__ import annotations

import logging
import time
import asyncio

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from src.models import CaptchaChallenge, CaptchaSolution, CaptchaType
from src.solvers.base import BaseSolver, SolverRegistry
from src.utils.image import preprocess_for_ocr, decode_image, pil_to_numpy
from src.utils.model_manager import ModelManager

logger = logging.getLogger("captcha_solver")


class BrowserImageSolver(BaseSolver):
    name = "browser_image"

    def __init__(self, model_manager: ModelManager | None = None):
        self.model_manager = model_manager or ModelManager()

    def can_solve(self, challenge: CaptchaChallenge) -> bool:
        return challenge.type == CaptchaType.IMAGE_CAPTCHA

    async def solve(self, challenge: CaptchaChallenge) -> CaptchaSolution:
        start = time.time()
        page: Page | None = challenge.extra.get("page")
        if not page:
            return CaptchaSolution(
                type=CaptchaType.IMAGE_CAPTCHA,
                success=False,
                error="No browser page provided in challenge.extra",
            )

        try:
            # 1. Locate the CAPTCHA image (exclude logos, prefer inside a form)
            img_selector = 'form img[src*="captcha" i], form img, main img[src*="captcha" i], img[src*="captcha" i]:not([src*="logo" i]):not([alt*="logo" i]):not(header img):not(nav img)'
            img_locator = page.locator(img_selector).first
            
            try:
                await img_locator.wait_for(state="visible", timeout=10000)
            except PlaywrightTimeoutError:
                return CaptchaSolution(
                    type=CaptchaType.IMAGE_CAPTCHA,
                    success=False,
                    error="Could not find a visible CAPTCHA image on the page",
                    elapsed_ms=(time.time() - start) * 1000,
                )

            # 2. Extract image bytes via screenshot
            logger.info("Extracting CAPTCHA image from DOM...")
            img_bytes = await img_locator.screenshot()

            # 3. Perform OCR
            logger.info("Extracting text to detect captcha type...")
            
            # Run EasyOCR first to detect Math symbols (+, -, *, =)
            reader = self.model_manager.get_easyocr()
            
            img_pil = decode_image(img_bytes)
            img_processed = preprocess_for_ocr(img_pil)
            img_np_processed = pil_to_numpy(img_processed)
            img_np_raw = pil_to_numpy(img_pil)
            
            # EasyOCR with processed image is best for Math symbols
            results_processed = reader.readtext(img_np_processed, detail=1)
            valid_processed = [r for r in results_processed if r[2] > 0.3]
            text_processed = "".join([r[1] for r in valid_processed]).strip()
            
            import re
            
            is_math = any(op in text_processed for op in ["+", "-", "*", "="]) or re.search(r'\d{1,2}[+\-*/]\d{1,2}', text_processed)
            
            if is_math:
                logger.info(f"Detected math symbols in EasyOCR: '{text_processed}'")
                text = text_processed
            else:
                logger.info("No math symbols detected. Using ddddocr for alphanumeric extraction...")
                ocr = self.model_manager.get_ddddocr()
                text = ocr.classification(img_bytes)
                if isinstance(text, str):
                    text = text.strip()
            
            
            # If nothing was found, text is empty
            if not text:
                return CaptchaSolution(
                    type=CaptchaType.IMAGE_CAPTCHA,
                    success=False,
                    error="OCR failed to extract any text",
                    elapsed_ms=(time.time() - start) * 1000,
                )
            
            logger.info(f"OCR successfully extracted text: '{text}'")

            import re
            
            # Basic Math CAPTCHA evaluation
            if any(op in text for op in ["+", "-", "*", "="]) or re.search(r'\d{1,2}[+\-*/]\d{1,2}', text):
                import operator
                
                logger.info(f"Detected possible math expression: '{text}'")
                
                try:
                    # Clean up common OCR mistakes for `=?` at the end
                    clean_text = re.sub(r'3[27]\.?$', '', text)
                    clean_text = re.sub(r'[=?.\s]+$', '', clean_text)
                    
                    # Extract up to 2-digit numbers to avoid trailing garbage
                    m = re.search(r'(\d{1,2})\s*([+\-*/])\s*(\d{1,2})', clean_text)
                    if m:
                        left, op_char, right = m.groups()
                        
                        def evaluate_op(l, op, r):
                            if op == '+': return operator.add(l, r)
                            if op == '-': return operator.sub(l, r)
                            if op == '*': return operator.mul(l, r)
                            return None
                            
                        res = evaluate_op(int(left), op_char, int(right))
                        if res is not None:
                            logger.info(f"Evaluated math expression {left} {op_char} {right} to: '{res}'")
                            text = str(res)
                except Exception as e:
                    logger.warning(f"Failed to evaluate math expression: {e}")
            

            # 4. Locate the corresponding text input field
            logger.info("Looking for CAPTCHA text input...")
            # Prioritize inputs with captcha in the name or id, then fallback to generic text input
            input_locator = page.locator("input[name*='captcha' i]:not([type='hidden']), input[id*='captcha' i]:not([type='hidden']), input[name='code' i]:not([type='hidden']), input[type='text']").first
            
            if not await input_locator.count() > 0:
                return CaptchaSolution(
                    type=CaptchaType.IMAGE_CAPTCHA,
                    success=False,
                    error="Could not find a text input field to type the CAPTCHA solution into",
                    elapsed_ms=(time.time() - start) * 1000,
                )

            # 5. Type the transcription
            logger.info("Typing OCR transcription into input field...")
            await input_locator.fill(text)
            
            # Wait a tiny bit just to ensure events fire
            await asyncio.sleep(0.5)
            
            # 6. Verify result if on a known demo page
            try:
                submit_btn = page.locator("button[type='submit'], input[type='submit'], input[type='button'][value*='Check' i], input[type='button'][value*='Validate' i], button:has-text('Check'), button:has-text('Validate')").first
                if await submit_btn.is_visible(timeout=1000):
                    await submit_btn.click()
                    await asyncio.sleep(2.0)
                    
                    # Check for failure text
                    body_text = await page.evaluate("document.body.innerText")
                    body_lower = body_text.lower()
                    if "incorrect" in body_lower or "failed" in body_lower or "wrong" in body_lower:
                        return CaptchaSolution(
                            type=CaptchaType.IMAGE_CAPTCHA,
                            success=False,
                            error=f"OCR extracted '{text}' but the website rejected it as incorrect.",
                            elapsed_ms=(time.time() - start) * 1000,
                        )
            except Exception:
                pass
            
            return CaptchaSolution(
                type=CaptchaType.IMAGE_CAPTCHA,
                success=True,
                token=text,
                image_bytes=img_bytes,
                attempts=1,
                elapsed_ms=(time.time() - start) * 1000,
            )

        except Exception as e:
            logger.error(f"BrowserImageSolver error: {e}")
            elapsed = (time.time() - start) * 1000
            return CaptchaSolution(
                type=CaptchaType.IMAGE_CAPTCHA,
                success=False,
                error=str(e),
                elapsed_ms=elapsed,
            )

SolverRegistry.register(BrowserImageSolver())