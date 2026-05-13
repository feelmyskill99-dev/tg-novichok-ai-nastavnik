# Задача: tests/test_safety_sentinel.py

## Цель

Pytest-тесты для `core.safety.Sentinel`. Класс ловит исключения корутины и
публикует fallback-пост + DM владельцу с stack trace.

## Правила

1. pytest + `pytest.mark.asyncio`. Используй minimal in-process `_FakeBot`
   класс (НЕ MagicMock — лучше явная заглушка).
2. Без эмодзи в коде/комментариях.
3. Импорты:
   ```python
   import json
   import sys
   from pathlib import Path
   import pytest
   ROOT = Path(__file__).resolve().parent.parent
   sys.path.insert(0, str(ROOT))
   from core.safety import Sentinel
   ```

## Контракт API

```python
class Sentinel:
    def __init__(self, bot, channel_id, owner_chat_id, fallback_file="fallback_lessons.json"):
        ...

    async def safe_execute(self, coro, context: str = "") -> None:
        # выполняет coro; при exception:
        #   1) шлёт DM владельцу с traceback
        #   2) публикует случайный fallback-пост в канал
```

## Структура fallback_lessons.json

```json
[
  {"title": "Урок 1", "body": "Текст урока 1"},
  {"title": "Урок 2", "body": "Текст урока 2"}
]
```

## Helper в начале файла

```python
class _FakeBot:
    """Minimal stand-in для aiogram.Bot. Записывает все send_message-вызовы."""

    def __init__(self) -> None:
        self.calls: list[tuple[int | str, str, dict]] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.calls.append((chat_id, text, dict(kwargs)))


def _make_fallback_file(tmp_path, items):
    p = tmp_path / "fallback.json"
    p.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return p
```

## Обязательные тесты

### Конструктор

1. **test_init_loads_fallback_file** — создай fallback файл с 2 уроками.
   `Sentinel(_FakeBot(), "@chan", 123, fallback_file=str(p))`. После
   init: `sentinel.fallback_posts == [{"title": "Урок 1", ...}, ...]`.

2. **test_init_empty_fallback_raises** — fallback файл с пустым
   массивом `[]`. Sentinel.__init__ должен бросить `ValueError`
   (см. `_load_fallback`).

3. **test_init_missing_file_raises** — fallback файл не существует —
   `FileNotFoundError`.

### safe_execute — happy path

4. **test_safe_execute_runs_coro_normally** — passing coro без
   исключений. `bot.calls` остаётся пустым (нет DM/fallback). Coro
   должна реально выполниться: используй счётчик внутри.

5. **test_safe_execute_returns_none_on_success** — `result = await
   sentinel.safe_execute(...)`. Result — `None` (метод ничего не возвращает).

### safe_execute — error path

6. **test_safe_execute_sends_dm_on_exception** — coro бросает
   `RuntimeError("boom")`. После safe_execute:
   - `bot.calls` содержит ≥ 1 запись с `owner_chat_id=123`
   - Текст содержит `"СБОЙ"`, `"RuntimeError"`, `"boom"`.

7. **test_safe_execute_publishes_fallback_to_channel** — coro падает.
   `bot.calls` содержит запись с `chat_id="@chan"` и текстом
   из fallback_posts (`Урок 1\n\nТекст урока 1` или `Урок 2...`).

8. **test_safe_execute_two_calls_on_failure** — coro падает. Всего
   `len(bot.calls) == 2` (один DM + один channel publish).

9. **test_safe_execute_passes_context_in_dm** — `await sentinel.safe_execute(
   coro, context="news_publish")`. DM-текст содержит `"news_publish"`.

10. **test_safe_execute_no_context_uses_default** — без context.
    DM-текст содержит `"неизвестно"` или подобное.

11. **test_safe_execute_truncates_long_traceback** — coro кидает
    исключение с длинным traceback. DM-текст не превышает разумной
    длины. По коду: `tb[-1500:]` — последние 1500 chars.
    Точная проверка: создай exception с глубокой вложенностью
    (recursive raise через `_deep_raise(depth=50)`). DM-текст
    содержит `"```"` (markdown code block) и общая длина < 4000.

12. **test_safe_execute_traceback_in_markdown_code_block** —
    DM-текст содержит `"```"` (открытие code block).

### Random fallback selection

13. **test_fallback_post_is_one_of_loaded** — fallback файл с 5
    уроками. Падай 10 раз → каждый channel-publish-текст должен
    совпадать с одним из 5 уроков (после parse). Не обязательно
    все 5 использованы (random), главное — нет «чужих».

14. **test_fallback_includes_title_and_body** — fallback файл с
    одним уроком `{"title": "T", "body": "B"}`. Падай. Channel-текст
    содержит и `"T"`, и `"B"`.

## Что НЕ делать

- Не используй MagicMock/AsyncMock. _FakeBot достаточно.
- Не пиши `if __name__ == "__main__"`.
- Не дёргай реальный Telegram API.

## Финальный ответ

Один Python-блок ```python ... ``` готового файла. Без пояснений.
