# Задача: tests/test_log_redact_extras.py

## Цель

Дополнительные тесты для `core.log_redact`. Базовый `tests/test_log_redact.py`
уже покрывает основной flow (8 тестов). Здесь — edge cases.

## Правила

1. pytest. Без моков. Используй `logging.StreamHandler` + `io.StringIO` для
   capture.
2. Без эмодзи.
3. Импорты:
   ```python
   import io
   import logging
   import sys
   from pathlib import Path
   import pytest
   ROOT = Path(__file__).resolve().parent.parent
   sys.path.insert(0, str(ROOT))
   from core.log_redact import RedactFilter, redact_text, REDACTED
   ```

## Контракт API

```python
def redact_text(text: str) -> str: ...

class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool: ...
```

Маскирует:
- Telegram bot-token в URL: `/bot<digits>:<token>` → `/bot<digits>:***REDACTED***`
- `Authorization: Bearer <token>` → `Authorization: Bearer ***REDACTED***`
- key-value пары для: `api_key`, `apikey`, `token`, `secret`, `authorization`,
  `auth_token` — value заменяется на `***REDACTED***`

## Обязательные тесты

### redact_text edge cases

1. **test_redact_text_with_empty_input** — `redact_text("")` → `""`.
   `redact_text(None)` — поведение? Если функция падает на None, протестируй
   что `redact_text("")` это валидный кейс. (NOT redact_text(None).)

2. **test_redact_text_no_secrets_returns_unchanged** — обычная строка без
   секретов → возвращается как есть, без модификаций.

3. **test_redact_multiple_secrets_in_one_line** — строка содержит
   и `token=abc`, и `api_key="xyz"` — оба замаскированы.

4. **test_redact_telegram_token_preserves_bot_id** — для
   `/bot123456:secret/sendMessage` после redact — `123456` остаётся
   (это id бота, не секрет), `secret` маскируется.

5. **test_redact_authorization_bearer_case_insensitive** — `authorization:
   bearer xxx` (lowercase), `Authorization: Bearer yyy`, `AUTHORIZATION:
   BEARER zzz` — все три должны замаскироваться.

6. **test_redact_key_value_with_quotes** — `api_key="quoted_value"` —
   маскируется (содержимое внутри кавычек заменено).

7. **test_redact_key_value_single_quotes** — `api_key='single_quoted'` —
   маскируется.

8. **test_redact_unrelated_key_not_touched** — `name=John`, `email=foo@bar`,
   `user_id=42` — НЕ маскируются (это не секретные ключи).

### RedactFilter integration

9. **test_filter_with_no_args** — `logger.info("hello world")` без `%s`.
   В output нет `***REDACTED***`, текст проходит как есть.

10. **test_filter_handles_dict_args** — `logger.info("%(key)s", {"key":
    "token=secret"})`. Filter должен обработать dict args корректно — в
    итоговом message `secret` замаскирован.

11. **test_filter_does_not_break_on_non_string_msg** — `logger.info(42)`
    (передан int как сообщение). Filter не падает, лог проходит.

12. **test_filter_returns_true_always** — `RedactFilter().filter(record)`
    всегда возвращает `True` (фильтр маскирует, но не отбрасывает записи).

13. **test_filter_preserves_record_level** — `logger.warning("token=x")`.
    После фильтра record.levelno == WARNING.

### Контракт REDACTED

14. **test_redacted_constant_is_non_empty_string** — `REDACTED` — непустая
    строка длиной ≥ 3 символов.

## Что НЕ делать

- Не моки.
- Не пиши `if __name__ == "__main__"`.
- Не передавай `None` в `redact_text` — функция может не быть устойчива к None
  (current impl: `if not text: return text` — обработает, но не гарантия API).

## Финальный ответ

Один Python-блок ```python ... ``` готового файла. Без пояснений.
