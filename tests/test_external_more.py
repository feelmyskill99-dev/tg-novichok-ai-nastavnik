import asyncio
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.external import run_with_timeout


@pytest.mark.asyncio
async def test_passing_non_callable_raises_typeerror():
    with pytest.raises(TypeError):
        await run_with_timeout(42, timeout_s=1.0)


@pytest.mark.asyncio
async def test_passing_string_raises_typeerror():
    with pytest.raises(TypeError):
        await run_with_timeout("not a function", timeout_s=1.0)


@pytest.mark.asyncio
async def test_retries_zero_means_one_attempt_total():
    counter = 0

    async def failing_factory():
        nonlocal counter
        counter += 1
        raise ValueError("fail")

    with pytest.raises(ValueError):
        await run_with_timeout(failing_factory, timeout_s=1.0, retries=0)
    assert counter == 1


@pytest.mark.asyncio
async def test_retries_n_means_n_plus_one_attempts():
    counter = 0

    async def failing_factory():
        nonlocal counter
        counter += 1
        raise ValueError("fail")

    with pytest.raises(ValueError):
        await run_with_timeout(failing_factory, timeout_s=1.0, retries=3)
    assert counter == 4


@pytest.mark.asyncio
async def test_backoff_zero_does_not_sleep():
    call_count = 0

    async def factory():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ValueError("first fail")
        return "success"

    start = time.monotonic()
    result = await run_with_timeout(factory, timeout_s=1.0, retries=1, backoff_s=0.0)
    elapsed = time.monotonic() - start
    assert result == "success"
    assert call_count == 2
    assert elapsed < 0.5


@pytest.mark.asyncio
async def test_backoff_applied_between_retries():
    call_count = 0

    async def failing_factory():
        nonlocal call_count
        call_count += 1
        raise ValueError("fail")

    start = time.monotonic()
    with pytest.raises(ValueError):
        await run_with_timeout(failing_factory, timeout_s=1.0, retries=2, backoff_s=0.1)
    elapsed = time.monotonic() - start
    assert call_count == 3
    assert elapsed >= 0.19  # two pauses of 0.1s, allow small tolerance


@pytest.mark.asyncio
async def test_returns_none_value_correctly():
    async def factory():
        return None

    result = await run_with_timeout(factory, timeout_s=1.0)
    assert result is None


@pytest.mark.asyncio
async def test_returns_complex_object():
    expected = {"key": "value", "n": 42}

    async def factory():
        return expected

    result = await run_with_timeout(factory, timeout_s=1.0)
    assert result == expected


@pytest.mark.asyncio
async def test_keyboardinterrupt_propagates():
    async def factory():
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        await run_with_timeout(factory, timeout_s=1.0, retries=0)


@pytest.mark.asyncio
async def test_cancellederror_with_retries_propagates_eventually():
    call_count = 0

    async def factory():
        nonlocal call_count
        call_count += 1
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await run_with_timeout(factory, timeout_s=1.0, retries=1)
    assert call_count == 2


@pytest.mark.asyncio
async def test_timeout_during_long_operation():
    async def factory():
        await asyncio.sleep(5)
        return "too late"

    with pytest.raises(asyncio.TimeoutError):
        await run_with_timeout(factory, timeout_s=0.05, retries=0)


@pytest.mark.asyncio
async def test_concurrent_calls_independent():
    counter1 = 0
    counter2 = 0

    async def factory1():
        nonlocal counter1
        counter1 += 1
        await asyncio.sleep(0.1)
        return "ok1"

    async def factory2():
        nonlocal counter2
        counter2 += 1
        await asyncio.sleep(0.1)
        return "ok2"

    start = time.monotonic()
    results = await asyncio.gather(
        run_with_timeout(factory1, timeout_s=1.0),
        run_with_timeout(factory2, timeout_s=1.0),
    )
    elapsed = time.monotonic() - start
    assert results == ["ok1", "ok2"]
    assert counter1 == 1
    assert counter2 == 1
    assert elapsed < 0.2  # parallel execution should be ~0.1s