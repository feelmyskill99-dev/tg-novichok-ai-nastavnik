"""Tests for core/sqlite_dao.py — read-only DAO поверх data.sqlite."""
from __future__ import annotations

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
from core.sqlite_schema import init_schema, open_db


@pytest.fixture
def empty_db(tmp_path: Path) -> Path:
    """Свежая инициализированная база без данных."""
    db = tmp_path / "test.sqlite"
    conn = open_db(db)
    init_schema(conn)
    conn.close()
    return db


@pytest.fixture
def populated_db(tmp_path: Path) -> Path:
    """База с тестовыми данными во всех таблицах."""
    db = tmp_path / "populated.sqlite"
    conn = open_db(db)
    init_schema(conn)

    # state_kv
    for k, v in [("post_count", 42), ("last_image_at", 5)]:
        conn.execute(
            "INSERT INTO state_kv (key, value_json, updated_at) VALUES (?, ?, ?);",
            (k, json.dumps(v), "2026-05-14T00:00:00+00:00"),
        )

    # post_history (3 записи разных типов)
    for i, ptype in enumerate(["market", "news", "market"]):
        conn.execute(
            "INSERT INTO post_history (datetime, post_type, payload_json) VALUES (?, ?, ?);",
            (f"2026-05-14T0{i}:00:00+00:00", ptype, json.dumps({"i": i, "type": ptype})),
        )

    # drafts (3 news, 2 author_note, разные статусы)
    drafts_data = [
        ("d1", "news", "pending_review"),
        ("d2", "news", "published"),
        ("d3", "news", "revised"),
        ("a1", "author_note", "pending_review"),
        ("a2", "author_note", "rejected"),
    ]
    for did, dtype, status in drafts_data:
        conn.execute(
            "INSERT INTO drafts (draft_id, draft_type, status, created_at, payload_json) "
            "VALUES (?, ?, ?, ?, ?);",
            (did, dtype, status, "2026-05-14T00:00:00+00:00",
             json.dumps({"draft_id": did, "title": f"Draft {did}"})),
        )

    # trades (1 active, 1 closed)
    trades_data = [
        ("t1", "confirm", "active", "BTC/USDT:USDT"),
        ("t2", "confirm", "closed_take_profit", "BTC/USDT:USDT"),
        ("t3", "live", "awaiting_confirmation", "ETH/USDT:USDT"),
    ]
    for tid, ttype, status, symbol in trades_data:
        conn.execute(
            "INSERT INTO trades (trade_id, trade_type, status, symbol, created_at, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?);",
            (tid, ttype, status, symbol, "2026-05-14T00:00:00+00:00",
             json.dumps({"id": tid, "status": status})),
        )

    conn.commit()
    conn.close()
    return db


# ---------- SqlitePostHistoryReader ----------


def test_post_history_count_on_empty(empty_db: Path):
    reader = SqlitePostHistoryReader(empty_db)
    assert reader.count() == 0


def test_post_history_count_populated(populated_db: Path):
    reader = SqlitePostHistoryReader(populated_db)
    assert reader.count() == 3


def test_post_history_list_recent_returns_newest_first(populated_db: Path):
    reader = SqlitePostHistoryReader(populated_db)
    rows = reader.list_recent(limit=10)
    assert len(rows) == 3
    # Order by id DESC → последняя вставленная сверху
    assert rows[0]["id"] > rows[1]["id"] > rows[2]["id"]


def test_post_history_list_recent_limit(populated_db: Path):
    reader = SqlitePostHistoryReader(populated_db)
    assert len(reader.list_recent(limit=2)) == 2


def test_post_history_list_by_type(populated_db: Path):
    reader = SqlitePostHistoryReader(populated_db)
    market = reader.list_by_type("market")
    news = reader.list_by_type("news")
    assert len(market) == 2
    assert len(news) == 1
    assert all(r["post_type"] == "market" for r in market)


def test_post_history_payload_parsed(populated_db: Path):
    reader = SqlitePostHistoryReader(populated_db)
    rows = reader.list_recent(limit=1)
    assert "payload" in rows[0]
    assert isinstance(rows[0]["payload"], dict)
    assert "i" in rows[0]["payload"]


def test_missing_db_raises(tmp_path: Path):
    reader = SqlitePostHistoryReader(tmp_path / "absent.sqlite")
    with pytest.raises(FileNotFoundError):
        reader.count()


# ---------- SqliteDraftReader ----------


def test_draft_reader_count_all(populated_db: Path):
    reader = SqliteDraftReader(populated_db)
    assert reader.count() == 5


def test_draft_reader_count_by_type(populated_db: Path):
    reader = SqliteDraftReader(populated_db)
    assert reader.count(draft_type="news") == 3
    assert reader.count(draft_type="author_note") == 2
    assert reader.count(draft_type="weekly_diary") == 0


def test_draft_reader_get_existing(populated_db: Path):
    reader = SqliteDraftReader(populated_db)
    draft = reader.get("d1")
    assert draft is not None
    assert draft["draft_id"] == "d1"
    assert draft["draft_type"] == "news"
    assert draft["status"] == "pending_review"
    assert draft["payload"]["title"] == "Draft d1"


def test_draft_reader_get_missing_returns_none(populated_db: Path):
    reader = SqliteDraftReader(populated_db)
    assert reader.get("does_not_exist") is None


def test_draft_reader_list_pending_all_types(populated_db: Path):
    reader = SqliteDraftReader(populated_db)
    pending = reader.list_pending()
    # d1 (pending_review), d3 (revised), a1 (pending_review) = 3
    assert len(pending) == 3
    ids = {d["draft_id"] for d in pending}
    assert ids == {"d1", "d3", "a1"}


def test_draft_reader_list_pending_filtered_by_type(populated_db: Path):
    reader = SqliteDraftReader(populated_db)
    news_pending = reader.list_pending(draft_type="news")
    assert len(news_pending) == 2
    assert {d["draft_id"] for d in news_pending} == {"d1", "d3"}


# ---------- SqliteTradeReader ----------


def test_trade_reader_count_all(populated_db: Path):
    reader = SqliteTradeReader(populated_db)
    assert reader.count() == 3


def test_trade_reader_count_by_type(populated_db: Path):
    reader = SqliteTradeReader(populated_db)
    assert reader.count(trade_type="confirm") == 2
    assert reader.count(trade_type="live") == 1


def test_trade_reader_find_existing(populated_db: Path):
    reader = SqliteTradeReader(populated_db)
    trade = reader.find("t1")
    assert trade is not None
    assert trade["status"] == "active"
    assert trade["symbol"] == "BTC/USDT:USDT"


def test_trade_reader_find_missing(populated_db: Path):
    reader = SqliteTradeReader(populated_db)
    assert reader.find("missing") is None


def test_trade_reader_list_active_excludes_closed(populated_db: Path):
    reader = SqliteTradeReader(populated_db)
    active = reader.list_active()
    # t1 (active), t3 (awaiting_confirmation) — оба non-terminal
    # t2 (closed_take_profit) — terminal, исключаем
    assert len(active) == 2
    ids = {t["trade_id"] for t in active}
    assert ids == {"t1", "t3"}


def test_trade_reader_list_active_filtered_by_type(populated_db: Path):
    reader = SqliteTradeReader(populated_db)
    confirm_active = reader.list_active(trade_type="confirm")
    assert len(confirm_active) == 1
    assert confirm_active[0]["trade_id"] == "t1"


# ---------- SqliteStateReader ----------


def test_state_reader_get_existing(populated_db: Path):
    reader = SqliteStateReader(populated_db)
    assert reader.get("post_count") == 42
    assert reader.get("last_image_at") == 5


def test_state_reader_get_missing_returns_none(populated_db: Path):
    reader = SqliteStateReader(populated_db)
    assert reader.get("nonexistent_key") is None


def test_state_reader_keys(populated_db: Path):
    reader = SqliteStateReader(populated_db)
    keys = reader.keys()
    assert set(keys) == {"post_count", "last_image_at"}


def test_state_reader_handles_complex_json(empty_db: Path):
    """Сохраняем complex value (list, nested dict) — читаем обратно."""
    conn = open_db(empty_db)
    complex_val = {"nested": {"a": [1, 2, 3]}, "tags": ["x", "y"]}
    conn.execute(
        "INSERT INTO state_kv (key, value_json, updated_at) VALUES (?, ?, ?);",
        ("complex", json.dumps(complex_val), "2026-05-14T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    reader = SqliteStateReader(empty_db)
    assert reader.get("complex") == complex_val
