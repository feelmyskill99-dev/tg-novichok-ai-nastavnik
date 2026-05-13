"""Этап 1.6: безопасные обёртки над внешними API.

`run_with_timeout(factory, timeout_s, retries)` — выполняет coroutine с
таймаутом, на ошибку/таймаут делает retries попыток заново. ВАЖНО: принимает
factory (callable, возвращающий coroutine), а не готовую coroutine, иначе
повторное `await` сломается.

Для sync-клиентов (ccxt, Anthropic, OpenAI), которые блокируют поток,
используйте `asyncio.to_thread(...)` внутри factory:

    await run_with_timeout(
        lambda: asyncio.to_thread(claude.messages.create, model=..., ...),
        timeout_s=30.0, retries=1,
    )
"""
from __future__ import annotations

import asyncio
import inspect
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")


async def run_with_timeout(
    factory: Callable[[], Awaitable[T]],
    *,
    timeout_s: float,
    retries: int = 0,
    backoff_s: float = 2.0,
) -> T:
    """Выполнить coroutine от factory с таймаутом и retry.

    Args:
        factory: callable, возвращающий coroutine. На каждую попытку вызывается заново.
        timeout_s: лимит времени на одну попытку.
        retries: дополнительные попытки после первой (всего вызовов: 1 + retries).
        backoff_s: пауза между попытками.

    Raises:
        TypeError: если передан не factory, а coroutine/иное.
        asyncio.TimeoutError | Exception: последняя ошибка после исчерпания retries.
    """
    if inspect.iscoroutine(factory):
        raise TypeError(
            "run_with_timeout получил coroutine. Передавайте factory: lambda: my_coro()"
        )
    if not callable(factory):
        raise TypeError("factory должен быть callable")

    attempts = retries + 1
    last_exc: BaseException | None = None
    for i in range(attempts):
        try:
            coro = factory()
            return await asyncio.wait_for(coro, timeout=timeout_s)
        except BaseException as exc:
            last_exc = exc
            if i + 1 >= attempts:
                raise
            await asyncio.sleep(backoff_s)
    # недостижимо
    assert last_exc is not None
    raise last_exc
