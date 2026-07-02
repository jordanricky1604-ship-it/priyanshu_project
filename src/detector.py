from __future__ import annotations

import logging
import re
from typing import Optional

from playwright.async_api import Page

from src.models import CaptchaChallenge, CaptchaType

logger = logging.getLogger("captcha_solver")


CAPTCHA_SIGNATURES: dict[CaptchaType, dict] = {
    CaptchaType.RECAPTCHA_V2: {
        "globals": ["grecaptcha"],
        "selectors": ["div.g-recaptcha", "iframe[src*='recaptcha/api2/anchor']",
                       "iframe[title*='recaptcha']", "div[data-sitekey]"],
    },
    CaptchaType.HCAPTCHA: {
        "globals": ["hcaptcha"],
        "selectors": ["div.h-captcha", "iframe[src*='hcaptcha.com/captcha']",
                       "iframe[src*='newassets.hcaptcha.com']"],
    },
    CaptchaType.TURNSTILE: {
        "globals": ["turnstile"],
        "selectors": ["div.cf-turnstile", "iframe[src*='challenges.cloudflare.com']"],
    },
    CaptchaType.FUNCAPTCHA: {
        "globals": [],
        "selectors": ["iframe[src*='funcaptcha']", "iframe[src*='arkoselabs']"],
    },
    CaptchaType.GEETEST_V3: {
        "globals": [],
        "selectors": ["div.geetest_captcha", "iframe[src*='gee']",
                       "script[src*='gee']", "script[src*='gt.js']"],
    },
    CaptchaType.AWS_WAF: {
        "globals": [],
        "selectors": ["iframe[src*='aws']", "div[data-aws-captcha]",
                       "script[src*='aws']"],
    },
}

SITEKEY_PATTERNS = {
    CaptchaType.RECAPTCHA_V2: re.compile(r'(?:data-sitekey|sitekey)\s*[:=]\s*["\']([^"\']+)["\']'),
    CaptchaType.RECAPTCHA_V3: re.compile(r'(?:data-sitekey|sitekey)\s*[:=]\s*["\']([^"\']+)["\']'),
    CaptchaType.RECAPTCHA_ENTERPRISE: re.compile(r'(?:data-sitekey|sitekey)\s*[:=]\s*["\']([^"\']+)["\']'),
    CaptchaType.HCAPTCHA: re.compile(r'(?:data-sitekey|sitekey)\s*[:=]\s*["\']([^"\']+)["\']'),
    CaptchaType.TURNSTILE: re.compile(r'(?:data-sitekey|sitekey)\s*[:=]\s*["\']([^"\']+)["\']'),
}


async def detect_captcha(page: Page, page_url: str) -> CaptchaChallenge:
    challenge = CaptchaChallenge(page_url=page_url)

    js_result = await page.evaluate("""
    (() => {
        const types = [];
        if (typeof grecaptcha !== 'undefined') types.push('grecaptcha');
        if (typeof hcaptcha !== 'undefined') types.push('hcaptcha');
        if (typeof turnstile !== 'undefined') types.push('turnstile');
        const scripts = Array.from(document.querySelectorAll('script')).map(s => s.src).join('|');
        const pageSource = document.documentElement.outerHTML;
        return { types, scripts, pageSource };
    })()
    """)

    globals = js_result.get("types", [])
    scripts = js_result.get("scripts", "")
    page_source = js_result.get("pageSource", "")

    _classify_recaptcha(challenge, globals, page_source, scripts)
    if challenge.type != CaptchaType.UNKNOWN:
        return challenge

    _classify_hcaptcha(challenge, globals, page_source)
    if challenge.type != CaptchaType.UNKNOWN:
        return challenge

    _classify_turnstile(challenge, globals, page_source)
    if challenge.type != CaptchaType.UNKNOWN:
        return challenge

    _classify_other(challenge, page_source, scripts)
    if challenge.type != CaptchaType.UNKNOWN:
        return challenge

    img_captcha = await _detect_image_captcha(page)
    if img_captcha:
        challenge.type = CaptchaType.IMAGE_CAPTCHA
        return challenge

    return challenge


def _classify_recaptcha(
    challenge: CaptchaChallenge,
    globals: list[str],
    page_source: str,
    scripts: str,
) -> None:
    if "grecaptcha" not in globals:
        if "recaptcha/api.js" not in scripts and "recaptcha/enterprise.js" not in scripts:
            return

    is_enterprise = "recaptcha/enterprise.js" in scripts or "recaptcha.net" in page_source
    is_v3 = "recaptcha/api.js?render=" in page_source or "grecaptcha.execute" in page_source

    if is_enterprise:
        challenge.type = CaptchaType.RECAPTCHA_ENTERPRISE
    elif is_v3:
        challenge.type = CaptchaType.RECAPTCHA_V3
    elif "grecaptcha" in globals:
        challenge.type = CaptchaType.RECAPTCHA_V2

    match = SITEKEY_PATTERNS.get(CaptchaType.RECAPTCHA_V2, re.compile(r'')).search(page_source)
    if match:
        challenge.sitekey = match.group(1)

    s_match = re.search(r'(?:data-s|"s")\s*[:=]\s*["\']([^"\']+)["\']', page_source)
    if s_match:
        challenge.data_s = s_match.group(1)
        challenge.extra["s_value"] = s_match.group(1)

    action_match = re.search(r'(?:data-action|action)\s*[:=]\s*["\']([^"\']+)["\']', page_source)
    if action_match:
        challenge.action = action_match.group(1)

    challenge.is_invisible = bool(
        re.search(r'"invisible"|data-size="invisible"', page_source)
    )


def _classify_hcaptcha(
    challenge: CaptchaChallenge,
    globals: list[str],
    page_source: str,
) -> None:
    if "hcaptcha" not in globals and "hcaptcha.com" not in page_source:
        return

    challenge.type = CaptchaType.HCAPTCHA
    match = SITEKEY_PATTERNS.get(CaptchaType.HCAPTCHA, re.compile(r'')).search(page_source)
    if match:
        challenge.sitekey = match.group(1)

    challenge.is_invisible = bool(
        re.search(r'"invisible"|data-size="invisible"', page_source)
    )


def _classify_turnstile(
    challenge: CaptchaChallenge,
    globals: list[str],
    page_source: str,
) -> None:
    if "turnstile" not in globals and "challenges.cloudflare.com" not in page_source:
        return

    challenge.type = CaptchaType.TURNSTILE
    match = SITEKEY_PATTERNS.get(CaptchaType.TURNSTILE, re.compile(r'')).search(page_source)
    if match:
        challenge.sitekey = match.group(1)


def _classify_other(
    challenge: CaptchaChallenge,
    page_source: str,
    scripts: str,
) -> None:
    if "funcaptcha" in page_source or "arkoselabs" in scripts:
        challenge.type = CaptchaType.FUNCAPTCHA
        pk_match = re.search(r'public_key\s*[:=]\s*["\']([^"\']+)["\']', page_source)
        if pk_match:
            challenge.sitekey = pk_match.group(1)
        return

    if "geetest" in page_source.lower() or "gt.js" in scripts:
        challenge.type = CaptchaType.GEETEST_V3
        gt_match = re.search(r'(?:gt)\s*[:=]\s*["\']([^"\']+)["\']', page_source)
        if gt_match:
            challenge.sitekey = gt_match.group(1)
        return

    if "aws" in scripts.lower() and ("captcha" in page_source.lower() or "challenge" in page_source.lower()):
        challenge.type = CaptchaType.AWS_WAF
        return

    if "datadome" in scripts.lower() or "datadome" in page_source.lower():
        challenge.type = CaptchaType.DATADOME
        return

    if "mtcaptcha" in scripts.lower() or "mtcaptcha" in page_source.lower():
        challenge.type = CaptchaType.MT_CAPTCHA
        match = re.search(r'(?:data-sitekey|sitekey)\s*[:=]\s*["\']([^"\']+)["\']', page_source)
        if match:
            challenge.sitekey = match.group(1)
        return


async def _detect_image_captcha(page: Page) -> bool:
    try:
        img_count = await page.evaluate("""
        (() => {
            const imgs = document.querySelectorAll('img[src*="captcha"], img[class*="captcha"], img[id*="captcha"]');
            return imgs.length;
        })()
        """)
        return int(img_count) > 0
    except Exception:
        return False
