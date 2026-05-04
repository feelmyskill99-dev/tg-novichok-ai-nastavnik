"""TradeJournal — append-only лог торговых событий.

Пишет в trade_journal.json каждое событие: создание плана, открытие, закрытие, истечение,
результаты backtest. Используется для отчётов владельцу и для пост-анализа.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .broker import PaperTrade


class TradeJournal:
    def __init__(self, journal_path: Path):
        self.path = journal_path

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def append(self, event: dict) -> None:
        event = dict(event)
        event.setdefault("logged_at", datetime.now(tz=timezone.utc).isoformat(timespec="seconds"))
        records = self._load()
        records.append(event)
        self.path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ---------- high-level helpers ----------
    def log_plan_created(self, trade: PaperTrade) -> None:
        self.append({
            "event": "plan_created",
            "trade_id": trade.id,
            "symbol": trade.symbol,
            "direction": trade.direction,
            "entry": trade.entry,
            "stop_loss": trade.stop_loss,
            "take_profit": trade.take_profit,
            "leverage": trade.leverage,
            "risk_amount_usdt": trade.risk_amount_usdt,
            "rr": trade.rr,
            "rationale": trade.rationale,
            "created_at": trade.created_at,
        })

    def log_trade_opened(
        self,
        trade: PaperTrade,
        *,
        published_to_owner: bool = False,
        published_to_channel: bool = False,
        channel_posted_at: str | None = None,
        claude_review: dict | None = None,
    ) -> None:
        self.append({
            "event": "trade_opened",
            "trade_id": trade.id,
            "symbol": trade.symbol,
            "direction": trade.direction,
            "entry": trade.entry,
            "opened_at": trade.opened_at,
            "opened_at_bar": trade.opened_at_bar,
            "published_to_owner": published_to_owner,
            "published_to_channel": published_to_channel,
            "channel_posted_at": channel_posted_at,
            "claude_review": claude_review or {},
        })

    def find_last_closed_trade(self) -> dict | None:
        """Берёт самую свежую запись trade_closed из журнала. None — если нет."""
        records = self._load()
        for rec in reversed(records):
            if rec.get("event") == "trade_closed":
                return rec
        return None

    def log_trade_closed(
        self,
        trade: PaperTrade,
        *,
        published_to_owner: bool = False,
        published_to_channel: bool = False,
        channel_posted_at: str | None = None,
        claude_review: dict | None = None,
    ) -> None:
        self.append({
            "event": "trade_closed",
            "trade_id": trade.id,
            "symbol": trade.symbol,
            "direction": trade.direction,
            # план — нужен для последующего --publish-last-trade и аналитики
            "entry": trade.entry,
            "stop_loss": trade.stop_loss,
            "take_profit": trade.take_profit,
            "leverage": trade.leverage,
            "rr": trade.rr,
            "risk_amount_usdt": trade.risk_amount_usdt,
            "rationale": trade.rationale,
            # факт закрытия
            "close_price": trade.close_price,
            "close_reason": trade.close_reason,
            "pnl_usdt": trade.pnl_usdt,
            "r_multiple": trade.r_multiple,
            "opened_at": trade.opened_at,
            "closed_at": trade.closed_at,
            "closed_at_bar": trade.closed_at_bar,
            "status": trade.status,
            # маршрутизация
            "published_to_owner": published_to_owner,
            "published_to_channel": published_to_channel,
            "channel_posted_at": channel_posted_at,
            "claude_review": claude_review or {},
        })

    def log_setup_skipped(self, reason: str, facts: dict | None = None) -> None:
        self.append({
            "event": "setup_skipped",
            "reason": reason,
            "facts": facts or {},
        })

    def log_backtest(self, result: dict) -> None:
        self.append({"event": "backtest_summary", **result})
