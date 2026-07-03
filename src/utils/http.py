import base64
import logging
from typing import Optional
from curl_cffi.requests import AsyncSession

logger = logging.getLogger("captcha_solver")


async def fetch_audio_base64_stealth(url: str, referer: Optional[str] = None) -> Optional[str]:
    """
    Downloads an audio file (or any generic asset) using curl_cffi with a Chrome 120 impersonation.
    Returns the file content as a base64 string.
    """
    headers = {}
    if referer:
        headers["Referer"] = referer

    try:
        async with AsyncSession(impersonate="chrome120") as session:
            response = await session.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                b64_content = base64.b64encode(response.content).decode("utf-8")
                return b64_content
            else:
                logger.warning(f"curl_cffi fetch got status {response.status_code} for {url}")
                return None
    except Exception as e:
        logger.warning(f"curl_cffi fetch failed for {url}: {e}")
        return None
