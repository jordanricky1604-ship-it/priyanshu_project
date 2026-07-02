from __future__ import annotations

import asyncio
import logging
import random
from typing import Optional

import httpx

from src.config import ProxyConfig

logger = logging.getLogger("captcha_solver")

_FREE_PROXY_SOURCES = [
    "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=http&proxy_format=protocolipport&format=text&timeout=20000",
    "https://www.proxy-list.download/api/v1/get?type=https",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
]


class ProxyManager:
    def __init__(self, config_proxy: Optional[ProxyConfig] = None):
        self.config_proxy = config_proxy
        self._proxy_pool: list[str] = []

    def get_proxy(self) -> Optional[dict]:
        if self.config_proxy and self.config_proxy.server:
            return self.config_proxy.as_playwright()
        if self._proxy_pool:
            url = random.choice(self._proxy_pool)
            return {"server": url}
        return None

    async def refresh_pool(self) -> int:
        added = 0
        for source in _FREE_PROXY_SOURCES:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(source)
                    lines = resp.text.strip().split("\n")
                    for line in lines:
                        line = line.strip()
                        if line and line not in self._proxy_pool:
                            if await self._validate(line):
                                self._proxy_pool.append(line)
                                added += 1
            except Exception as e:
                logger.debug(f"failed to fetch from {source}: {e}")
        logger.info(f"proxy pool refreshed: {added} new proxies (total: {len(self._proxy_pool)})")
        return added

    async def _validate(self, proxy_url: str) -> bool:
        try:
            async with httpx.AsyncClient(
                proxy=proxy_url,
                timeout=10.0,
            ) as client:
                resp = await client.get("https://httpbin.org/ip")
                return resp.status_code == 200
        except Exception:
            return False

    async def rotate(self) -> Optional[dict]:
        if self.config_proxy and self.config_proxy.server:
            return self.config_proxy.as_playwright()

        self._proxy_pool = [
            p for p in self._proxy_pool if await self._validate(p)
        ]

        if not self._proxy_pool:
            await self.refresh_pool()

        if self._proxy_pool:
            url = random.choice(self._proxy_pool)
            return {"server": url}
        return None
