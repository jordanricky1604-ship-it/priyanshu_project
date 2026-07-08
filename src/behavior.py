from __future__ import annotations

import random
import asyncio
import math
from typing import Optional

from playwright.async_api import Page, Locator

from src.config import FingerprintConfig


def _human_delay(
    min_ms: int = 50, max_ms: int = 300, add_gaussian: bool = True
) -> float:
    base = random.randint(min_ms, max_ms)
    if add_gaussian:
        base += abs(random.gauss(0, 50))
    return base / 1000.0


def _bezier_curve(
    start: tuple[float, float],
    end: tuple[float, float],
    steps: int = 30,
) -> list[tuple[float, float]]:
    cp1 = (
        start[0] + random.uniform(-100, 100),
        start[1] + random.uniform(-100, 100),
    )
    cp2 = (
        end[0] + random.uniform(-100, 100),
        end[1] + random.uniform(-100, 100),
    )
    points = []
    for i in range(steps + 1):
        t = i / steps
        x = (1 - t) ** 3 * start[0] + 3 * (1 - t) ** 2 * t * cp1[0] + 3 * (1 - t) * t ** 2 * cp2[0] + t ** 3 * end[0]
        y = (1 - t) ** 3 * start[1] + 3 * (1 - t) ** 2 * t * cp1[1] + 3 * (1 - t) * t ** 2 * cp2[1] + t ** 3 * end[1]
        points.append((x, y))
    return points


async def human_mouse_move(
    page: Page, target_x: float, target_y: float, steps: int = 30
) -> None:
    start_x = random.randint(100, 800)
    start_y = random.randint(100, 600)
    curve = _bezier_curve((start_x, start_y), (target_x, target_y), steps)
    for x, y in curve:
        await page.mouse.move(x, y)
        await asyncio.sleep(random.uniform(0.002, 0.015))


async def human_drag(
    page: Page, start_x: float, start_y: float, end_x: float, end_y: float, steps: int = 40
) -> None:
    # 1. Move to start
    await human_mouse_move(page, start_x, start_y, steps=20)
    await asyncio.sleep(random.uniform(0.1, 0.3))
    
    # 2. Mouse down
    await page.mouse.down()
    await asyncio.sleep(random.uniform(0.05, 0.15))
    
    # 3. Add an overshoot to end_x to simulate human error and correction
    overshoot_x = end_x + random.uniform(5, 20)
    curve_to_overshoot = _bezier_curve((start_x, start_y), (overshoot_x, end_y + random.uniform(-2, 2)), steps)
    
    for idx, (x, y) in enumerate(curve_to_overshoot):
        await page.mouse.move(x, y)
        # Easing: move faster in the middle, slower at the edges
        progress = idx / steps
        if progress < 0.2 or progress > 0.8:
            await asyncio.sleep(random.uniform(0.015, 0.03))
        else:
            await asyncio.sleep(random.uniform(0.002, 0.01))
            
    await asyncio.sleep(random.uniform(0.05, 0.2))
    
    # 4. Correct back to end_x
    curve_to_end = _bezier_curve((overshoot_x, end_y), (end_x, end_y), 10)
    for x, y in curve_to_end:
        await page.mouse.move(x, y)
        await asyncio.sleep(random.uniform(0.01, 0.03))
        
    # 5. Mouse up
    await asyncio.sleep(random.uniform(0.1, 0.3))
    await page.mouse.up()


async def human_click(
    page: Page, selector: str | Locator, delay_before_ms: int = 300
) -> None:
    await asyncio.sleep(_human_delay(delay_before_ms, delay_before_ms + 500))
    if isinstance(selector, str):
        locator = page.locator(selector).first
    else:
        locator = selector
    box = await locator.bounding_box()
    if box:
        target_x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
        target_y = box["y"] + box["height"] * random.uniform(0.3, 0.7)
        await human_mouse_move(page, target_x, target_y)
        await asyncio.sleep(random.uniform(0.05, 0.2))
        await page.mouse.down()
        await asyncio.sleep(random.uniform(0.05, 0.15)) # Human click delay
        await page.mouse.up()
    else:
        await locator.click(delay=random.randint(100, 300))


async def human_type(
    page: Page, selector: str | Locator, text: str
) -> None:
    if isinstance(selector, str):
        locator = page.locator(selector).first
    else:
        locator = selector
    await locator.click(delay=random.randint(100, 300))
    for char in text:
        await page.keyboard.type(char, delay=random.randint(30, 120))
        if random.random() < 0.1:
            await asyncio.sleep(random.uniform(0.05, 0.2))


async def random_scroll(page: Page, count: int = 3) -> None:
    for _ in range(count):
        scroll_y = random.randint(100, 500)
        # Scroll in small human-like increments
        steps = random.randint(3, 8)
        step_amount = scroll_y / steps
        for _ in range(steps):
            await page.mouse.wheel(0, step_amount)
            await asyncio.sleep(random.uniform(0.02, 0.08))
        await asyncio.sleep(random.uniform(0.3, 1.0))


async def human_prebrowse(page: Page) -> None:
    await random_scroll(page, random.randint(1, 4))
    await asyncio.sleep(random.uniform(0.5, 2.0))
    body = page.locator("body")
    if await body.count():
        await body.hover()
        await asyncio.sleep(random.uniform(0.2, 0.8))


async def simulate_human_session(page: Page, duration_ms: int = 3000) -> None:
    elapsed = 0
    while elapsed < duration_ms:
        action = random.choice(["scroll", "hover", "wait"])
        if action == "scroll":
            scroll_y = random.randint(-200, 500)
            await page.evaluate(f"window.scrollBy(0, {scroll_y})")
            delay = random.randint(200, 800)
        elif action == "hover":
            x = random.randint(100, page.viewport_size["width"] - 100 if page.viewport_size else 1800)
            y = random.randint(100, page.viewport_size["height"] - 100 if page.viewport_size else 900)
            await page.mouse.move(x, y)
            delay = random.randint(300, 1200)
        else:
            delay = random.randint(500, 1500)
        await asyncio.sleep(delay / 1000.0)
        elapsed += delay
