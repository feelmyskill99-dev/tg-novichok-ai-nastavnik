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


@pytest.fixture(autouse=True)
def _isolate_json_paths(tmp_path, monkeypatch):
    paths = {}
    for key, (orig, kind) in mig.JSON_FILES.items():
        new_path = tmp_path / orig.name
        paths[key] = (new_path, kind)
    monkeypatch.setattr(mig, "JSON_FILES", paths)
    yield tmp_path


def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# collect_plan() — empty
# ---------------------------------------------------------------------------
class TestCollectPlanEmpty:
    def test_collect_plan_on_empty_dir(self):
        plan = mig.collect_plan()
        assert plan["state_kv_keys"] == 0
        assert plan["post_history_rows"] == 0
        assert plan["drafts_total"] == 0
        assert plan["trades_total"] == 0
        assert plan["journals_total"] == 0


# ---------------------------------------------------------------------------
# collect_plan() — populated
# ---------------------------------------------------------------------------
class TestCollectPlanPopulated:
    def test_collect_plan_state_kv_keys(self, _isolate_json_paths):
        _write(_isolate_json_paths / "state.json", {"a": 1, "b": 2, "c": 3})
        plan = mig.collect_plan()
        assert plan["state_kv_keys"] == 3

    def test_collect_plan_post_history_rows(self, _isolate_json_paths):
        _write(_isolate_json_paths / "history.json",
               [{"x": 1}, {"x": 2}, {"x": 3}])
        plan = mig.collect_plan()
        assert plan["post_history_rows"] == 3

    def test_collect_plan_drafts_by_type(self, _isolate_json_paths):
        _write(_isolate_json_paths / "news_drafts.json", [{}, {}, {}])
        _write(_isolate_json_paths / "author_notes_drafts.json", [{}, {}])
        _write(_isolate_json_paths / "weekly_diary_drafts.json", [])
        plan = mig.collect_plan()
        assert plan["drafts_total"] == 5
        assert plan["drafts_by_type"] == {"news": 3, "author": 2, "weekly": 0}

    def test_collect_plan_trades_by_type(self, _isolate_json_paths):
        _write(_isolate_json_paths / "confirm_trades.json", [{}, {}])
        _write(_isolate_json_paths / "live_trades.json", [{}])
        plan = mig.collect_plan()
        assert plan["trades_total"] == 3
        assert plan["trades_by_type"] == {"confirm": 2, "live": 1}

    def test_collect_plan_journals_total(self, _isolate_json_paths):
        _write(_isolate_json_paths / "live_trade_journal.json", [{}, {}, {}])
        _write(_isolate_json_paths / "news_history.json", [{}, {}])
        plan = mig.collect_plan()
        assert plan["journals_total"] == 5


# ---------------------------------------------------------------------------
# apply_migration() — empty
# ---------------------------------------------------------------------------
class TestApplyEmpty:
    def test_apply_creates_db_with_all_tables(self, _isolate_json_paths):
        db = _isolate_json_paths / "out.sqlite"
        mig.apply_migration(db)
        conn = open_db(db)
        tables = set(row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall())
        conn.close()
        assert EXPECTED_TABLES.issubset(tables)

    def test_apply_empty_inserts_zero_rows(self, _isolate_json_paths):
        db = _isolate_json_paths / "out.sqlite"
        result = mig.apply_migration(db)
        for key in ("state_kv", "post_history", "drafts", "trades", "journals"):
            assert result[key] == 0


# ---------------------------------------------------------------------------
# apply_migration() — state_kv
# ---------------------------------------------------------------------------
class TestApplyStateKv:
    def test_apply_writes_state_kv_keys(self, _isolate_json_paths):
        _write(_isolate_json_paths / "state.json",
               {"post_count": 42, "list_val": [1, 2]})
        db = _isolate_json_paths / "out.sqlite"
        mig.apply_migration(db)
        conn = open_db(db)
        rows = conn.execute("SELECT key, value_json FROM state_kv").fetchall()
        conn.close()
        assert len(rows) == 2
        vals = {row["key"]: json.loads(row["value_json"]) for row in rows}
        assert vals["post_count"] == 42
        assert vals["list_val"] == [1, 2]

    def test_apply_state_kv_replace_existing(self, _isolate_json_paths):
        _write(_isolate_json_paths / "state.json", {"a": 1, "b": 2})
        db = _isolate_json_paths / "out.sqlite"
        mig.apply_migration(db)
        mig.apply_migration(db)
        conn = open_db(db)
        count = conn.execute("SELECT COUNT(*) FROM state_kv").fetchone()[0]
        conn.close()
        assert count == 2


# ---------------------------------------------------------------------------
# apply_migration() — post_history
# ---------------------------------------------------------------------------
class TestApplyPostHistory:
    def test_apply_writes_post_history(self, _isolate_json_paths):
        data = [
            {"datetime": "2026-01-01T00:00:00+00:00", "post_type": "market",
             "published_to": "channel", "short_summary": "x"},
            {"datetime": "2026-01-02T00:00:00+00:00", "post_type": "news"},
            {"datetime": "2026-01-03T00:00:00+00:00", "post_type": "market"},
        ]
        _write(_isolate_json_paths / "history.json", data)
        db = _isolate_json_paths / "out.sqlite"
        mig.apply_migration(db)
        conn = open_db(db)
        cnt = conn.execute("SELECT COUNT(*) FROM post_history").fetchone()[0]
        types = [r[0] for r in conn.execute(
            "SELECT post_type FROM post_history"
        ).fetchall()]
        conn.close()
        assert cnt == 3
        assert types.count("market") == 2

    def test_apply_history_skips_non_dict_entries(self, _isolate_json_paths):
        data = [{"datetime": "x", "post_type": "market"}, "garbage", 42]
        _write(_isolate_json_paths / "history.json", data)
        db = _isolate_json_paths / "out.sqlite"
        mig.apply_migration(db)
        conn = open_db(db)
        cnt = conn.execute("SELECT COUNT(*) FROM post_history").fetchone()[0]
        conn.close()
        assert cnt == 1

    def test_apply_history_missing_datetime_uses_now(self, _isolate_json_paths):
        data = [{"post_type": "market"}]
        _write(_isolate_json_paths / "history.json", data)
        db = _isolate_json_paths / "out.sqlite"
        mig.apply_migration(db)
        conn = open_db(db)
        row = conn.execute("SELECT datetime FROM post_history").fetchone()
        conn.close()
        assert row and row["datetime"] != ""


# ---------------------------------------------------------------------------
# apply_migration() — drafts
# ---------------------------------------------------------------------------
class TestApplyDrafts:
    def test_apply_writes_drafts_with_type(self, _isolate_json_paths):
        data = [{
            "draft_id": "d1", "status": "pending_review",
            "created_at": "2026-05-14T10:00:00+00:00"
        }]
        _write(_isolate_json_paths / "news_drafts.json", data)
        db = _isolate_json_paths / "out.sqlite"
        mig.apply_migration(db)
        conn = open_db(db)
        row = conn.execute(
            "SELECT draft_type FROM drafts WHERE draft_id = 'd1'"
        ).fetchone()
        conn.close()
        assert row["draft_type"] == "news"

    def test_apply_drafts_skip_when_missing_id(self, _isolate_json_paths):
        data = [
            {"status": "pending_review"},
            {"draft_id": "d2", "status": "published"},
        ]
        _write(_isolate_json_paths / "news_drafts.json", data)
        db = _isolate_json_paths / "out.sqlite"
        mig.apply_migration(db)
        conn = open_db(db)
        cnt = conn.execute("SELECT COUNT(*) FROM drafts").fetchone()[0]
        conn.close()
        assert cnt == 1

    def test_apply_drafts_type_maps_correctly(self, _isolate_json_paths):
        data = [{
            "draft_id": "a1", "status": "pending_review",
            "created_at": "2026-05-14T10:00:00+00:00"
        }]
        _write(_isolate_json_paths / "author_notes_drafts.json", data)
        db = _isolate_json_paths / "out.sqlite"
        mig.apply_migration(db)
        conn = open_db(db)
        row = conn.execute(
            "SELECT draft_type FROM drafts WHERE draft_id = 'a1'"
        ).fetchone()
        conn.close()
        assert row["draft_type"] == "author_note"


# ---------------------------------------------------------------------------
# apply_migration() — trades
# ---------------------------------------------------------------------------
class TestApplyTrades:
    def test_apply_writes_trades_with_type(self, _isolate_json_paths):
        data = [{
            "id": "t1", "status": "active", "symbol": "BTC/USDT:USDT"
        }]
        _write(_isolate_json_paths / "confirm_trades.json", data)
        db = _isolate_json_paths / "out.sqlite"
        mig.apply_migration(db)
        conn = open_db(db)
        row = conn.execute(
            "SELECT trade_type, symbol FROM trades WHERE trade_id = 't1'"
        ).fetchone()
        conn.close()
        assert (row["trade_type"], row["symbol"]) == ("confirm", "BTC/USDT:USDT")

    def test_apply_trades_skip_when_missing_id(self, _isolate_json_paths):
        data = [{"status": "active"}, {"id": "t2", "status": "closed"}]
        _write(_isolate_json_paths / "confirm_trades.json", data)
        db = _isolate_json_paths / "out.sqlite"
        mig.apply_migration(db)
        conn = open_db(db)
        cnt = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        conn.close()
        assert cnt == 1


# ---------------------------------------------------------------------------
# apply_migration() — journals
# ---------------------------------------------------------------------------
class TestApplyJournals:
    def test_apply_writes_journals(self, _isolate_json_paths):
        data = [{
            "event": "entry_submitted",
            "logged_at": "2026-05-14T10:00:00+00:00"
        }]
        _write(_isolate_json_paths / "live_trade_journal.json", data)
        db = _isolate_json_paths / "out.sqlite"
        mig.apply_migration(db)
        conn = open_db(db)
        row = conn.execute(
            "SELECT journal_type, event_type FROM journals"
        ).fetchone()
        conn.close()
        assert row["journal_type"] == "live_trades"
        assert row["event_type"] == "entry_submitted"

    def test_apply_journal_fallback_event_type(self, _isolate_json_paths):
        data = [{"logged_at": "now"}]
        _write(_isolate_json_paths / "live_trade_journal.json", data)
        db = _isolate_json_paths / "out.sqlite"
        mig.apply_migration(db)
        conn = open_db(db)
        row = conn.execute(
            "SELECT event_type FROM journals"
        ).fetchone()
        conn.close()
        assert row["event_type"] == "unknown"


# ---------------------------------------------------------------------------
# Return value
# ---------------------------------------------------------------------------
class TestReturnValue:
    def test_apply_returns_inserted_counts_dict(self, _isolate_json_paths):
        _write(_isolate_json_paths / "state.json", {"k": "v"})
        db = _isolate_json_paths / "out.sqlite"
        result = mig.apply_migration(db)
        expected_keys = {"state_kv", "post_history", "drafts", "trades", "journals"}
        assert set(result.keys()) == expected_keys
        for v in result.values():
            assert isinstance(v, int)