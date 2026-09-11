"""Resilience and exponential backoff utility for email connectors.

Provides configurable retry decorators with full jitter to handle transient
network disconnects, rate limits, socket timeouts, and provider throttling.
"""

import functools
import logging
import random
import time
from typing import Tuple, Type

logger = logging.getLogger(__name__)


def retry_with_backoff(
    retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,)
):
    """Decorator applying truncated exponential backoff with full jitter.
    
    Formula: t = min(max_delay, base_delay * (exponential_base ** attempt))
    Sleep = uniform(0, t) when jitter is True.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as err:
                    attempt += 1
                    if attempt > retries:
                        logger.error(f"[{func.__name__}] Failed after {retries} retries. Error: {err}")
                        raise
                    
                    delay = min(max_delay, base_delay * (exponential_base ** (attempt - 1)))
                    sleep_duration = random.uniform(0.1, delay) if jitter else delay
                    
                    logger.warning(
                        f"[{func.__name__}] Transient error: {err}. "
                        f"Retry {attempt}/{retries} in {sleep_duration:.2f}s..."
                    )
                    time.sleep(sleep_duration)
        return wrapper
    return decorator
