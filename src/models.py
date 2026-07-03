from __future__ import annotations

from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional


class CaptchaType(Enum):
    UNKNOWN = auto()
    IMAGE_CAPTCHA = auto()
    RECAPTCHA_V2 = auto()
    RECAPTCHA_V2_INVISIBLE = auto()
    RECAPTCHA_V3 = auto()
    RECAPTCHA_ENTERPRISE = auto()
    HCAPTCHA = auto()
    HCAPTCHA_INVISIBLE = auto()
    TURNSTILE = auto()
    TURNSTILE_INVISIBLE = auto()
    FUNCAPTCHA = auto()
    GEETEST_V3 = auto()
    GEETEST_V4 = auto()
    AWS_WAF = auto()
    MT_CAPTCHA = auto()
    DATADOME = auto()


@dataclass
class CaptchaChallenge:
    type: CaptchaType = CaptchaType.UNKNOWN
    page_url: str = ""
    sitekey: str = ""
    api_domain: str = ""
    data_s: str = ""
    action: str = ""
    is_invisible: bool = False
    enterprise_payload: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)


@dataclass
class CaptchaSolution:
    type: CaptchaType
    token: str = ""
    user_agent: str = ""
    cookies: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)
    solved_via: str = ""
    attempts: int = 0
    elapsed_ms: float = 0.0
    success: bool = False
    error: str = ""

class RateLimitException(Exception):
    pass
