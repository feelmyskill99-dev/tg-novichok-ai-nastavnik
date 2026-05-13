"""SQLite schema для будущей миграции с JSON-stores (этап 3.4 шаг 1).

Этот модуль создаёт чистую базу с таблицами по плану §SQLite migration.
Реальная замена JSON произойдёт позднее — сейчас закладываем основу:
- schema совместима с существующими dataclass через `payload_json`
- bulk-импорт из JSON делается отдельным `scripts/migrate_json_to_sqlite.py`
- читать из SQLite можно прямо сейчас (для отладки), но прод-stores
  всё ещё используют JSON через `core.json_store`

API:
    conn = open_db(path)             # sqlite3.Connection с включёнными FK + WAL
    init_schema(conn)                # создаёт таблицы (idempotent)
    list_tables(conn) -> list[str]   # для smoke-проверок
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable


SCHEMA_STATEMENTS: list[str] = [
    # KV-state — заменяет state.json (один dict с произвольными ключами).
    """
    CREATE TABLE IF NOT EXISTS state_kv (
        key         TEXT PRIMARY KEY,
        value_json  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );
    """,

    # История публикаций (history.json + content_mix_log).
    """
    CREATE TABLE IF NOT EXISTS post_history (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        datetime        TEXT    NOT NULL,
        post_type       TEXT    NOT NULL,
        published_to    TEXT,
        source          TEXT,
        short_summary   TEXT,
        payload_json    TEXT    NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_post_history_datetime ON post_history(datetime);",
    "CREATE INDEX IF NOT EXISTS idx_post_history_type ON post_history(post_type);",

    # Drafts — news / author_notes / weekly_diary в одной таблице,
    # разделяются по `draft_type`.
    """
    CREATE TABLE IF NOT EXISTS drafts (
        draft_id      TEXT PRIMARY KEY,
        draft_type    TEXT NOT NULL,
        status        TEXT NOT NULL,
        created_at    TEXT NOT NULL,
        updated_at    TEXT,
        payload_json  TEXT NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_drafts_type_status ON drafts(draft_type, status);",
    "CREATE INDEX IF NOT EXISTS idx_drafts_created_at ON drafts(created_at);",

    # Trades — confirm_trades + live_trades в одной таблице.
    """
    CREATE TABLE IF NOT EXISTS trades (
        trade_id      TEXT PRIMARY KEY,
        trade_type    TEXT NOT NULL,
        status        TEXT NOT NULL,
        symbol        TEXT,
        created_at    TEXT,
        updated_at    TEXT,
        payload_json  TEXT NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_trades_type_status ON trades(trade_type, status);",

    # Append-only журнал событий (live_trade_journal, news_history).
    """
    CREATE TABLE IF NOT EXISTS journals (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        journal_type  TEXT NOT NULL,
        event_type    TEXT NOT NULL,
        logged_at     TEXT NOT NULL,
        payload_json  TEXT NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_journals_type_logged ON journals(journal_type, logged_at);",
]


EXPECTED_TABLES: frozenset[str] = frozenset({
    "state_kv", "post_history", "drafts", "trades", "journals",
})


def open_db(path: str | Path) -> sqlite3.Connection:
    """Открывает SQLite-соединение с WAL + foreign_keys."""
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Создаёт все таблицы. Idempotent (IF NOT EXISTS)."""
    for stmt in SCHEMA_STATEMENTS:
        conn.execute(stmt)
    conn.commit()


def list_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
    ).fetchall()
    return [r[0] for r in rows]
