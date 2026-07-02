from __future__ import annotations

import random
from typing import Optional

from playwright.async_api import BrowserContext


class FingerprintManager:
    def __init__(self, randomized: bool = True):
        self.randomized = randomized
        self._fingerprint: dict = {}
        if randomized:
            self.randomize()

    def randomize(self) -> dict:
        vendors = ["Intel Inc.", "Google Inc.", "NVIDIA Corporation", "AMD"]
        renderers = [
            "Intel Iris OpenGL Engine",
            "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060)",
            "ANGLE (AMD, AMD Radeon RX 6800M)",
            "Mesa DRI Intel(R) UHD Graphics 620",
        ]
        platforms = ["Win32", "MacIntel", "Linux x86_64"]
        timezones = [
            "America/New_York",
            "America/Chicago",
            "America/Los_Angeles",
            "Europe/London",
            "Europe/Berlin",
            "Asia/Tokyo",
        ]
        languages = [
            ("en-US", "en"),
            ("en-GB", "en"),
            ("de-DE", "de", "en"),
            ("fr-FR", "fr", "en"),
        ]
        resolutions = [
            (1920, 1080),
            (2560, 1440),
            (1366, 768),
            (1440, 900),
        ]

        self._fingerprint = {
            "webgl_vendor": random.choice(vendors),
            "webgl_renderer": random.choice(renderers),
            "platform": random.choice(platforms),
            "timezone": random.choice(timezones),
            "languages": list(random.choice(languages)),
            "resolution": random.choice(resolutions),
            "device_pixel_ratio": random.choice([1.0, 1.25, 1.5, 2.0]),
        }
        return self._fingerprint

    async def apply(self, context: BrowserContext) -> None:
        if not self.randomized:
            return
        fp = self._fingerprint

        await context.add_init_script(f"""
        Object.defineProperty(navigator, 'platform', {{
            get: () => '{fp["platform"]}',
        }});
        Object.defineProperty(navigator, 'languages', {{
            get: () => {fp["languages"]},
        }});
        Object.defineProperty(navigator, 'deviceMemory', {{
            get: () => {random.choice([4, 8, 16])},
        }});
        Object.defineProperty(navigator, 'hardwareConcurrency', {{
            get: () => {random.choice([4, 8, 12, 16])},
        }});
        """)
