from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from playwright_stealth import stealth

from src.config import BrowserProfile, SolverConfig

logger = logging.getLogger("captcha_solver")


_BROWSER_CACHE: tuple[Browser, asyncio.Task | None] = (None, None)


async def _launch_browser(config: SolverConfig) -> Browser:
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=config.browser_headless,
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-features=OptimizationGuideModelDownloading,OptimizationHintsFetching,OptimizationTargetPrediction,IsolateOrigins,site-per-process",
            "--disable-dev-shm-usage",
            "--disable-infobars",
            "--disable-setuid-sandbox",
            "--disable-web-security",
            f"--window-size=1920,1080",
        ],
    )
    return browser


async def get_browser(config: SolverConfig) -> Browser:
    global _BROWSER_CACHE
    if _BROWSER_CACHE[0] is None or not _BROWSER_CACHE[0].is_connected():
        _BROWSER_CACHE = (await _launch_browser(config), None)
    return _BROWSER_CACHE[0]


async def close_browser() -> None:
    global _BROWSER_CACHE
    if _BROWSER_CACHE[0]:
        await _BROWSER_CACHE[0].close()
        _BROWSER_CACHE = (None, None)


@asynccontextmanager
async def create_context(
    browser: Browser,
    profile: Optional[BrowserProfile] = None,
    proxy: Optional[dict] = None,
) -> AsyncIterator[BrowserContext]:
    context_kwargs: dict = {
        "viewport": {"width": 1920, "height": 1080},
        "locale": "en-US",
        "timezone_id": "America/New_York",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "ignore_https_errors": True,
    }

    if profile and profile.user_data_dir:
        user_dir = Path(profile.user_data_dir)
        user_dir.mkdir(parents=True, exist_ok=True)
        state_file = user_dir / "state.json"
        if state_file.exists():
            context_kwargs["storage_state"] = str(state_file)

    if proxy:
        context_kwargs["proxy"] = proxy

    context = await browser.new_context(**context_kwargs)
    await _apply_stealth(context)
    try:
        yield context
    finally:
        await context.close()


async def _apply_stealth(context: BrowserContext) -> None:
    # In playwright-stealth, the Stealth class allows injecting scripts into a context
    stealth_config = stealth.Stealth()
    await stealth_config.apply_stealth_async(context)
