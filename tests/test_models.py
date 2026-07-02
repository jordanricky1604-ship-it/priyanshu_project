from __future__ import annotations

from src.models import CaptchaType


def test_captcha_types():
    assert CaptchaType.RECAPTCHA_V2.name == "RECAPTCHA_V2"
    assert CaptchaType.HCAPTCHA.name == "HCAPTCHA"
    assert CaptchaType.TURNSTILE.name == "TURNSTILE"
    assert CaptchaType.IMAGE_CAPTCHA.name == "IMAGE_CAPTCHA"
    assert CaptchaType.UNKNOWN.name == "UNKNOWN"
