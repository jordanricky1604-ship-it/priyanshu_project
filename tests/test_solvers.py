from __future__ import annotations

import pytest

from src.models import CaptchaType, CaptchaChallenge, CaptchaSolution
from src.solvers.base import SolverRegistry, BaseSolver
from src.solvers.ocr import OCRSolver
from src.solvers.audio import AudioSolver
from src.solvers.image_classifier import ImageClassifierSolver
from src.solvers.browser_token import BrowserTokenSolver
from src.solvers.funcaptcha import FunCaptchaSolver
from src.solvers.geetest import GeeTestSolver

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
    assert solver is None # Assuming GEETEST_V4 is not fully registered/handled by name in the dummy match if it fails earlier

class MockConfig:
    audio_model_size = "tiny.en"
    audio_compute_type = "int8"
    clip_model_name = "ViT-B-32"
    clip_pretrained = "openai"

def test_browser_token_can_solve():
    solver = BrowserTokenSolver(config=MockConfig(), page=None)
    assert solver.can_solve(CaptchaChallenge(type=CaptchaType.RECAPTCHA_V2))
    assert solver.can_solve(CaptchaChallenge(type=CaptchaType.HCAPTCHA))
    assert solver.can_solve(CaptchaChallenge(type=CaptchaType.TURNSTILE))
    assert not solver.can_solve(CaptchaChallenge(type=CaptchaType.IMAGE_CAPTCHA))

def test_funcaptcha_can_solve():
    solver = FunCaptchaSolver()
    assert solver.can_solve(CaptchaChallenge(type=CaptchaType.FUNCAPTCHA))
    assert not solver.can_solve(CaptchaChallenge(type=CaptchaType.RECAPTCHA_V2))

def test_geetest_can_solve():
    solver = GeeTestSolver()
    assert solver.can_solve(CaptchaChallenge(type=CaptchaType.GEETEST_V3))
    assert solver.can_solve(CaptchaChallenge(type=CaptchaType.GEETEST_V4))
    assert not solver.can_solve(CaptchaChallenge(type=CaptchaType.HCAPTCHA))
