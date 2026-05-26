"""Tests for core/sqlite_schema.py — schema init + smoke."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.sqlite_schema import (
    EXPECTED_TABLES,
    SCHEMA_STATEMENTS,
    init_schema,
    list_tables,
    open_db,
)


def test_open_db_creates_file(tmp_path: Path):
    db = tmp_path / "test.sqlite"
    assert not db.exists()

    conn = open_db(db)

    assert db.exists()
    conn.close()


def test_open_db_enables_wal(tmp_path: Path):
    conn = open_db(tmp_path / "wal.sqlite")
    mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]

    assert mode == "wal"
    conn.close()


def test_open_db_returns_row_factory(tmp_path: Path):
    conn = open_db(tmp_path / "rf.sqlite")

    assert conn.row_factory is sqlite3.Row
    conn.close()


def test_init_schema_creates_all_expected_tables(tmp_path: Path):
    conn = open_db(tmp_path / "schema.sqlite")
    init_schema(conn)

    tables = set(list_tables(conn))

    assert EXPECTED_TABLES.issubset(tables)
    conn.close()


def test_init_schema_is_idempotent(tmp_path: Path):
    """Повторный init не должен падать (IF NOT EXISTS)."""
    conn = open_db(tmp_path / "idem.sqlite")
    init_schema(conn)
    init_schema(conn)
    init_schema(conn)

    tables = list_tables(conn)
    assert len(set(tables)) >= len(EXPECTED_TABLES)
    conn.close()


def test_state_kv_primary_key_uniqueness(tmp_path: Path):
    conn = open_db(tmp_path / "kv.sqlite")
    init_schema(conn)

    conn.execute(
        "INSERT INTO state_kv (key, value_json, updated_at) VALUES (?, ?, ?);",
        ("post_count", "1", "2026-05-14T00:00:00+00:00"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO state_kv (key, value_json, updated_at) VALUES (?, ?, ?);",
            ("post_count", "2", "2026-05-14T00:01:00+00:00"),
        )
    conn.close()


def test_state_kv_insert_or_replace(tmp_path: Path):
    """INSERT OR REPLACE используется в migration script."""
    conn = open_db(tmp_path / "kv2.sqlite")
    init_schema(conn)

    conn.execute(
        "INSERT OR REPLACE INTO state_kv (key, value_json, updated_at) VALUES (?, ?, ?);",
        ("post_count", "1", "2026-05-14T00:00:00+00:00"),
    )
    conn.execute(
        "INSERT OR REPLACE INTO state_kv (key, value_json, updated_at) VALUES (?, ?, ?);",
        ("post_count", "2", "2026-05-14T00:01:00+00:00"),
    )
    row = conn.execute(
        "SELECT value_json FROM state_kv WHERE key = 'post_count';"
    ).fetchone()

    assert row["value_json"] == "2"
    conn.close()


def test_post_history_autoincrement(tmp_path: Path):
    conn = open_db(tmp_path / "ph.sqlite")
    init_schema(conn)

    for i in range(3):
        conn.execute(
            "INSERT INTO post_history (datetime, post_type, payload_json) VALUES (?, ?, ?);",
            (f"2026-05-14T0{i}:00:00+00:00", "market", json.dumps({"i": i})),
        )
    rows = conn.execute("SELECT id FROM post_history ORDER BY id;").fetchall()
    assert [r["id"] for r in rows] == [1, 2, 3]
    conn.close()


def test_drafts_pk_is_draft_id(tmp_path: Path):
    conn = open_db(tmp_path / "dr.sqlite")
    init_schema(conn)

    conn.execute(
        "INSERT INTO drafts (draft_id, draft_type, status, created_at, payload_json) "
        "VALUES (?, ?, ?, ?, ?);",
        ("d1", "news", "pending_review", "2026-05-14T00:00:00+00:00", "{}"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO drafts (draft_id, draft_type, status, created_at, payload_json) "
            "VALUES (?, ?, ?, ?, ?);",
            ("d1", "author_note", "pending_review", "2026-05-14T00:01:00+00:00", "{}"),
        )
    conn.close()


def test_indexes_exist(tmp_path: Path):
    """Создаются ли индексы, нужные для прод-нагрузки."""
    conn = open_db(tmp_path / "idx.sqlite")
    init_schema(conn)

    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%';"
    ).fetchall()
    index_names = {r["name"] for r in rows}

    expected = {
        "idx_post_history_datetime",
        "idx_post_history_type",
        "idx_drafts_type_status",
        "idx_drafts_created_at",
        "idx_trades_type_status",
        "idx_journals_type_logged",
    }
    assert expected.issubset(index_names)
    conn.close()


def test_schema_statements_are_non_empty():
    assert len(SCHEMA_STATEMENTS) > 0
    for stmt in SCHEMA_STATEMENTS:
        assert isinstance(stmt, str)
        assert stmt.strip()


def test_journals_payload_preserved_as_json(tmp_path: Path):
    conn = open_db(tmp_path / "j.sqlite")
    init_schema(conn)

    payload = {"event": "test", "extra": {"nested": [1, 2, 3]}}
    conn.execute(
        "INSERT INTO journals (journal_type, event_type, logged_at, payload_json) "
        "VALUES (?, ?, ?, ?);",
        ("live_trades", "entry_submitted", "2026-05-14T00:00:00+00:00",
         json.dumps(payload, ensure_ascii=False)),
    )
    row = conn.execute(
        "SELECT payload_json FROM journals WHERE journal_type='live_trades';"
    ).fetchone()
    restored = json.loads(row["payload_json"])
    assert restored == payload
    conn.close()
