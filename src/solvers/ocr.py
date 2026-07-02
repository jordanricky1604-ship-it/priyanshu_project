from __future__ import annotations

import logging
import time

import easyocr

from src.models import CaptchaChallenge, CaptchaSolution, CaptchaType
from src.solvers.base import BaseSolver, SolverRegistry
from src.utils.image import decode_image, preprocess_for_ocr

logger = logging.getLogger("captcha_solver")


class OCRSolver(BaseSolver):
    name = "ocr"

    def __init__(self, languages: list[str] | None = None):
        self._reader = None
        self._languages = languages or ["en"]
        self._initialized = False

    def _init_reader(self) -> easyocr.Reader:
        if not self._reader:
            logger.info("loading EasyOCR (first use, may take a moment)...")
            self._reader = easyocr.Reader(self._languages, gpu=True)
            logger.info("EasyOCR ready")
        return self._reader

    def can_solve(self, challenge: CaptchaChallenge) -> bool:
        return challenge.type == CaptchaType.IMAGE_CAPTCHA

    async def solve(self, challenge: CaptchaChallenge) -> CaptchaSolution:
        start = time.time()
        attempts = 0
        try:
            reader = self._init_reader()
            img_data = challenge.extra.get("image_data", "")
            if not img_data:
                return CaptchaSolution(
                    type=CaptchaType.IMAGE_CAPTCHA,
                    success=False,
                    error="no image_data in challenge.extra",
                )

            img = decode_image(img_data)
            img = preprocess_for_ocr(img)

            results = reader.readtext(img, detail=1)
            text = "".join([r[1] for r in results if r[2] > 0.3])

            attempts = 1
            logger.info(f"ocr solved: '{text}'")
            elapsed = (time.time() - start) * 1000
            return CaptchaSolution(
                type=CaptchaType.IMAGE_CAPTCHA,
                token=text.strip(),
                solved_via="ocr",
                attempts=attempts,
                elapsed_ms=elapsed,
                success=bool(text.strip()),
            )
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            return CaptchaSolution(
                type=CaptchaType.IMAGE_CAPTCHA,
                success=False,
                error=str(e),
                attempts=attempts,
                elapsed_ms=elapsed,
            )


SolverRegistry.register(OCRSolver())
