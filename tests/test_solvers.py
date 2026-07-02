from __future__ import annotations

import pytest

from src.models import CaptchaType, CaptchaChallenge, CaptchaSolution
from src.solvers.base import SolverRegistry, BaseSolver
from src.solvers.ocr import OCRSolver
from src.solvers.audio import AudioSolver
from src.solvers.image_classifier import ImageClassifierSolver


def test_captcha_challenge_defaults():
    c = CaptchaChallenge()
    assert c.type == CaptchaType.UNKNOWN
    assert c.page_url == ""
    assert c.sitekey == ""


def test_captcha_solution():
    s = CaptchaSolution(type=CaptchaType.IMAGE_CAPTCHA, token="abc123", success=True)
    assert s.token == "abc123"
    assert s.success


def test_solver_registry():
    solvers = SolverRegistry.get_solvers()
    assert len(solvers) >= 3
    names = {s.name for s in solvers}
    assert "ocr" in names
    assert "audio" in names
    assert "image_classifier" in names


def test_ocr_can_solve():
    solver = OCRSolver()
    image_challenge = CaptchaChallenge(type=CaptchaType.IMAGE_CAPTCHA)
    assert solver.can_solve(image_challenge)
    recaptcha_challenge = CaptchaChallenge(type=CaptchaType.RECAPTCHA_V2)
    assert not solver.can_solve(recaptcha_challenge)


def test_audio_can_solve():
    solver = AudioSolver()
    assert solver.can_solve(CaptchaChallenge(type=CaptchaType.IMAGE_CAPTCHA, extra={"audio_data": "dummy"}))
    assert not solver.can_solve(CaptchaChallenge(type=CaptchaType.RECAPTCHA_V2))
    assert not solver.can_solve(CaptchaChallenge(type=CaptchaType.IMAGE_CAPTCHA))


def test_image_classifier_can_solve():
    solver = ImageClassifierSolver()
    assert solver.can_solve(CaptchaChallenge(type=CaptchaType.IMAGE_CAPTCHA, extra={"image_data": "dummy"}))
    assert not solver.can_solve(CaptchaChallenge(type=CaptchaType.RECAPTCHA_V2))


def test_registry_find():
    ocr_challenge = CaptchaChallenge(type=CaptchaType.IMAGE_CAPTCHA)
    solver = SolverRegistry.find(ocr_challenge)
    assert solver is not None
    assert solver.name == "ocr"

    no_match = CaptchaChallenge(type=CaptchaType.GEETEST_V4)
    solver = SolverRegistry.find(no_match)
    assert solver is None
