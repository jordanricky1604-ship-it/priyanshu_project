from __future__ import annotations

import asyncio
import logging
import time
import base64
import re
import random
from typing import Optional

from playwright.async_api import Page, Frame

from src.models import CaptchaChallenge, CaptchaSolution, CaptchaType, RateLimitException
from src.solvers.base import BaseSolver, SolverRegistry
from src.solvers.audio import AudioSolver
from src.solvers.image_classifier import ImageClassifierSolver
from src.browser import create_context
from src.behavior import human_click, human_type, human_mouse_move, human_prebrowse
from src.utils.selectors import RecaptchaSelectors
from src.utils.model_manager import ModelManager
from src.utils.retry import async_retry, PlaywrightError, PlaywrightTimeoutError
from src.utils.http import fetch_audio_base64_stealth
from src.config import SolverConfig

logger = logging.getLogger("captcha_solver")


class BrowserTokenSolver(BaseSolver):
    name = "browser_token"

    def __init__(self, config: SolverConfig, page: Page, model_manager: ModelManager | None = None):
        self.config = config
        self.page = page
        self.model_manager = model_manager or ModelManager(
            whisper_model_size=config.audio_model_size,
            clip_model_name=config.clip_model_name,
        )
        self._audio_solver = AudioSolver(
            model_manager=self.model_manager,
        )
        self._image_solver = ImageClassifierSolver(
            model_manager=self.model_manager,
        )

    def can_solve(self, challenge: CaptchaChallenge) -> bool:
        return challenge.type in (
            CaptchaType.RECAPTCHA_V2,
            CaptchaType.RECAPTCHA_V2_INVISIBLE,
            CaptchaType.RECAPTCHA_V3,
            CaptchaType.RECAPTCHA_ENTERPRISE,
            CaptchaType.HCAPTCHA,
            CaptchaType.HCAPTCHA_INVISIBLE,
            CaptchaType.TURNSTILE,
            CaptchaType.TURNSTILE_INVISIBLE,
        )

    async def solve(self, challenge: CaptchaChallenge) -> CaptchaSolution:
        start = time.time()
        attempts = 0

        for attempt in range(self.config.max_retries):
            attempts += 1
            try:
                if challenge.type in (CaptchaType.TURNSTILE, CaptchaType.TURNSTILE_INVISIBLE):
                    token = await self._solve_turnstile(challenge)
                elif challenge.type in (CaptchaType.HCAPTCHA, CaptchaType.HCAPTCHA_INVISIBLE):
                    token = await self._solve_hcaptcha(challenge)
                else:
                    token = await self._solve_recaptcha(challenge)

                if token:
                    elapsed = (time.time() - start) * 1000
                    logger.info(f"solved {challenge.type.name} in {elapsed:.0f}ms (attempts={attempts})")
                    return CaptchaSolution(
                        type=challenge.type,
                        token=token,
                        solved_via="browser_token",
                        attempts=attempts,
                        elapsed_ms=elapsed,
                        success=True,
                    )

                if attempt < self.config.max_retries - 1:
                    delay = self.config.retry_delay_ms / 1000.0 * (attempt + 1)
                    logger.info(f"retrying in {delay:.1f}s (attempt {attempt + 2}/{self.config.max_retries})")
                    await asyncio.sleep(delay)

            except RateLimitException as e:
                logger.warning(f"attempt {attempt + 1} hit rate limit: {e}. Aborting retries for this proxy.")
                return CaptchaSolution(
                    type=challenge.type,
                    success=False,
                    error=f"RateLimitException: {e}",
                    attempts=attempts,
                    elapsed_ms=(time.time() - start) * 1000,
                )
            except Exception as e:
                logger.warning(f"attempt {attempt + 1} failed: {e}")

        elapsed = (time.time() - start) * 1000
        return CaptchaSolution(
            type=challenge.type,
            success=False,
            error="max retries exhausted",
            attempts=attempts,
            elapsed_ms=elapsed,
        )

    async def _find_recaptcha_bframe(self) -> Optional[Frame]:
        for frame in self.page.frames:
            if "recaptcha/api2/bframe" in frame.url or "recaptcha/enterprise/bframe" in frame.url:
                return frame
        return None

    async def _solve_recaptcha(self, challenge: CaptchaChallenge) -> Optional[str]:
        await human_prebrowse(self.page)

        if challenge.type == CaptchaType.RECAPTCHA_V3:
            return await self._extract_v3_token(challenge)

        anchor_frame = await self._find_recaptcha_frame()
        if not anchor_frame:
            logger.warning("reCAPTCHA anchor iframe not found")
            return None

        await self._click_checkbox(anchor_frame)
        await asyncio.sleep(3.0)

        token = await self._extract_recaptcha_response(self.page)
        if token:
            logger.info("got token immediately after checkbox")
            return token

        bframe = await self._find_recaptcha_bframe()
        if not bframe:
            logger.warning("reCAPTCHA bframe not found after checkbox")
            return None

        logger.info("challenge bframe found, solving...")

        for audio_round in range(5):
            # Audio-First Logic
            audio_btn = bframe.locator(RecaptchaSelectors.AUDIO_BUTTON).first
            try:
                if await audio_btn.is_visible(timeout=1500):
                    logger.info("reCAPTCHA audio button found, prioritizing audio method...")
                    await self._switch_to_audio(bframe)
            except Exception:
                pass

            body_text = await bframe.locator("body").inner_text()
            # If we are STILL on an image challenge (audio switch failed or missing)
            if "Select all" in body_text or "Click verify" in body_text:
                logger.info("Falling back to reCAPTCHA image challenge")
                from src.metrics import CAPTCHA_FALLBACKS_TOTAL
                CAPTCHA_FALLBACKS_TOTAL.labels(captcha_type=CaptchaType.RECAPTCHA_V2.value, fallback_reason="audio_unavailable_or_failed").inc()
                await self._solve_image_challenge(bframe, self.page)
                await asyncio.sleep(2.0)
                token = await self._extract_recaptcha_response(self.page)
                if token:
                    return token
                continue

            try:
                answer = await self._solve_audio_challenge(bframe)
                if not answer:
                    logger.warning("audio challenge returned no answer, falling back to image...")
                    await self._switch_to_image(bframe)
                    await self._solve_image_challenge(bframe, self.page)
                    await asyncio.sleep(2.0)
                    continue
            except Exception as e:
                logger.warning(f"audio challenge failed: {e}")
                logger.info("Falling back to reCAPTCHA image challenge")
                from src.metrics import CAPTCHA_FALLBACKS_TOTAL
                CAPTCHA_FALLBACKS_TOTAL.labels(captcha_type=CaptchaType.RECAPTCHA_V2.value, fallback_reason="audio_error").inc()
                await self._switch_to_image(bframe)
                await self._solve_image_challenge(bframe, self.page)
                await asyncio.sleep(2.0)
                continue

            await self._type_audio_answer(bframe, answer)
            await self._click_verify(bframe)
            await asyncio.sleep(3.0)

            token = await self._extract_recaptcha_response(self.page)
            if token:
                return token

            body_text = await bframe.locator("body").inner_text()
            if "Press PLAY" not in body_text and "Select all" not in body_text:
                break
            logger.info(f"audio round {audio_round + 2} needed...")

        return await self._extract_recaptcha_response(self.page)

    @async_retry(max_retries=2, exceptions=(PlaywrightError, PlaywrightTimeoutError))
    async def _switch_to_audio(self, frame: Frame) -> bool:
        audio_btn = frame.locator(RecaptchaSelectors.AUDIO_BUTTON).first
        await audio_btn.click(timeout=5000, force=True)
        logger.info("switched to audio challenge")
        await asyncio.sleep(3.0)
        return True

    @async_retry(max_retries=2, exceptions=(PlaywrightError, PlaywrightTimeoutError))
    async def _switch_to_image(self, frame: Frame) -> bool:
        try:
            image_btn = frame.locator("#recaptcha-image-button, button[title*='image'], button[title*='Get a visual challenge'], .button-image").first
            if await image_btn.is_visible(timeout=2000):
                await image_btn.click(force=True)
                logger.info("switched back to image challenge")
                await asyncio.sleep(2.0)
                return True
        except Exception as e:
            logger.warning(f"failed to switch to image challenge: {e}")
        return False

    async def _solve_hcaptcha(self, challenge: CaptchaChallenge) -> Optional[str]:
        await human_prebrowse(self.page)

        hcaptcha_frame = await self._find_hcaptcha_frame()
        if not hcaptcha_frame:
            logger.warning("hCaptcha iframe not found")
            return None

        await self._click_hcaptcha_checkbox(hcaptcha_frame)

        await asyncio.sleep(2.0)
        token = await self._extract_hcaptcha_response(self.page)
        if token:
            return token

        # Audio-First Logic:
        audio_btn = hcaptcha_frame.locator(RecaptchaSelectors.AUDIO_BUTTON).first
        try:
            if await audio_btn.is_visible(timeout=3000):
                logger.info("hCaptcha audio button found, prioritizing audio method...")
                await audio_btn.click(force=True, timeout=5000)
                await asyncio.sleep(2.0)
                
                answer = await self._solve_audio_challenge(hcaptcha_frame)
                if answer:
                    await self._type_audio_answer(hcaptcha_frame, answer)
                    await self._click_verify(hcaptcha_frame)
                    await asyncio.sleep(2.0)
                    token = await self._extract_hcaptcha_response(self.page)
                    if token:
                        return token
        except Exception as e:
            logger.info(f"hCaptcha audio switch/solve failed, falling back to image: {e}")

        logger.info("Falling back to hCaptcha image challenge")
        await self._solve_image_challenge(hcaptcha_frame, self.page)
        await asyncio.sleep(2.0)
        return await self._extract_hcaptcha_response(self.page)

    async def _solve_turnstile(self, challenge: CaptchaChallenge) -> Optional[str]:
        await human_prebrowse(self.page)
        await asyncio.sleep(2.0)

        for _ in range(15):
            try:
                turnstile_frame = None
                for frame in self.page.frames:
                    if 'turnstile' in frame.url and 'challenges' in frame.url:
                        turnstile_frame = frame
                        break
                
                if turnstile_frame:
                    checkbox = turnstile_frame.locator('input[type="checkbox"]')
                    if await checkbox.count() > 0:
                        await checkbox.first.click(force=True)
                    else:
                        await turnstile_frame.locator('body').click(force=True)
            except Exception:
                pass

            token = await self._extract_turnstile_response(self.page)
            if token:
                return token
            await asyncio.sleep(1.0)

        return None

    async def _find_recaptcha_frame(self) -> Optional[Frame]:
        for _ in range(10):
            for frame in self.page.frames:
                if "recaptcha/api2/anchor" in frame.url or "recaptcha/enterprise/anchor" in frame.url:
                    return frame
            await asyncio.sleep(0.5)
        return None

    async def _find_hcaptcha_frame(self) -> Optional[Frame]:
        for _ in range(10):
            for frame in self.page.frames:
                if "hcaptcha.com/captcha" in frame.url:
                    return frame
            await asyncio.sleep(0.5)
        return None

    @async_retry(max_retries=3, exceptions=(PlaywrightError, PlaywrightTimeoutError))
    async def _click_checkbox(self, frame: Frame) -> None:
        try:
            checkbox = frame.locator(RecaptchaSelectors.CHECKBOX).first
            await checkbox.wait_for(state="visible", timeout=10000)
            box = await checkbox.bounding_box()
            if box:
                x = box["x"] + box["width"] / 2
                y = box["y"] + box["height"] / 2
                await human_mouse_move(frame.page, x, y)
                await asyncio.sleep(random.uniform(0.1, 0.4))
                await frame.page.mouse.click(x, y, delay=random.randint(50, 200))
                logger.info("clicked reCAPTCHA checkbox")
            else:
                await checkbox.click(delay=random.randint(100, 300), timeout=5000)
                logger.info("clicked reCAPTCHA checkbox (direct)")
        except Exception as e:
            logger.warning(f"checkbox click failed or not found (might be invisible): {e}")

    @async_retry(max_retries=3, exceptions=(PlaywrightError, PlaywrightTimeoutError))
    async def _click_hcaptcha_checkbox(self, frame: Frame) -> None:
        checkbox = frame.locator(RecaptchaSelectors.CHECKBOX_ALTERNATE)
        await human_click(frame.page, checkbox)
        logger.info("clicked hCaptcha checkbox")

    async def _wait_for_challenge(self, frame: Frame) -> bool:
        for _ in range(5):
            try:
                visible = await frame.locator(RecaptchaSelectors.CHALLENGE_FRAME).is_visible()
                if visible:
                    return True
            except Exception:
                pass
            await asyncio.sleep(1.0)
        return False

    async def _solve_audio_challenge(self, frame: Frame) -> Optional[str]:
        try:
            body_text = await frame.locator("body").inner_text()
            logger.info(f"frame body snippet: {body_text[:300]}")

            if "Press PLAY" in body_text or "PLAY" in body_text:
                pass
            elif "Select all" in body_text or "Click verify" in body_text:
                audio_btn = frame.locator(RecaptchaSelectors.AUDIO_BUTTON).first
                await audio_btn.click(timeout=5000, force=True)
                logger.info("switched to audio challenge")
                await asyncio.sleep(3.0)
            if "Try again later" in body_text:
                logger.warning("rate limited by Google (403), throwing RateLimitException")
                raise RateLimitException("Google rate limit hit (Try again later)")

            play_btn = frame.locator(RecaptchaSelectors.PLAY_BUTTON).first
            await play_btn.click(timeout=8000, force=True)
            logger.info("clicked PLAY")
            await asyncio.sleep(4.0)

        except RateLimitException:
            raise
        except Exception as e:
            logger.warning(f"audio challenge activation failed: {e}")
            return None

        try:
            audio_src = None

            all_audio = await frame.evaluate("""
            (() => {
                const elements = [];
                document.querySelectorAll('audio, audio source, a[href*="mp3"], a[href*="audio"], .rc-audiochallenge-tdownload-link').forEach(el => {
                    elements.push({tag: el.tagName, src: el.src || el.href, id: el.id, class: el.className});
                });
                return elements;
            })()
            """)
            logger.info(f"audio elements found: {all_audio}")

            for item in all_audio:
                if item.get("src"):
                    audio_src = item["src"]
                    break

            if not audio_src:
                audio_el = frame.locator(RecaptchaSelectors.AUDIO_ELEMENT).first
                audio_src = await audio_el.get_attribute("src", timeout=3000)
            if not audio_src:
                src_el = frame.locator(RecaptchaSelectors.AUDIO_SOURCE).first
                audio_src = await src_el.get_attribute("src", timeout=3000)
            if not audio_src:
                download = frame.locator(RecaptchaSelectors.DOWNLOAD_LINK).first
                audio_src = await download.get_attribute("href", timeout=3000)

            if audio_src:
                logger.info(f"fetching audio from {audio_src} via stealth client")
                audio_b64 = await fetch_audio_base64_stealth(audio_src, referer=self.page.url)
                
                if not audio_b64:
                    logger.warning("stealth fetch failed, falling back to browser fetch")
                    audio_b64 = await self.page.evaluate(f"""
                    (async () => {{
                        const resp = await fetch('{audio_src}');
                        const blob = await resp.blob();
                        return new Promise((resolve) => {{
                            const reader = new FileReader();
                            reader.onloadend = () => resolve(reader.result.split(',')[1]);
                            reader.readAsDataURL(blob);
                        }});
                    }})()
                    """)
                    
                if audio_b64:
                    audio_data = f"data:audio/mp3;base64,{audio_b64}"

                    challenge = CaptchaChallenge(
                        type=CaptchaType.IMAGE_CAPTCHA,
                        extra={"audio_data": audio_data},
                    )
                    solution = await self._audio_solver.solve(challenge)
                    if solution.success:
                        logger.info(f"whisper transcribed: '{solution.token}'")
                        return solution.token

            logger.warning("audio via direct/browser fetch failed, trying download link")
            download_link = frame.locator(RecaptchaSelectors.DOWNLOAD_LINK).first
            href = await download_link.get_attribute("href", timeout=5000)
            if href:
                logger.info(f"fetching audio download link via stealth client")
                audio_b64 = await fetch_audio_base64_stealth(href, referer=self.page.url)
                if not audio_b64:
                    audio_b64 = await self.page.evaluate(f"""
                    (async () => {{
                        const resp = await fetch('{href}');
                        const blob = await resp.blob();
                        return new Promise((resolve) => {{
                            const reader = new FileReader();
                            reader.onloadend = () => resolve(reader.result.split(',')[1]);
                            reader.readAsDataURL(blob);
                        }});
                    }})()
                    """)
                    
                if audio_b64:
                    audio_data = f"data:audio/mp3;base64,{audio_b64}"

                challenge = CaptchaChallenge(
                    type=CaptchaType.IMAGE_CAPTCHA,
                    extra={"audio_data": audio_data},
                )
                solution = await self._audio_solver.solve(challenge)
                if solution.success:
                    logger.info(f"whisper transcribed: '{solution.token}'")
                    return solution.token

        except Exception as e:
            logger.error(f"audio download/transcribe failed: {e}")
        return None

    @async_retry(max_retries=2, exceptions=(PlaywrightError, PlaywrightTimeoutError))
    async def _type_audio_answer(self, frame: Frame, answer: str) -> None:
        input_field = frame.locator(RecaptchaSelectors.AUDIO_RESPONSE_INPUT).first
        await input_field.fill(answer, timeout=5000)
        logger.info(f"typed audio answer: {answer}")

    @async_retry(max_retries=2, exceptions=(PlaywrightError, PlaywrightTimeoutError))
    async def _click_verify(self, frame: Frame) -> None:
        verify_btn = frame.locator(RecaptchaSelectors.VERIFY_BUTTON).first
        await verify_btn.click(timeout=5000)
        logger.info("clicked verify")
        await asyncio.sleep(2.0)

    @async_retry(max_retries=2, exceptions=(PlaywrightError, PlaywrightTimeoutError))
    async def _solve_image_challenge(self, frame: Frame, page: Page) -> None:
        try:
            challenge_title = await frame.locator(RecaptchaSelectors.CHALLENGE_TITLE).first.text_content(timeout=5000)
            prompt = challenge_title.strip() if challenge_title else ""
            logger.info(f"image challenge prompt: {prompt}")
        except Exception:
            prompt = ""

        tiles = frame.locator(RecaptchaSelectors.TILES)
        tile_count = await tiles.count()
        
        if tile_count == 0:
            logger.warning("No image tiles found to solve.")
            return

        # Extract all tiles as base64 images
        images_b64 = []
        for i in range(tile_count):
            tile = tiles.nth(i)
            # Take screenshot of the individual tile
            img_bytes = await tile.screenshot()
            b64 = base64.b64encode(img_bytes).decode('utf-8')
            images_b64.append(b64)

        # Call the ImageClassifierSolver
        challenge = CaptchaChallenge(
            type=CaptchaType.IMAGE_CAPTCHA,
            extra={"image_data": images_b64, "prompt": prompt}
        )
        solution = await self._image_solver.solve(challenge)

        if not solution.success or not solution.extra.get("selected_tiles"):
            logger.warning("Image classifier failed to select any tiles, falling back to random selection.")
            selected_indices = random.sample(range(tile_count), min(3, tile_count))
        else:
            selected_indices = solution.extra["selected_tiles"]
            logger.info(f"CLIP model selected tiles: {selected_indices}")

        # Click the selected tiles
        for idx in selected_indices:
            if idx < tile_count:
                tile = tiles.nth(idx)
                await human_click(page, tile)
                await asyncio.sleep(random.uniform(0.3, 0.8))

        verify_btn = frame.locator(RecaptchaSelectors.VERIFY_BUTTON)
        await human_click(page, verify_btn)

    async def _extract_recaptcha_response(self, page: Page) -> Optional[str]:
        try:
            token = await page.evaluate("""
            (() => {
                const elements = document.querySelectorAll('textarea[name="g-recaptcha-response"], input[name="g-recaptcha-response"]');
                if (elements.length > 0) return elements[0].value;
                if (typeof grecaptcha !== 'undefined' && grecaptcha.getResponse) {
                    return grecaptcha.getResponse();
                }
                return null;
            })()
            """)
            if token and len(token) > 10:
                return str(token)
        except Exception:
            pass
        return None

    async def _extract_hcaptcha_response(self, page: Page) -> Optional[str]:
        try:
            token = await page.evaluate("""
            (() => {
                const el = document.querySelector('textarea[name="h-captcha-response"], input[name="h-captcha-response"]');
                if (el) return el.value;
                if (typeof hcaptcha !== 'undefined' && hcaptcha.getResponse) {
                    return hcaptcha.getResponse();
                }
                return null;
            })()
            """)
            if token and len(token) > 10:
                return str(token)
        except Exception:
            pass
        return None

    async def _extract_turnstile_response(self, page: Page) -> Optional[str]:
        try:
            token = await page.evaluate("""
            (() => {
                const el = document.querySelector('input[name="cf-turnstile-response"]');
                if (el) return el.value;
                if (typeof turnstile !== 'undefined' && turnstile.getResponse) {
                    return turnstile.getResponse();
                }
                return null;
            })()
            """)
            if token and len(token) > 10:
                return str(token)
        except Exception:
            pass
        return None

    async def _extract_v3_token(self, challenge: CaptchaChallenge) -> Optional[str]:
        try:
            token = await self.page.evaluate(f"""
            (async () => {{
                if (typeof grecaptcha === 'undefined') return null;
                return new Promise((resolve) => {{
                    grecaptcha.ready(() => {{
                        grecaptcha.execute('{challenge.sitekey}', {{action: '{challenge.action or "homepage"}'}}).then(resolve);
                    }});
                }});
            }})()
            """)
            if token and isinstance(token, str) and len(token) > 10:
                await asyncio.sleep(1.0)
                return str(token)
        except Exception as e:
            logger.warning(f"v3 token extraction failed: {e}")
        return None
