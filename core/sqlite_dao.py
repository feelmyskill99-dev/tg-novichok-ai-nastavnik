"""SQLite Data Access Objects (этап 3.4 шаг 2 — read-only proof-of-concept).

Реальные stores (JSON) остаются основными — это лишь read-side для
data.sqlite после миграции через `scripts/migrate_json_to_sqlite.py`.

Использование:
    from core.sqlite_dao import SqlitePostHistoryReader, SqliteDraftReader
    reader = SqlitePostHistoryReader(db_path)
    recent = reader.list_recent(limit=20)

Эти классы НЕ реализуют полный Protocol (Reader без save/update). Когда
JSON будет заменён — добавим write-side и реализуем DraftStore/TradeStore
Protocol полностью.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from .sqlite_schema import open_db


class _BaseReader:
    """Общая инфраструктура: open/close, чтение из sqlite3.Row."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def _conn(self) -> sqlite3.Connection:
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"SQLite db not found at {self.db_path}. "
                f"Запустите scripts/migrate_json_to_sqlite.py --apply."
            )
        return open_db(self.db_path)


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def _parse_payload(row: sqlite3.Row) -> dict[str, Any]:
    """Восстанавливает payload_json в dict."""
    raw = row["payload_json"]
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------------------
# Post history
# ---------------------------------------------------------------------------

class SqlitePostHistoryReader(_BaseReader):
    """Read-only доступ к таблице post_history."""

    def count(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM post_history;").fetchone()
            return int(row["n"])

    def list_recent(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """Последние N записей, новые сверху. payload_json распакован."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM post_history ORDER BY id DESC LIMIT ?;", (limit,),
            ).fetchall()
            return [_row_to_dict(r) | {"payload": _parse_payload(r)} for r in rows]

    def list_by_type(self, post_type: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM post_history WHERE post_type = ? ORDER BY id DESC LIMIT ?;",
                (post_type, limit),
            ).fetchall()
            return [_row_to_dict(r) | {"payload": _parse_payload(r)} for r in rows]


# ---------------------------------------------------------------------------
# Drafts (read-only)
# ---------------------------------------------------------------------------

class SqliteDraftReader(_BaseReader):
    """Read-only доступ к таблице drafts. Полный DraftStore-write-side
    реализуем когда JSON будет заменён."""

    def count(self, *, draft_type: Optional[str] = None) -> int:
        with self._conn() as conn:
            if draft_type:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM drafts WHERE draft_type = ?;",
                    (draft_type,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS n FROM drafts;").fetchone()
            return int(row["n"])

    def get(self, draft_id: str) -> Optional[dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM drafts WHERE draft_id = ?;", (draft_id,),
            ).fetchone()
            if row is None:
                return None
            return _row_to_dict(row) | {"payload": _parse_payload(row)}

    def list_pending(self, *, draft_type: Optional[str] = None) -> list[dict[str, Any]]:
        """status in (pending_review, revised). Фильтр по типу опционален."""
        with self._conn() as conn:
            if draft_type:
                rows = conn.execute(
                    "SELECT * FROM drafts WHERE draft_type = ? AND status IN ('pending_review', 'revised') "
                    "ORDER BY created_at DESC;",
                    (draft_type,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM drafts WHERE status IN ('pending_review', 'revised') "
                    "ORDER BY created_at DESC;",
                ).fetchall()
            return [_row_to_dict(r) | {"payload": _parse_payload(r)} for r in rows]


# ---------------------------------------------------------------------------
# Trades (read-only)
# ---------------------------------------------------------------------------

class SqliteTradeReader(_BaseReader):
    """Read-only доступ к таблице trades."""

    NON_TERMINAL = (
        "created", "awaiting_confirmation", "approved",
        "entry_order_submitted", "entry_filled",
        "protection_orders_submitted", "active",
    )

    def count(self, *, trade_type: Optional[str] = None) -> int:
        with self._conn() as conn:
            if trade_type:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM trades WHERE trade_type = ?;",
                    (trade_type,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS n FROM trades;").fetchone()
            return int(row["n"])

    def find(self, trade_id: str) -> Optional[dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM trades WHERE trade_id = ?;", (trade_id,),
            ).fetchone()
            if row is None:
                return None
            return _row_to_dict(row) | {"payload": _parse_payload(row)}

    def list_active(self, *, trade_type: Optional[str] = None) -> list[dict[str, Any]]:
        placeholders = ",".join("?" * len(self.NON_TERMINAL))
        with self._conn() as conn:
            if trade_type:
                rows = conn.execute(
                    f"SELECT * FROM trades WHERE trade_type = ? AND status IN ({placeholders}) "
                    f"ORDER BY created_at DESC;",
                    (trade_type, *self.NON_TERMINAL),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT * FROM trades WHERE status IN ({placeholders}) "
                    f"ORDER BY created_at DESC;",
                    self.NON_TERMINAL,
                ).fetchall()
            return [_row_to_dict(r) | {"payload": _parse_payload(r)} for r in rows]


# ---------------------------------------------------------------------------
# State KV (read-only)
# ---------------------------------------------------------------------------

class SqliteStateReader(_BaseReader):
    """Read-only доступ к state_kv (бывший state.json)."""

    def get(self, key: str) -> Any:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value_json FROM state_kv WHERE key = ?;", (key,),
            ).fetchone()
            if row is None:
                return None
            try:
                return json.loads(row["value_json"])
            except json.JSONDecodeError:
                return None

    def keys(self) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute("SELECT key FROM state_kv ORDER BY key;").fetchall()
            return [r["key"] for r in rows]
