from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

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
            "--disable-dev-shm-usage",
            "--disable-infobars",
            "--disable-setuid-sandbox",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
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
    await context.add_init_script("""
    delete Object.getPrototypeOf(navigator).webdriver;
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5],
    });
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-US', 'en'],
    });
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
            Promise.resolve({state: Notification.permission}) :
            originalQuery(parameters)
    );
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
    });
    """)

    await context.add_init_script("""
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) {
            return 'Intel Inc.';
        }
        if (parameter === 37446) {
            return 'Intel Iris OpenGL Engine';
        }
        return getParameter.call(this, parameter);
    };
    """)

    await context.add_init_script("""
    HTMLCanvasElement.prototype.toDataURL = (function(original) {
        return function() {
            const context = this.getContext('2d', {willReadFrequently: true});
            if (context) {
                const imageData = context.getImageData(0, 0, this.width, this.height);
                const data = imageData.data;
                for (let i = 0; i < data.length; i += 4) {
                    if (i % 40 === 0) {
                        data[i + 2] = (data[i + 2] + 1) % 256;
                    }
                }
                context.putImageData(imageData, 0, 0);
            }
            return original.apply(this, arguments);
        };
    })(HTMLCanvasElement.prototype.toDataURL);
    """)
