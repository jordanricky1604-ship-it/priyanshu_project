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

logger = logging.getLogger("captcha_solver")

_WHISPER_MODEL = None


def _get_model_path() -> str:
    model_dir = os.path.join(os.path.dirname(__file__), "..", "..", "models")
    return os.path.abspath(model_dir)


def _get_whisper_model(model_size: str = "tiny.en", compute_type: str = "int8"):
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        try:
            from faster_whisper import WhisperModel

            logger.info(f"loading faster-whisper model '{model_size}'...")
            _WHISPER_MODEL = WhisperModel(
                model_size,
                device="cpu",
                compute_type=compute_type,
                download_root=_get_model_path(),
            )
            logger.info("faster-whisper ready")
        except ImportError:
            logger.error("faster-whisper not installed. Run: pip install faster-whisper")
            raise
    return _WHISPER_MODEL


class AudioSolver(BaseSolver):
    name = "audio"

    def __init__(
        self,
        model_size: str = "tiny.en",
        compute_type: str = "int8",
    ):
        self.model_size = model_size
        self.compute_type = compute_type

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

        model = _get_whisper_model(self.model_size, self.compute_type)
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
