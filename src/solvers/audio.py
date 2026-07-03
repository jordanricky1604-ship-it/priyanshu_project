from __future__ import annotations

import logging
import time
import io
import base64
import asyncio
import os

import numpy as np

from src.models import CaptchaChallenge, CaptchaSolution, CaptchaType
from src.solvers.base import BaseSolver, SolverRegistry
from src.utils.model_manager import ModelManager

logger = logging.getLogger("captcha_solver")


class AudioSolver(BaseSolver):
    name = "audio"

    def __init__(
        self,
        model_manager: ModelManager | None = None,
    ):
        self.model_manager = model_manager or ModelManager()

    def can_solve(self, challenge: CaptchaChallenge) -> bool:
        return challenge.type == CaptchaType.IMAGE_CAPTCHA and "audio_data" in challenge.extra

    async def solve(self, challenge: CaptchaChallenge) -> CaptchaSolution:
        start = time.time()
        try:
            audio_data = challenge.extra.get("audio_data", "")
            if not audio_data:
                return CaptchaSolution(
                    type=challenge.type,
                    success=False,
                    error="no audio_data in challenge.extra",
                )

            audio_bytes = _decode_audio(audio_data)
            text = self._transcribe(audio_bytes)

            elapsed = (time.time() - start) * 1000
            logger.info(f"audio transcribed: '{text}'")
            return CaptchaSolution(
                type=challenge.type,
                token=text.strip(),
                solved_via="audio",
                attempts=1,
                elapsed_ms=elapsed,
                success=bool(text.strip()),
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

    def _transcribe(self, audio_bytes: bytes) -> str:
        import tempfile
        import os

        model = self.model_manager.get_whisper()
        logger.info(f"transcribing {len(audio_bytes)} bytes of audio...")

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name

        try:
            segments, info = model.transcribe(tmp_path, beam_size=5, language="en")
            logger.info(f"whisper detected language: {info.language}, probability: {info.language_probability}")
            text = " ".join(segment.text for segment in segments)
            logger.info(f"whisper raw output: '{text}'")
            cleaned = _clean_transcription(text)
            logger.info(f"cleaned output: '{cleaned}'")
            return cleaned
        finally:
            os.unlink(tmp_path)


def _decode_audio(data: str) -> bytes:
    if data.startswith("data:"):
        data = data.split(",", 1)[1]
    return base64.b64decode(data)


def _clean_transcription(text: str) -> str:
    text = text.lower().strip()
    for prefix in ["the answer is ", "answer: ", "the word is ", "the words are "]:
        if text.startswith(prefix):
            text = text[len(prefix):]
    text = text.replace(" ", "").replace("-", "").replace(".", "").replace(",", "")
    text = "".join(c for c in text if c.isalpha() or c.isdigit())
    return text


SolverRegistry.register(AudioSolver())
