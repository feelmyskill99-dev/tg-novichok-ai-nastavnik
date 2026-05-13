# Задача: tests/test_check_env_extras.py

## Цель

Дополнительные тесты для `scripts.check_env.check_env`. Базовый
`tests/test_check_env.py` (6 тестов) уже покрывает основные случаи.
Здесь — granular edge cases и контракт.

## Правила

1. pytest. Без моков.
2. Без эмодзи.
3. Импорты:
   ```python
   import sys
   from pathlib import Path
   import pytest
   ROOT = Path(__file__).resolve().parent.parent
   sys.path.insert(0, str(ROOT))
   sys.path.insert(0, str(ROOT / "scripts"))
   from check_env import (
       check_env,
       ADMIN_FORBIDDEN_PASSWORDS,
       REQUIRED,
       EXPECTED_FLAGS,
   )
   ```

## Контракт

```python
def check_env(env: dict[str, str] | None = None) -> tuple[bool, list[str], list[str]]:
    """Возвращает (ok, missing_required, flag_problems)."""
```

- `env=None` → читается из `os.environ`.
- REQUIRED проверяется на наличие непустого значения после strip.
- EXPECTED_FLAGS — каждый флаг должен равняться ожидаемому значению (case-insensitive после strip).
- ADMIN_PASSWORD — если задан и в FORBIDDEN — проблема. Если не задан или пустой — OK (CLI без админки).
- ok = (not missing) and (not flag_problems).

## Базовый _VALID_ENV

```python
_VALID_ENV = {
    "TELEGRAM_TOKEN": "123:abc",
    "CHANNEL_ID": "@chan",
    "OWNER_CHAT_ID": "1",
    "CLAUDE_API_KEY": "sk-x",
    "OPENAI_API_KEY": "sk-y",
    "PARTNER_URL": "https://example.com",
    "DRY_RUN": "true",
    "GENERATE_IMAGES": "true",
    "GENERATE_VIDEO": "false",
    "ENABLE_WEBHOOK": "false",
}
```

## Обязательные тесты

### REQUIRED variants

1. **test_required_whitespace_only_treated_as_missing** — установить
   `TELEGRAM_TOKEN="   "` (только пробелы). `missing` содержит
   `"TELEGRAM_TOKEN"`, `ok=False`.

2. **test_all_required_keys_checked** — для каждого ключа из REQUIRED
   делаем env без него — он попадает в missing. (Параметризованный
   тест через `@pytest.mark.parametrize`.)

3. **test_missing_two_or_more_reports_all** — env без CLAUDE_API_KEY
   и OPENAI_API_KEY. missing содержит оба, не один.

### FLAGS variants

4. **test_each_flag_wrong_value_reported** — для каждого ключа из
   EXPECTED_FLAGS делаем env с противоположным значением. Этот ключ
   должен быть в `flag_problems`.

5. **test_flag_case_insensitive_match** — `DRY_RUN="TRUE"` (uppercase),
   ожидается "true". Должно совпасть → не в problems.

6. **test_flag_with_whitespace_stripped** — `DRY_RUN="  true  "`.
   Не в problems (strip применяется).

7. **test_flag_missing_treated_as_empty_then_wrong** — env без
   `DRY_RUN`. EXPECTED `DRY_RUN="true"`. Пустое != "true" → в problems.

### ADMIN_PASSWORD variants

8. **test_admin_password_weak_password_each** — для каждого слова из
   ADMIN_FORBIDDEN_PASSWORDS (кроме пустой "") делаем env с этим
   паролем. `ADMIN_PASSWORD` должен быть в problems.

9. **test_admin_password_uppercase_forbidden_still_caught** —
   `ADMIN_PASSWORD="CHANGEME"` (uppercase). Case-insensitive match
   → в problems.

10. **test_admin_password_strong_passes** — `ADMIN_PASSWORD="Tg!Bot2026XyZ"`.
    Не в problems.

11. **test_admin_password_unset_does_not_fail** — env БЕЗ
    ADMIN_PASSWORD. `ok=True` (CLI работает без админки).

### Контракт возврата

12. **test_check_env_returns_tuple_of_three** — результат — кортеж
    из 3 элементов: bool, list, list.

13. **test_check_env_with_none_reads_from_os_environ** — `monkeypatch.setenv`
    все требуемые переменные. Вызови `check_env(env=None)` — должно
    использовать os.environ и вернуть ok=True.

14. **test_constants_contract** — `len(REQUIRED) >= 6`,
    `len(EXPECTED_FLAGS) >= 4`, `"" in ADMIN_FORBIDDEN_PASSWORDS`,
    `"changeme" in ADMIN_FORBIDDEN_PASSWORDS`.

## Что НЕ делать

- Не моки.
- Не пиши `if __name__ == "__main__"`.
- Не используй `load_dotenv` — тесты передают env как аргумент.

## Финальный ответ

Один Python-блок ```python ... ``` готового файла. Без пояснений.
