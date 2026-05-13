import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.sqlite_dao import (
    SqliteDraftReader,
    SqlitePostHistoryReader,
    SqliteStateReader,
    SqliteTradeReader,
)
from core.sqlite_schema import open_db, init_schema


@pytest.fixture
def empty_db(tmp_path):
    db = tmp_path / "test.sqlite"
    conn = open_db(db)
    init_schema(conn)
    conn.close()
    return db


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
        (
            draft_id,
            draft_type,
            status,
            "2026-05-14T10:00:00+00:00",
            json.dumps(payload, ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()


def _insert_trade(db, trade_id, trade_type, status, payload):
    conn = open_db(db)
    conn.execute(
        "INSERT INTO trades (trade_id, trade_type, status, created_at, payload_json) "
        "VALUES (?, ?, ?, ?, ?);",
        (
            trade_id,
            trade_type,
            status,
            "2026-05-14T10:00:00+00:00",
            json.dumps(payload, ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# SqliteStateReader
# ---------------------------------------------------------------------------

def test_state_reader_get_with_invalid_json_returns_none(empty_db):
    _insert_state(empty_db, "key1", "not valid json{")
    reader = SqliteStateReader(empty_db)
    assert reader.get("key1") is None


def test_state_reader_get_with_unicode_value(empty_db):
    _insert_state(empty_db, "key1", '"привет"')
    reader = SqliteStateReader(empty_db)
    assert reader.get("key1") == "привет"


def test_state_reader_get_list_value(empty_db):
    _insert_state(empty_db, "key1", '[1, 2, 3]')
    reader = SqliteStateReader(empty_db)
    assert reader.get("key1") == [1, 2, 3]


def test_state_reader_get_bool_value(empty_db):
    _insert_state(empty_db, "key1", 'true')
    reader = SqliteStateReader(empty_db)
    assert reader.get("key1") is True


def test_state_reader_get_null_value(empty_db):
    _insert_state(empty_db, "key1", 'null')
    reader = SqliteStateReader(empty_db)
    assert reader.get("key1") is None


def test_state_reader_keys_returns_sorted(empty_db):
    _insert_state(empty_db, "zebra", '1')
    _insert_state(empty_db, "alpha", '2')
    _insert_state(empty_db, "mango", '3')
    reader = SqliteStateReader(empty_db)
    assert reader.keys() == ["alpha", "mango", "zebra"]


def test_state_reader_keys_empty(empty_db):
    reader = SqliteStateReader(empty_db)
    assert reader.keys() == []


# ---------------------------------------------------------------------------
# SqlitePostHistoryReader
# ---------------------------------------------------------------------------

def test_post_history_payload_handles_invalid_json(empty_db):
    conn = open_db(empty_db)
    conn.execute(
        "INSERT INTO post_history (datetime, post_type, payload_json) VALUES (?, ?, ?);",
        ("2026-05-14T00:00:00+00:00", "market", "not json"),
    )
    conn.commit()
    conn.close()
    reader = SqlitePostHistoryReader(empty_db)
    records = reader.list_recent(limit=10)
    assert len(records) == 1
    assert records[0]["payload"] == {}


def test_post_history_list_recent_zero_limit(empty_db):
    _insert_history(empty_db, "2026-05-14T00:00:00+00:00", "market", {"a": 1})
    reader = SqlitePostHistoryReader(empty_db)
    assert reader.list_recent(limit=0) == []


def test_post_history_list_recent_negative_limit(empty_db):
    _insert_history(empty_db, "2026-05-14T00:00:00+00:00", "market", {"a": 1})
    reader = SqlitePostHistoryReader(empty_db)
    # SQLite allows negative LIMIT (treated as unlimited), just check no exception
    result = reader.list_recent(limit=-1)
    assert isinstance(result, list)


def test_post_history_count_independent_of_other_tables(empty_db):
    _insert_draft(empty_db, "d1", "news", "pending_review", {"text": "hello"})
    _insert_trade(empty_db, "t1", "confirm_trade", "created", {"symbol": "BTC"})
    reader = SqlitePostHistoryReader(empty_db)
    assert reader.count() == 0


def test_post_history_list_by_type_returns_empty_for_missing_type(empty_db):
    _insert_history(empty_db, "2026-05-14T00:00:00+00:00", "market", {"a": 1})
    _insert_history(empty_db, "2026-05-14T01:00:00+00:00", "market", {"b": 2})
    _insert_history(empty_db, "2026-05-14T02:00:00+00:00", "market", {"c": 3})
    reader = SqlitePostHistoryReader(empty_db)
    assert reader.list_by_type("nonexistent") == []


# ---------------------------------------------------------------------------
# SqliteDraftReader
# ---------------------------------------------------------------------------

def test_draft_reader_get_with_invalid_payload_json(empty_db):
    conn = open_db(empty_db)
    conn.execute(
        "INSERT INTO drafts (draft_id, draft_type, status, created_at, payload_json) "
        "VALUES (?, ?, ?, ?, ?);",
        ("d1", "news", "pending_review", "2026-05-14T10:00:00+00:00", "garbage"),
    )
    conn.commit()
    conn.close()
    reader = SqliteDraftReader(empty_db)
    result = reader.get("d1")
    assert result is not None
    assert result["payload"] == {}


def test_draft_reader_list_pending_excludes_rejected(empty_db):
    _insert_draft(empty_db, "d1", "news", "pending_review", {})
    _insert_draft(empty_db, "d2", "news", "rejected", {})
    _insert_draft(empty_db, "d3", "news", "published", {})
    _insert_draft(empty_db, "d4", "news", "revised", {})
    reader = SqliteDraftReader(empty_db)
    pending = reader.list_pending()
    assert len(pending) == 2
    assert {r["draft_id"] for r in pending} == {"d1", "d4"}


def test_draft_reader_list_pending_ordering_by_created_at_desc(empty_db):
    # Insert drafts with different created_at dates
    conn = open_db(empty_db)
    conn.execute(
        "INSERT INTO drafts (draft_id, draft_type, status, created_at, payload_json) "
        "VALUES (?, ?, ?, ?, ?);",
        ("d_old", "news", "pending_review", "2026-05-01T10:00:00+00:00", "{}"),
    )
    conn.execute(
        "INSERT INTO drafts (draft_id, draft_type, status, created_at, payload_json) "
        "VALUES (?, ?, ?, ?, ?);",
        ("d_mid", "news", "pending_review", "2026-05-10T10:00:00+00:00", "{}"),
    )
    conn.execute(
        "INSERT INTO drafts (draft_id, draft_type, status, created_at, payload_json) "
        "VALUES (?, ?, ?, ?, ?);",
        ("d_new", "news", "pending_review", "2026-05-15T10:00:00+00:00", "{}"),
    )
    conn.commit()
    conn.close()
    reader = SqliteDraftReader(empty_db)
    pending = reader.list_pending()
    assert len(pending) == 3
    dates = [r["created_at"] for r in pending]
    assert dates == sorted(dates, reverse=True)


def test_draft_reader_count_zero_for_missing_type(empty_db):
    _insert_draft(empty_db, "d1", "news", "pending_review", {})
    reader = SqliteDraftReader(empty_db)
    assert reader.count(draft_type="weekly_diary") == 0


# ---------------------------------------------------------------------------
# SqliteTradeReader
# ---------------------------------------------------------------------------

def test_trade_reader_list_active_empty_when_all_terminal(empty_db):
    _insert_trade(empty_db, "t1", "confirm_trade", "closed_take_profit", {})
    _insert_trade(empty_db, "t2", "confirm_trade", "rejected", {})
    _insert_trade(empty_db, "t3", "confirm_trade", "expired_confirmation", {})
    reader = SqliteTradeReader(empty_db)
    assert reader.list_active() == []


def test_trade_reader_list_active_includes_all_non_terminal(empty_db):
    non_terminal = [
        "created", "awaiting_confirmation", "approved",
        "entry_order_submitted", "entry_filled",
        "protection_orders_submitted", "active",
    ]
    for i, status in enumerate(non_terminal):
        _insert_trade(empty_db, f"t{i}", "confirm_trade", status, {"s": status})
    reader = SqliteTradeReader(empty_db)
    active = reader.list_active()
    assert len(active) == 7
    found_statuses = {r["status"] for r in active}
    assert found_statuses == set(non_terminal)


def test_trade_reader_find_with_invalid_payload_json(empty_db):
    conn = open_db(empty_db)
    conn.execute(
        "INSERT INTO trades (trade_id, trade_type, status, created_at, payload_json) "
        "VALUES (?, ?, ?, ?, ?);",
        ("t1", "confirm_trade", "created", "2026-05-14T10:00:00+00:00", "bad"),
    )
    conn.commit()
    conn.close()
    reader = SqliteTradeReader(empty_db)
    result = reader.find("t1")
    assert result is not None
    assert result["payload"] == {}


# ---------------------------------------------------------------------------
# Cross-cutting
# ---------------------------------------------------------------------------

def test_missing_db_raises_for_all_readers(tmp_path):
    nonexistent = tmp_path / "no_such.sqlite"
    readers = [
        SqliteStateReader(nonexistent),
        SqlitePostHistoryReader(nonexistent),
        SqliteDraftReader(nonexistent),
        SqliteTradeReader(nonexistent),
    ]
    for reader in readers:
        with pytest.raises(FileNotFoundError):
            if isinstance(reader, SqliteStateReader):
                reader.keys()
            elif isinstance(reader, SqlitePostHistoryReader):
                reader.count()
            elif isinstance(reader, SqliteDraftReader):
                reader.count()
            elif isinstance(reader, SqliteTradeReader):
                reader.count()


def test_concurrent_reads_independent(empty_db):
    _insert_history(empty_db, "2026-05-14T00:00:00+00:00", "market", {"a": 1})
    reader1 = SqlitePostHistoryReader(empty_db)
    reader2 = SqlitePostHistoryReader(empty_db)
    assert reader1.count() == reader2.count()
    assert reader1.count() == 1