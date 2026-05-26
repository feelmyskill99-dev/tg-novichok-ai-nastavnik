"""Dry-run миграция JSON-stores в SQLite (этап 3.4 шаг 1).

Использование:
    python scripts/migrate_json_to_sqlite.py             # dry-run отчёт
    python scripts/migrate_json_to_sqlite.py --apply     # реально пишет в data.sqlite
    python scripts/migrate_json_to_sqlite.py --apply --db custom.sqlite

Без --apply: только читает JSON-файлы, считает записи, проверяет ожидаемые
поля, печатает план. НИЧЕГО НЕ ПИШЕТ.

С --apply: создаёт `data.sqlite` рядом с .env, инициализирует схему через
core.sqlite_schema.init_schema, импортирует записи. Бизнес-логика бота
продолжает использовать JSON-файлы — это снимок для будущего перехода.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.json_store import load_json
from core.sqlite_schema import open_db, init_schema, list_tables, EXPECTED_TABLES


JSON_FILES = {
    "state":          (ROOT / "state.json",          dict),
    "history":        (ROOT / "history.json",        list),
    "news_drafts":    (ROOT / "news_drafts.json",    list),
    "author_drafts":  (ROOT / "author_notes_drafts.json", list),
    "weekly_drafts":  (ROOT / "weekly_diary_drafts.json", list),
    "confirm_trades": (ROOT / "confirm_trades.json", list),
    "live_trades":    (ROOT / "live_trades.json",    list),
    "live_journal":   (ROOT / "live_trade_journal.json", list),
    "news_history":   (ROOT / "news_history.json",   list),
}


def _read(path: Path, default_type: type) -> Any:
    return load_json(path, default=default_type(), expected_type=default_type)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def collect_plan() -> dict:
    """Считает что мы хотим импортировать, без записи."""
    plan: dict[str, Any] = {}
    state = _read(*JSON_FILES["state"])
    plan["state_kv_keys"] = len(state)

    plan["post_history_rows"] = len(_read(*JSON_FILES["history"]))

    drafts = {
        "news":   _read(*JSON_FILES["news_drafts"]),
        "author": _read(*JSON_FILES["author_drafts"]),
        "weekly": _read(*JSON_FILES["weekly_drafts"]),
    }
    plan["drafts_total"] = sum(len(v) for v in drafts.values())
    plan["drafts_by_type"] = {k: len(v) for k, v in drafts.items()}

    trades = {
        "confirm": _read(*JSON_FILES["confirm_trades"]),
        "live":    _read(*JSON_FILES["live_trades"]),
    }
    plan["trades_total"] = sum(len(v) for v in trades.values())
    plan["trades_by_type"] = {k: len(v) for k, v in trades.items()}

    journals = {
        "live":         _read(*JSON_FILES["live_journal"]),
        "news_history": _read(*JSON_FILES["news_history"]),
    }
    plan["journals_total"] = sum(len(v) for v in journals.values())
    plan["journals_by_type"] = {k: len(v) for k, v in journals.items()}

    return plan


def apply_migration(db_path: Path) -> dict:
    """Реально пишет в SQLite. Возвращает {table: rows_inserted}."""
    conn = open_db(db_path)
    init_schema(conn)

    inserted: dict[str, int] = {"state_kv": 0, "post_history": 0,
                                "drafts": 0, "trades": 0, "journals": 0}
    now = _now_iso()

    # state_kv
    state = _read(*JSON_FILES["state"])
    for key, value in state.items():
        conn.execute(
            "INSERT OR REPLACE INTO state_kv (key, value_json, updated_at) VALUES (?, ?, ?);",
            (key, json.dumps(value, ensure_ascii=False), now),
        )
        inserted["state_kv"] += 1

    # post_history
    for item in _read(*JSON_FILES["history"]):
        if not isinstance(item, dict):
            continue
        conn.execute(
            "INSERT INTO post_history (datetime, post_type, published_to, source, short_summary, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?);",
            (
                item.get("datetime") or now,
                item.get("post_type") or "unknown",
                item.get("published_to"),
                item.get("source"),
                item.get("short_summary"),
                json.dumps(item, ensure_ascii=False),
            ),
        )
        inserted["post_history"] += 1

    # drafts
    for draft_type, json_key in [
        ("news", "news_drafts"),
        ("author_note", "author_drafts"),
        ("weekly_diary", "weekly_drafts"),
    ]:
        for d in _read(*JSON_FILES[json_key]):
            if not isinstance(d, dict):
                continue
            did = d.get("draft_id")
            if not did:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO drafts (draft_id, draft_type, status, created_at, updated_at, payload_json) "
                "VALUES (?, ?, ?, ?, ?, ?);",
                (
                    did,
                    draft_type,
                    d.get("status") or "unknown",
                    d.get("created_at") or now,
                    d.get("updated_at"),
                    json.dumps(d, ensure_ascii=False),
                ),
            )
            inserted["drafts"] += 1

    # trades
    for trade_type, json_key in [
        ("confirm", "confirm_trades"),
        ("live", "live_trades"),
    ]:
        for t in _read(*JSON_FILES[json_key]):
            if not isinstance(t, dict):
                continue
            tid = t.get("id")
            if not tid:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO trades (trade_id, trade_type, status, symbol, created_at, updated_at, payload_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?);",
                (
                    tid,
                    trade_type,
                    t.get("status") or "unknown",
                    t.get("symbol"),
                    t.get("created_at"),
                    t.get("last_status_change_at"),
                    json.dumps(t, ensure_ascii=False),
                ),
            )
            inserted["trades"] += 1

    # journals
    for journal_type, json_key in [
        ("live_trades", "live_journal"),
        ("news_history", "news_history"),
    ]:
        for e in _read(*JSON_FILES[json_key]):
            if not isinstance(e, dict):
                continue
            conn.execute(
                "INSERT INTO journals (journal_type, event_type, logged_at, payload_json) "
                "VALUES (?, ?, ?, ?);",
                (
                    journal_type,
                    e.get("event") or e.get("decision") or "unknown",
                    e.get("logged_at") or e.get("posted_at") or now,
                    json.dumps(e, ensure_ascii=False),
                ),
            )
            inserted["journals"] += 1

    conn.commit()
    conn.close()
    return inserted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="реально пишет в SQLite (без флага — dry-run)")
    parser.add_argument("--db", default=str(ROOT / "data.sqlite"),
                        help="путь к SQLite-файлу (default: data.sqlite)")
    args = parser.parse_args()

    print("=" * 60)
    print("JSON -> SQLite migration (этап 3.4 шаг 1)")
    print("=" * 60)

    plan = collect_plan()
    print("\nPlan:")
    for k, v in plan.items():
        print(f"  {k}: {v}")

    if not args.apply:
        print("\nDRY RUN — ничего не записано.")
        print("Чтобы применить: --apply")
        print(f"Целевой файл: {args.db}")
        return 0

    db_path = Path(args.db)
    if db_path.exists():
        print(f"\nWARNING: {db_path} уже существует. INSERT OR REPLACE для kv/drafts/trades, INSERT для history/journals (могут дублироваться).")

    print(f"\nApplying migration to: {db_path}")
    inserted = apply_migration(db_path)
    print("\nInserted rows:")
    for tbl, n in inserted.items():
        print(f"  {tbl}: {n}")

    # Sanity-check
    conn = open_db(db_path)
    tables = set(list_tables(conn))
    conn.close()
    missing = EXPECTED_TABLES - tables
    if missing:
        print(f"\nERROR: missing tables: {missing}")
        return 1

    print("\nOK — schema initialized, all expected tables present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
