# Задача: tests/test_external_more.py

## Цель

Дополнительные тесты для `core.external.run_with_timeout`. Базовый
`tests/test_external.py` уже покрывает 6 сценариев. Здесь — edge cases
и контракт API.

## Правила

1. pytest + `pytest.mark.asyncio`. Без моков.
2. Без эмодзи.
3. Импорты:
   ```python
   import asyncio
   import sys
   from pathlib import Path
   import pytest
   ROOT = Path(__file__).resolve().parent.parent
   sys.path.insert(0, str(ROOT))
   from core.external import run_with_timeout
   ```

## Контракт API

```python
async def run_with_timeout(
    factory: Callable[[], Awaitable[T]],
    *,
    timeout_s: float,
    retries: int = 0,
    backoff_s: float = 2.0,
) -> T:
```

Поведение:
- factory должен быть callable, возвращающий coroutine. Не coroutine.
- timeout_s применяется к одной попытке.
- retries — ДОПОЛНИТЕЛЬНЫЕ попытки после первой (всего 1+retries вызовов).
- backoff_s — пауза между попытками (asyncio.sleep).
- Передача coroutine → TypeError.
- Передача не-callable → TypeError.

## Обязательные тесты

### Контракт API

1. **test_passing_non_callable_raises_typeerror** — `run_with_timeout(42,
   timeout_s=1.0)` → TypeError.

2. **test_passing_string_raises_typeerror** — `run_with_timeout("not a function",
   timeout_s=1.0)` → TypeError.

### Граничные значения параметров

3. **test_retries_zero_means_one_attempt_total** — factory который всегда
   падает. С `retries=0` factory должен быть вызван ровно 1 раз. Используй
   счётчик.

4. **test_retries_n_means_n_plus_one_attempts** — factory всегда падает,
   `retries=3` → factory вызван ровно 4 раза.

5. **test_backoff_zero_does_not_sleep** — factory вызывается дважды (первая
   падает, вторая успех), `backoff_s=0`. Засеки `time.monotonic()` до и
   после — общее время <0.5 сек.

6. **test_backoff_applied_between_retries** — factory с `retries=2`,
   `backoff_s=0.1`. Если factory всегда падает, общее время ≥ 2*0.1 = 0.2 сек
   (две паузы между тремя попытками).

### Возвращаемые значения

7. **test_returns_none_value_correctly** — factory возвращает None.
   `result = await run_with_timeout(...)` → result is None (не путать
   с retry-by-error).

8. **test_returns_complex_object** — factory возвращает `{"key": "value",
   "n": 42}` (dict). Возвращается тот же объект.

### Поведение исключений

9. **test_keyboardinterrupt_propagates** — factory кидает
   `KeyboardInterrupt`. Должно пройти наружу без подавления (retries
   игнорируются для interrupts — но в текущей реализации они идут через
   except BaseException... СМОТРИ В КОДЕ).
   ВАЖНО: текущий код использует `except BaseException` — это значит
   KeyboardInterrupt тоже ретраится. Это не идеально, но это поведение.
   Тест: KeyboardInterrupt с retries=0 → пробрасывается сразу.

10. **test_cancellederror_with_retries_propagates_eventually** —
    factory кидает `asyncio.CancelledError`. С retries=1 — после двух
    попыток пробрасывается. Контракт: после исчерпания retries
    последняя exception (CancelledError) пробрасывается.

11. **test_timeout_during_long_operation** — factory создаёт coroutine
    которая `await asyncio.sleep(5)`. timeout_s=0.05. retries=0 →
    asyncio.TimeoutError. ВАЖНО: после TimeoutError coroutine должна
    быть отменена (asyncio.wait_for делает это автоматически).

### Параллельность

12. **test_concurrent_calls_independent** — два независимых вызова
    `run_with_timeout` через `asyncio.gather`. Оба должны выполниться
    независимо (счётчики двух factory должны быть инкрементированы
    параллельно, не последовательно).

## Что НЕ делать

- Не моки (asyncio.Future не нужен — пишем обычные async-функции).
- Не пиши `if __name__ == "__main__"`.
- НЕ передавай coroutine как factory: только callable→coroutine.

## Финальный ответ

Один Python-блок ```python ... ``` готового файла. Без пояснений.
