# Задача: tests/test_migrate_json_to_sqlite.py

## Цель

Pytest-тесты для `scripts.migrate_json_to_sqlite`. Покрываем:
- `collect_plan()` — dry-run отчёт по JSON-файлам
- `apply_migration(db_path)` — реальная запись в SQLite

ВАЖНО: тесты не должны трогать настоящие JSON-файлы проекта.
Используй `tmp_path` + monkeypatch путей.

## Правила

1. pytest. Без моков, кроме `monkeypatch` путей.
2. Без эмодзи.
3. Импорты:
   ```python
   import json
   import sys
   import sqlite3
   from pathlib import Path
   import pytest
   ROOT = Path(__file__).resolve().parent.parent
   sys.path.insert(0, str(ROOT))
   sys.path.insert(0, str(ROOT / "scripts"))
   import migrate_json_to_sqlite as mig
   from core.sqlite_schema import open_db, EXPECTED_TABLES
   ```

## Структура `migrate_json_to_sqlite`

```python
JSON_FILES = {
    "state":          (ROOT/"state.json",          dict),
    "history":        (ROOT/"history.json",        list),
    "news_drafts":    (ROOT/"news_drafts.json",    list),
    "author_drafts":  (ROOT/"author_notes_drafts.json", list),
    "weekly_drafts":  (ROOT/"weekly_diary_drafts.json", list),
    "confirm_trades": (ROOT/"confirm_trades.json", list),
    "live_trades":    (ROOT/"live_trades.json",    list),
    "live_journal":   (ROOT/"live_trade_journal.json", list),
    "news_history":   (ROOT/"news_history.json",   list),
}

def collect_plan() -> dict: ...
def apply_migration(db_path: Path) -> dict: ...
```

## Fixture для изоляции

```python
@pytest.fixture(autouse=True)
def _isolate_json_paths(tmp_path, monkeypatch):
    """Перенаправляем все 9 JSON-файлов на tmp_path."""
    paths = {}
    for key, (orig, kind) in mig.JSON_FILES.items():
        new_path = tmp_path / orig.name
        paths[key] = (new_path, kind)
    monkeypatch.setattr(mig, "JSON_FILES", paths)
    yield tmp_path
```

## Helper для записи JSON

```python
def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
```

## Обязательные тесты

### collect_plan() — empty

1. **test_collect_plan_on_empty_dir** — нет JSON-файлов. `plan = collect_plan()`.
   Все счётчики = 0:
   - `plan["state_kv_keys"] == 0`
   - `plan["post_history_rows"] == 0`
   - `plan["drafts_total"] == 0`
   - `plan["trades_total"] == 0`
   - `plan["journals_total"] == 0`

### collect_plan() — populated

2. **test_collect_plan_state_kv_keys** — `_write(state.json, {"a":1, "b":2, "c":3})`.
   `plan["state_kv_keys"] == 3`.

3. **test_collect_plan_post_history_rows** — `_write(history.json, [{"x":1},
   {"x":2}, {"x":3}])`. `plan["post_history_rows"] == 3`.

4. **test_collect_plan_drafts_by_type** — `_write(news_drafts.json,
   [{}, {}, {}])`, `author_drafts.json -> [{}, {}]`, `weekly_drafts.json -> []`.
   `plan["drafts_total"] == 5`, `plan["drafts_by_type"] == {"news": 3,
   "author": 2, "weekly": 0}`.

5. **test_collect_plan_trades_by_type** — `confirm_trades.json -> [{},{}]`,
   `live_trades.json -> [{}]`. `plan["trades_total"] == 3`,
   `plan["trades_by_type"] == {"confirm": 2, "live": 1}`.

6. **test_collect_plan_journals_total** — `live_journal -> [{},{},{}]`,
   `news_history -> [{},{}]`. `plan["journals_total"] == 5`.

### apply_migration() — empty

7. **test_apply_creates_db_with_all_tables** — нет JSON-файлов.
   `mig.apply_migration(tmp_path / "out.sqlite")`. Файл существует,
   `EXPECTED_TABLES` — все есть в базе.

8. **test_apply_empty_inserts_zero_rows** — пустые JSON. Все
   inserted counters == 0.

### apply_migration() — state_kv

9. **test_apply_writes_state_kv_keys** — `state.json = {"post_count":
   42, "list_val": [1, 2]}`. После apply: запросом
   `SELECT key, value_json FROM state_kv` возвращает 2 строки.
   `json.loads(row["value_json"])` для post_count = 42, для list_val = [1, 2].

10. **test_apply_state_kv_replace_existing** — apply дважды подряд
    с одним `state.json`. После: ровно 2 записи (state_kv использует
    INSERT OR REPLACE). Перезапись не должна давать дублей.

### apply_migration() — post_history

11. **test_apply_writes_post_history** — `history.json` с 3 записями:
    ```json
    [{"datetime": "2026-01-01T00:00:00+00:00", "post_type": "market",
      "published_to": "channel", "short_summary": "x"},
     {"datetime": "2026-01-02T00:00:00+00:00", "post_type": "news"},
     {"datetime": "2026-01-03T00:00:00+00:00", "post_type": "market"}]
    ```
    После apply: 3 строки в post_history. Запрос
    `SELECT COUNT(*) FROM post_history` → 3.
    `SELECT post_type FROM post_history` содержит "market" дважды.

12. **test_apply_history_skips_non_dict_entries** — `history.json =
    [{"datetime": "...", "post_type": "market"}, "garbage", 42]`.
    После apply: ровно 1 запись.

13. **test_apply_history_missing_datetime_uses_now** — запись без
    `"datetime"` ключа. Apply не падает. Записанный datetime —
    непустая строка (используется `now()`).

### apply_migration() — drafts

14. **test_apply_writes_drafts_with_type** — `news_drafts.json =
    [{"draft_id": "d1", "status": "pending_review",
      "created_at": "2026-05-14T10:00:00+00:00"}]`. После apply:
    `SELECT draft_type FROM drafts WHERE draft_id = 'd1'` = "news".

15. **test_apply_drafts_skip_when_missing_id** — `news_drafts.json
    = [{"status": "pending_review"}, {"draft_id": "d2", "status":
    "published"}]`. Запись без draft_id скипается. После apply:
    1 запись в drafts (только d2).

16. **test_apply_drafts_type_maps_correctly** — `author_drafts.json
    = [{"draft_id": "a1", "status": "pending_review", "created_at":
    "2026-05-14T10:00:00+00:00"}]`. После apply: `SELECT draft_type
    WHERE draft_id = 'a1'` = "author_note".

### apply_migration() — trades

17. **test_apply_writes_trades_with_type** — `confirm_trades.json =
    [{"id": "t1", "status": "active", "symbol": "BTC/USDT:USDT"}]`.
    После apply: `SELECT trade_type, symbol FROM trades WHERE
    trade_id = 't1'` → ("confirm", "BTC/USDT:USDT").

18. **test_apply_trades_skip_when_missing_id** — запись без `"id"`.
    Скипается.

### apply_migration() — journals

19. **test_apply_writes_journals** — `live_journal.json = [{"event":
    "entry_submitted", "logged_at": "2026-05-14T10:00:00+00:00"}]`.
    После apply: 1 запись в journals с `journal_type = "live_trades"`
    и `event_type = "entry_submitted"`.

20. **test_apply_journal_fallback_event_type** — запись без
    `"event"` / `"decision"` ключей. После apply: `event_type ==
    "unknown"`.

### Return value

21. **test_apply_returns_inserted_counts_dict** — После apply
    возвращается dict с ключами: state_kv, post_history, drafts,
    trades, journals. Все значения — int.

## Что НЕ делать

- Не моки.
- Не пиши `if __name__ == "__main__"`.
- Не используй `subprocess.run` — вызывай функции напрямую.
- Не вызывай `main()` (он печатает в stdout) — используй
  `collect_plan()` и `apply_migration()` напрямую.

## Финальный ответ

Один Python-блок ```python ... ``` готового файла. Без пояснений.
