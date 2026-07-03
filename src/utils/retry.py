import asyncio
import logging
from functools import wraps
from typing import Callable, Any, Type

from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger("captcha_solver")


def async_retry(
    max_retries: int = 3,
    delay_ms: int = 1000,
    backoff: float = 1.5,
    exceptions: tuple[Type[Exception], ...] = (Exception,)
) -> Callable:
    """
    Retry an async function with exponential backoff.
    By default catches all Exceptions, but can be restricted to specific ones
    like PlaywrightTimeoutError.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempt = 0
            current_delay = delay_ms / 1000.0
            
            while attempt < max_retries:
                attempt += 1
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_retries:
                        logger.error(f"Function {func.__name__} failed after {max_retries} attempts: {e}")
                        raise
                    
                    logger.warning(
                        f"Function {func.__name__} failed (attempt {attempt}/{max_retries}): {e}. "
                        f"Retrying in {current_delay:.1f}s..."
                    )
                    await asyncio.sleep(current_delay)
                    current_delay *= backoff
                    
        return wrapper
    return decorator
