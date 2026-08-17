"""Per-IP sliding-window rate limiting.

In-memory (single process is enough for the laptop/tunnel deploy; a multi-
instance cloud deploy would swap this for Redis). Disabled unless
RATE_LIMIT_ENABLED=true, so local dev, CI and tests are unaffected.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from app.config import settings

_hits: dict[str, deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def client_ip(request: Request) -> str:
    return (
        request.headers.get("cf-connecting-ip")
        or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )


def rate_limit(bucket: str, limit: int | None = None, window_s: int | None = None):
    """FastAPI dependency: allow `limit` requests per `window_s` per client IP.

    If *limit* or *window_s* is ``None`` the value is read from application
    settings at request time so that monkeypatching in tests takes effect.
    """

    def dependency(request: Request) -> None:
        effective_limit = limit if limit is not None else settings.rate_limit_requests_per_window
        effective_window = window_s if window_s is not None else settings.rate_limit_window_seconds
        enforce_rate_limit(bucket, client_ip(request), effective_limit, effective_window)

    return dependency


def enforce_rate_limit(
    bucket: str,
    subject: str,
    limit: int,
    window_s: int,
) -> None:
    """Apply a sliding-window limit to an explicit authenticated subject."""
    if not settings.rate_limit_enabled:
        return
    key = f"{bucket}:{subject}"
    now = time.time()
    with _lock:
        dq = _hits[key]
        cutoff = now - window_s
        while dq and dq[0] <= cutoff:
            dq.popleft()
        if len(dq) >= limit:
            retry = int(window_s - (now - dq[0])) + 1
            raise HTTPException(
                429,
                "rate limit exceeded, slow down",
                headers={"Retry-After": str(retry)},
            )
        dq.append(now)
