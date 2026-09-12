"""Resilience and exponential backoff utility for email connectors.

Powered by the battle-tested 'tenacity' library, providing production-grade
exponential backoff, full jitter, and exception filtering to handle transient
network disconnects, rate limits, socket timeouts, and provider throttling.
"""

import logging
from typing import Tuple, Type
from tenacity import (
    retry,
    stop_after_attempt,
    wait_random_exponential,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

logger = logging.getLogger(__name__)


def retry_with_backoff(
    retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,)
):
    """Decorator applying exponential backoff with full jitter powered by tenacity."""
    if jitter:
        wait_strategy = wait_random_exponential(
            multiplier=base_delay,
            max=max_delay,
            exp_base=exponential_base
        )
    else:
        wait_strategy = wait_exponential(
            multiplier=base_delay,
            max=max_delay,
            exp_base=exponential_base
        )

    return retry(
        reraise=True,
        stop=stop_after_attempt(retries + 1),
        wait=wait_strategy,
        retry=retry_if_exception_type(retryable_exceptions),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
