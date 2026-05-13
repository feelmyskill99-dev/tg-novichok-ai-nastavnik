# Задача: tests/test_sqlite_dao_more.py

## Цель

Дополнительные edge-case тесты для `core.sqlite_dao` readers.
Базовый `tests/test_sqlite_dao.py` (23 теста) покрывает основной flow.
Здесь — corrupt-data scenarios + ordering + larger payload checks.

## Правила

1. pytest + `tmp_path`. Без моков.
2. Без эмодзи.
3. Импорты:
   ```python
   import json
   import sys
   from pathlib import Path
   import pytest
   ROOT = Path(__file__).resolve().parent.parent
   sys.path.insert(0, str(ROOT))
   from core.sqlite_dao import (
       SqliteDraftReader, SqlitePostHistoryReader,
       SqliteStateReader, SqliteTradeReader,
   )
   from core.sqlite_schema import open_db, init_schema
   ```

## Fixture

```python
@pytest.fixture
def empty_db(tmp_path):
    db = tmp_path / "test.sqlite"
    conn = open_db(db)
    init_schema(conn)
    conn.close()
    return db
```

## Helper

```python
def _insert_state(db, k, v):
    conn = open_db(db)
    conn.execute(
        "INSERT INTO state_kv (key, value_json, updated_at) VALUES (?, ?, ?);",
        (k, v, "2026-05-14T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()


def _insert_history(db, datetime_iso, post_type, payload):
    conn = open_db(db)
    conn.execute(
        "INSERT INTO post_history (datetime, post_type, payload_json) VALUES (?, ?, ?);",
        (datetime_iso, post_type, json.dumps(payload, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()


def _insert_draft(db, draft_id, draft_type, status, payload):
    conn = open_db(db)
    conn.execute(
        "INSERT INTO drafts (draft_id, draft_type, status, created_at, payload_json) "
        "VALUES (?, ?, ?, ?, ?);",
        (draft_id, draft_type, status, "2026-05-14T10:00:00+00:00",
         json.dumps(payload, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()
```

## Обязательные тесты

### SqliteStateReader

1. **test_state_reader_get_with_invalid_json_returns_none** — запиши
   value_json равным `"not valid json{"` (через _insert_state).
   `reader.get("key1")` возвращает None (без падения).

2. **test_state_reader_get_with_unicode_value** —
   value_json = `'"привет"'` (валидный JSON-string). Должен вернуть `"привет"`.

3. **test_state_reader_get_list_value** — value_json = `'[1, 2, 3]'`.
   Должен вернуть `[1, 2, 3]`.

4. **test_state_reader_get_bool_value** — value_json = `'true'`.
   Должен вернуть `True`.

5. **test_state_reader_get_null_value** — value_json = `'null'`.
   Должен вернуть `None` (это валидное JSON значение null).

6. **test_state_reader_keys_returns_sorted** — вставь ключи
   `["zebra", "alpha", "mango"]`. `reader.keys()` → отсортированный список.

7. **test_state_reader_keys_empty** — empty_db, ничего не вставлено.
   `reader.keys()` → `[]` (не падает).

### SqlitePostHistoryReader

8. **test_post_history_payload_handles_invalid_json** — запиши строку
   с payload_json = `"not json"`. `list_recent()` не падает, payload
   = `{}` (или подобное "пустое" значение).

9. **test_post_history_list_recent_zero_limit** — `list_recent(limit=0)`.
   Возвращает `[]`.

10. **test_post_history_list_recent_negative_limit** —
    `list_recent(limit=-1)`. Возвращает `[]` или не падает (SQLite
    с LIMIT -1 = unlimited; убедись что просто не падает).

11. **test_post_history_count_independent_of_other_tables** — вставь
    несколько drafts и trades, но 0 history. `count() == 0`.

12. **test_post_history_list_by_type_returns_empty_for_missing_type** —
    вставь 3 market записи. `list_by_type("nonexistent")` → `[]`.

### SqliteDraftReader

13. **test_draft_reader_get_with_invalid_payload_json** — вставь draft
    с payload_json = `"garbage"`. `reader.get("d1")` не падает, payload
    = `{}`.

14. **test_draft_reader_list_pending_excludes_rejected** — вставь
    drafts: `d1` pending_review, `d2` rejected, `d3` published, `d4`
    revised. `list_pending()` возвращает 2 элемента (d1 и d4).

15. **test_draft_reader_list_pending_ordering_by_created_at_desc** —
    вставь drafts с `created_at` разных дней; проверь что результат
    отсортирован DESC (новые сверху). Используй прямые INSERT через
    `_insert_draft`-like helper, чтобы контролировать дату.

16. **test_draft_reader_count_zero_for_missing_type** — есть только
    news drafts. `count(draft_type="weekly_diary") == 0`.

### SqliteTradeReader

17. **test_trade_reader_list_active_empty_when_all_terminal** — вставь
    trades со статусами `closed_take_profit`, `rejected`,
    `expired_confirmation`. `list_active()` → `[]`.

18. **test_trade_reader_list_active_includes_all_non_terminal** —
    проверь что все 7 NON_TERMINAL статусов корректно проходят:
    `created`, `awaiting_confirmation`, `approved`,
    `entry_order_submitted`, `entry_filled`,
    `protection_orders_submitted`, `active`. Вставь по одному trade
    для каждого. `list_active()` возвращает все 7.

19. **test_trade_reader_find_with_invalid_payload_json** — вставь
    trade с payload_json = `"bad"`. `find("t1")` не падает, payload
    = `{}`.

### Cross-cutting

20. **test_missing_db_raises_for_all_readers** — для каждого из 4
    reader-классов: создать с путём к несуществующему файлу. Любой
    запрос → `FileNotFoundError`.

21. **test_concurrent_reads_independent** — 2 SqlitePostHistoryReader
    инстанса на одну и ту же базу. Вызови `count()` на обоих. Оба
    возвращают одинаковое значение (нет race на open/close).

## Что НЕ делать

- Не моки.
- Не пиши `if __name__ == "__main__"`.
- Не используй `subprocess.run`.
- Не вставляй данные напрямую через open_db без commit — обязательно
  commit + close после вставки.

## Финальный ответ

Один Python-блок ```python ... ``` готового файла. Без пояснений.
