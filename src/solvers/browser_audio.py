from __future__ import annotations

import logging
import time

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from src.models import CaptchaChallenge, CaptchaSolution, CaptchaType
from src.solvers.base import BaseSolver
from src.utils.model_manager import ModelManager

logger = logging.getLogger("captcha_solver")


class BrowserAudioSolver(BaseSolver):
    name = "browser_audio"

    def __init__(self, model_manager: ModelManager | None = None):
        self.model_manager = model_manager or ModelManager()

    def can_solve(self, challenge: CaptchaChallenge) -> bool:
        return challenge.type in (CaptchaType.UNKNOWN, CaptchaType.AUDIO_CAPTCHA)

    async def solve(self, challenge: CaptchaChallenge) -> CaptchaSolution:
        start = time.time()
        page: Page | None = challenge.extra.get("page")
        if not page:
            return CaptchaSolution(
                type=CaptchaType.AUDIO_CAPTCHA,
                success=False,
                error="No browser page provided in challenge.extra",
            )

        try:
            # 1. Locate the audio file link or tag
            # We look for <audio> elements, or links ending in .wav / .mp3, or with audio-related classes
            audio_selectors = [
                "audio source[src]",
                "audio[src]",
                "a[href$='.wav' i]",
                "a[href$='.mp3' i]",
                "a[class*='sound' i]",
                "a[class*='audio' i]",
            ]
            
            audio_url = None
            for selector in audio_selectors:
                loc = page.locator(selector).first
                if await loc.count() > 0:
                    if selector.startswith("audio"):
                        audio_url = await loc.get_attribute("src")
                    else:
                        audio_url = await loc.get_attribute("href")
                    if audio_url:
                        break
                        
            if not audio_url:
                return CaptchaSolution(
                    type=CaptchaType.AUDIO_CAPTCHA,
                    success=False,
                    error="Could not find a generic audio CAPTCHA link or <audio> tag",
                    elapsed_ms=(time.time() - start) * 1000,
                )

            # Ensure URL is absolute
            if not audio_url.startswith("http"):
                base_url = await page.evaluate("window.location.origin")
                if audio_url.startswith("/"):
                    audio_url = base_url + audio_url
                else:
                    path = await page.evaluate("window.location.pathname")
                    audio_url = base_url + path.rsplit("/", 1)[0] + "/" + audio_url

            # Try to click it so the user can hear it playing in the UI
            try:
                # Find the element again by URL
                audio_el = page.locator(f"a[href$='{audio_url.split('/')[-1]}']").first
                if await audio_el.count() > 0 and await audio_el.is_visible():
                    await audio_el.click(force=True)
            except Exception as e:
                pass

            logger.info(f"Downloading audio CAPTCHA from: {audio_url}")
            
            # 2. Download the audio bytes using the page context (inherits cookies/session)
            # Use fetch API via evaluate to get array buffer
            audio_bytes = await page.evaluate("""
                async (url) => {
                    const response = await fetch(url);
                    const buffer = await response.arrayBuffer();
                    return Array.from(new Uint8Array(buffer));
                }
            """, audio_url)
            
            audio_bytes = bytes(audio_bytes)

            # 3. Transcribe audio with Whisper
            logger.info("Transcribing audio CAPTCHA with Whisper...")
            whisper_model = self.model_manager.get_whisper()
            
            import tempfile
            import os
            
            # Whisper requires a file path or file-like object usually, but since the model 
            # might have a transcribe_bytes helper or we can write to temp
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                tf.write(audio_bytes)
                temp_path = tf.name
                
            try:
                # Transcribe
                segments, info = whisper_model.transcribe(temp_path, beam_size=5, language="en")
                text = "".join(segment.text for segment in segments).strip()
            finally:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)

            if not text:
                return CaptchaSolution(
                    type=CaptchaType.AUDIO_CAPTCHA,
                    success=False,
                    error="Whisper failed to transcribe any text",
                    elapsed_ms=(time.time() - start) * 1000,
                )
            
            logger.info(f"Transcription successful: '{text}'")

            # 4. Locate the corresponding text input field
            input_selectors = [
                'input[id="CaptchaCode" i]',
                'input[type="text"][name*="captcha" i]',
                'input[type="text"][id*="captcha" i]',
                'input[name*="captcha" i]',
                'input[id*="captcha" i]',
                'input[type="text"]' # Fallback
            ]
            
            input_locator = None
            for selector in input_selectors:
                loc = page.locator(selector).first
                if await loc.count() > 0 and await loc.is_visible():
                    input_locator = loc
                    break
                    
            if not input_locator:
                logger.warning("Could not find a text input field to type the CAPTCHA solution into. Returning token anyway.")
            else:
                # 5. Type the transcription
                logger.info("Typing solution into generic audio CAPTCHA input...")
                await input_locator.fill(text)
            
            return CaptchaSolution(
                type=CaptchaType.AUDIO_CAPTCHA,
                success=True,
                token=text,
                elapsed_ms=(time.time() - start) * 1000,
            )
            
        except Exception as e:
            logger.error(f"BrowserAudioSolver error: {e}")
            return CaptchaSolution(
                type=CaptchaType.AUDIO_CAPTCHA,
                success=False,
                error=str(e),
                elapsed_ms=(time.time() - start) * 1000,
            )


from src.solvers.base import SolverRegistry
SolverRegistry.register(BrowserAudioSolver())
