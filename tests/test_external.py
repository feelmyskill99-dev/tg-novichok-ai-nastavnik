"""Этап 1.6: run_with_timeout — обёртка над coroutine-factory с retry.

Контракт:
- factory: callable, возвращающий coroutine (НЕ готовую coroutine, чтобы retry работал)
- timeout_s: float
- retries: int — сколько ДОПОЛНИТЕЛЬНЫХ попыток после первой неудачи

Поведение:
- успех с первого раза → возвращает результат
- timeout / exception → retry до retries раз, потом пробрасывает последнюю ошибку
- factory вызывается заново на каждой попытке (важно — иначе coroutine reused)
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.external import run_with_timeout


@pytest.mark.asyncio
async def test_success_returns_result():
    async def _ok():
        return 42

    result = await run_with_timeout(_ok, timeout_s=1.0, retries=0)
    assert result == 42


@pytest.mark.asyncio
async def test_timeout_raises_after_no_retries():
    async def _slow():
        await asyncio.sleep(10)
        return "never"

    with pytest.raises(asyncio.TimeoutError):
        await run_with_timeout(_slow, timeout_s=0.05, retries=0)


@pytest.mark.asyncio
async def test_retry_recovers_from_initial_failure():
    state = {"attempts": 0}

    async def _flaky():
        state["attempts"] += 1
        if state["attempts"] < 2:
            raise RuntimeError("boom")
        return "ok"

    result = await run_with_timeout(_flaky, timeout_s=1.0, retries=2, backoff_s=0.01)

    assert result == "ok"
    assert state["attempts"] == 2


@pytest.mark.asyncio
async def test_factory_called_fresh_each_attempt():
    """Factory должен вызываться заново — иначе вторая попытка получит уже
    исчерпанный coroutine (RuntimeError: cannot reuse already awaited coroutine)."""
    state = {"calls": 0}

    async def _failing():
        return None

    def factory():
        state["calls"] += 1
        return _failing_then_ok(state["calls"])

    async def _failing_then_ok(attempt: int):
        if attempt < 3:
            raise ValueError(f"attempt {attempt}")
        return "win"

    result = await run_with_timeout(factory, timeout_s=1.0, retries=3, backoff_s=0.01)
    assert result == "win"
    assert state["calls"] == 3


@pytest.mark.asyncio
async def test_raises_last_exception_after_exhausted_retries():
    state = {"attempts": 0}

    async def _always_fails():
        state["attempts"] += 1
        raise ValueError(f"fail-{state['attempts']}")

    with pytest.raises(ValueError, match="fail-3"):
        await run_with_timeout(_always_fails, timeout_s=1.0, retries=2, backoff_s=0.01)
    assert state["attempts"] == 3


@pytest.mark.asyncio
async def test_passing_coroutine_not_factory_raises_typeerror():
    """Безопасность: если передать coro вместо callable — должен быть понятный отказ."""
    async def _ok():
        return 1

    coro = _ok()
    try:
        with pytest.raises(TypeError):
            await run_with_timeout(coro, timeout_s=1.0, retries=0)
    finally:
        coro.close()
