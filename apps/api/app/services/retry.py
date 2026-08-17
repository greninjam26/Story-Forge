"""Shared transient-error retry with exponential backoff."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

from app.config import settings

_T = TypeVar("_T")

logger = logging.getLogger(__name__)


def retry_transient(
    func: Callable[[int], _T],
    is_transient: Callable[[Exception], bool],
    *,
    max_attempts: int | None = None,
    base_delay: float | None = None,
    max_delay: float | None = None,
) -> _T:
    """Call *func* up to *max_attempts* times, sleeping between transient failures.

    *func* receives the 1-indexed attempt number.  When it raises an
    exception for which *is_transient* returns ``True`` the utility sleeps
    with exponential backoff (``base_delay * 2**(attempt-1)`` capped at
    *max_delay*) and retries.  Non-transient exceptions propagate immediately.

    Returns the first successful result.  After exhausting all attempts the
    last exception propagates.
    """
    _max = (
        max_attempts
        if max_attempts is not None
        else settings.provider_retry_attempts
    )
    _base = (
        base_delay
        if base_delay is not None
        else settings.provider_retry_base_delay_seconds
    )
    _cap = (
        max_delay
        if max_delay is not None
        else settings.provider_retry_max_delay_seconds
    )

    last_exc: Exception | None = None
    for attempt in range(1, _max + 1):
        try:
            return func(attempt)
        except Exception as exc:
            if not is_transient(exc) or attempt == _max:
                raise
            last_exc = exc
            delay = min(_base * (2 ** (attempt - 1)), _cap)
            logger.debug(
                "Transient provider error on attempt %d, retrying in %.1fs",
                attempt,
                delay,
            )
            time.sleep(delay)
    raise RuntimeError("retry_transient loop ended unexpectedly") from last_exc
