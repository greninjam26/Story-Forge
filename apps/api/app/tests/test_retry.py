from __future__ import annotations

import pytest

from app.services.retry import retry_transient


class TransientError(RuntimeError):
    pass


class PermanentError(RuntimeError):
    pass


def test_retry_returns_first_successful_result() -> None:
    result = retry_transient(
        lambda attempt: f"ok-{attempt}",
        is_transient=lambda e: isinstance(e, TransientError),
        max_attempts=3,
        base_delay=0,
        max_delay=0,
    )
    assert result == "ok-1"


def test_retry_retries_transient_and_returns() -> None:
    calls: list[int] = []

    def func(attempt: int) -> str:
        calls.append(attempt)
        if attempt < 3:
            raise TransientError(f"fail-{attempt}")
        return "done"

    result = retry_transient(
        func,
        is_transient=lambda e: isinstance(e, TransientError),
        max_attempts=3,
        base_delay=0,
        max_delay=0,
    )
    assert result == "done"
    assert calls == [1, 2, 3]


def test_retry_raises_permanent_error_immediately() -> None:
    calls: list[int] = []

    def func(attempt: int) -> str:
        calls.append(attempt)
        raise PermanentError("nope")

    with pytest.raises(PermanentError, match="nope"):
        retry_transient(
            func,
            is_transient=lambda e: isinstance(e, TransientError),
            max_attempts=3,
            base_delay=0,
            max_delay=0,
        )
    assert calls == [1]


def test_retry_raises_after_exhausting_attempts() -> None:
    calls: list[int] = []

    def func(attempt: int) -> str:
        calls.append(attempt)
        raise TransientError(f"fail-{attempt}")

    with pytest.raises(TransientError, match="fail-3"):
        retry_transient(
            func,
            is_transient=lambda e: isinstance(e, TransientError),
            max_attempts=3,
            base_delay=0,
            max_delay=0,
        )
    assert calls == [1, 2, 3]


def test_retry_sleeps_with_exponential_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", sleeps.append)

    def func(attempt: int) -> str:
        if attempt < 3:
            raise TransientError("fail")
        return "done"

    result = retry_transient(
        func,
        is_transient=lambda e: isinstance(e, TransientError),
        max_attempts=3,
        base_delay=1.0,
        max_delay=8.0,
    )
    assert result == "done"
    assert sleeps == [1.0, 2.0]


def test_retry_caps_delay_at_max() -> None:
    sleeps: list[float] = []

    def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    import app.services.retry as retry_mod

    original_sleep = retry_mod.time.sleep
    retry_mod.time.sleep = fake_sleep
    try:

        def func(attempt: int) -> str:
            if attempt < 5:
                raise TransientError("fail")
            return "done"

        result = retry_transient(
            func,
            is_transient=lambda e: isinstance(e, TransientError),
            max_attempts=5,
            base_delay=2.0,
            max_delay=8.0,
        )
        assert result == "done"
        assert sleeps == [2.0, 4.0, 8.0, 8.0]
    finally:
        retry_mod.time.sleep = original_sleep
