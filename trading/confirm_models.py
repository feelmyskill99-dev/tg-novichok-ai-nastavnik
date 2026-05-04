"""ConfirmTrade — модель сделки confirm-режима.

Не путать с PaperTrade: у confirm-сделки своя машина состояний и реальные orderId
от биржи. Файлы тоже отдельные: confirm_trades.json + live_trades.json + live_trade_journal.json.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path


# =============================================================================
# Состояния (см. ТЗ Stage 8a §6)
# =============================================================================

STATUS_CREATED                       = "created"
STATUS_AWAITING_CONFIRMATION         = "awaiting_confirmation"
STATUS_REJECTED                      = "rejected"
STATUS_EXPIRED_CONFIRMATION          = "expired_confirmation"
STATUS_APPROVED                      = "approved"
STATUS_ENTRY_ORDER_SUBMITTED         = "entry_order_submitted"
STATUS_ENTRY_FILLED                  = "entry_filled"
STATUS_PROTECTION_ORDERS_SUBMITTED   = "protection_orders_submitted"
STATUS_ACTIVE                        = "active"
STATUS_CLOSED_TAKE_PROFIT            = "closed_take_profit"
STATUS_CLOSED_STOP_LOSS              = "closed_stop_loss"
STATUS_CLOSED_MANUAL                 = "closed_manual"
STATUS_CLOSED_ERROR                  = "closed_error"
STATUS_CANCELLED                     = "cancelled"
STATUS_FAILED                        = "failed"
STATUS_MANUAL_INTERVENTION           = "manual_intervention_detected"

# не-конечные статусы (ещё нужно что-то делать)
NON_TERMINAL = {
    STATUS_CREATED,
    STATUS_AWAITING_CONFIRMATION,
    STATUS_APPROVED,
    STATUS_ENTRY_ORDER_SUBMITTED,
    STATUS_ENTRY_FILLED,
    STATUS_PROTECTION_ORDERS_SUBMITTED,
    STATUS_ACTIVE,
}

TERMINAL = {
    STATUS_REJECTED,
    STATUS_EXPIRED_CONFIRMATION,
    STATUS_CLOSED_TAKE_PROFIT,
    STATUS_CLOSED_STOP_LOSS,
    STATUS_CLOSED_MANUAL,
    STATUS_CLOSED_ERROR,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_MANUAL_INTERVENTION,
}


# =============================================================================
# Модель
# =============================================================================

def _new_id() -> str:
    """Короткий, безопасный для CallbackData id (Telegram ограничивает 64 байта)."""
    return uuid.uuid4().hex[:12]


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


@dataclass
class ConfirmTrade:
    # --- идентификация и план ---
    id: str
    symbol: str
    direction: str                  # long | short
    entry: float
    stop_loss: float
    take_profit: float
    leverage: float
    margin_mode: str                # isolated only
    position_size: float
    notional_usdt: float
    risk_amount_usdt: float
    rr: float
    rationale: str

    # --- состояние ---
    status: str = STATUS_CREATED
    created_at: str = field(default_factory=_now_iso)
    awaiting_since: str | None = None
    decided_at: str | None = None
    submitted_at: str | None = None
    filled_at: str | None = None
    closed_at: str | None = None
    last_status_change_at: str = field(default_factory=_now_iso)

    # --- exchange artifacts ---
    entry_order_id: str | None = None
    sl_order_id: str | None = None
    tp_order_id: str | None = None
    fill_price: float | None = None
    close_price: float | None = None
    close_reason: str | None = None
    realized_pnl_usdt: float | None = None

    # --- маршрутизация и UI ---
    confirm_message_id: int | None = None
    safety_summary: dict = field(default_factory=dict)
    error_message: str | None = None
    notes: list[str] = field(default_factory=list)

    @classmethod
    def new(
        cls,
        *,
        symbol: str,
        direction: str,
        entry: float,
        stop_loss: float,
        take_profit: float,
        leverage: float,
        position_size: float,
        notional_usdt: float,
        risk_amount_usdt: float,
        rr: float,
        rationale: str,
        margin_mode: str = "isolated",
        safety_summary: dict | None = None,
    ) -> "ConfirmTrade":
        return cls(
            id=_new_id(),
            symbol=symbol,
            direction=direction,
            entry=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            leverage=leverage,
            margin_mode=margin_mode,
            position_size=position_size,
            notional_usdt=notional_usdt,
            risk_amount_usdt=risk_amount_usdt,
            rr=rr,
            rationale=rationale,
            safety_summary=safety_summary or {},
        )

    def transition(self, new_status: str, *, note: str = "") -> None:
        self.status = new_status
        self.last_status_change_at = _now_iso()
        if note:
            self.notes.append(f"{self.last_status_change_at} {new_status}: {note}")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ConfirmTrade":
        allowed = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in allowed})


# =============================================================================
# Хранилища
# =============================================================================

class ConfirmTradesStore:
    """Хранит все non-terminal confirm-сделки в confirm_trades.json.

    Terminal-сделки (rejected/expired/cancelled/failed) тоже хранятся — для аудита,
    но удаляются при превышении ROLLING_CAP.
    """
    ROLLING_CAP = 200

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> list[ConfirmTrade]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return [ConfirmTrade.from_dict(d) for d in raw if isinstance(d, dict)]
        except Exception:
            return []

    def save(self, trades: list[ConfirmTrade]) -> None:
        # сначала non-terminal, потом terminal — так удобнее читать глазами
        non_term = [t for t in trades if t.status in NON_TERMINAL]
        term = [t for t in trades if t.status in TERMINAL]
        keep = non_term + term[-self.ROLLING_CAP:]
        self.path.write_text(
            json.dumps([t.to_dict() for t in keep], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def upsert(self, trade: ConfirmTrade) -> None:
        items = self.load()
        replaced = False
        for i, t in enumerate(items):
            if t.id == trade.id:
                items[i] = trade
                replaced = True
                break
        if not replaced:
            items.append(trade)
        self.save(items)

    def find(self, trade_id: str) -> ConfirmTrade | None:
        for t in self.load():
            if t.id == trade_id:
                return t
        return None

    def pending(self) -> list[ConfirmTrade]:
        return [t for t in self.load() if t.status == STATUS_AWAITING_CONFIRMATION]

    def active_or_pending_live(self) -> list[ConfirmTrade]:
        """То, что уже на бирже либо вот-вот туда попадёт."""
        statuses = {
            STATUS_APPROVED,
            STATUS_ENTRY_ORDER_SUBMITTED,
            STATUS_ENTRY_FILLED,
            STATUS_PROTECTION_ORDERS_SUBMITTED,
            STATUS_ACTIVE,
        }
        return [t for t in self.load() if t.status in statuses]


class LiveTradesStore(ConfirmTradesStore):
    """Активные/недавно закрытые real-trades. Та же сериализация, отдельный файл."""
    pass


class LiveTradeJournal:
    """Append-only лог реальных закрытий. Финансовая трассировка."""
    def __init__(self, path: Path):
        self.path = path

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
        event.setdefault("logged_at", _now_iso())
        records = self._load()
        records.append(event)
        self.path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def log_trade_event(self, trade: ConfirmTrade, event_type: str, extra: dict | None = None) -> None:
        payload = {
            "event": event_type,
            "trade_id": trade.id,
            "symbol": trade.symbol,
            "direction": trade.direction,
            "status": trade.status,
            "entry": trade.entry,
            "stop_loss": trade.stop_loss,
            "take_profit": trade.take_profit,
            "leverage": trade.leverage,
            "margin_mode": trade.margin_mode,
            "position_size": trade.position_size,
            "notional_usdt": trade.notional_usdt,
            "risk_amount_usdt": trade.risk_amount_usdt,
            "rr": trade.rr,
            "fill_price": trade.fill_price,
            "close_price": trade.close_price,
            "close_reason": trade.close_reason,
            "realized_pnl_usdt": trade.realized_pnl_usdt,
            "entry_order_id": trade.entry_order_id,
            "sl_order_id": trade.sl_order_id,
            "tp_order_id": trade.tp_order_id,
        }
        if extra:
            payload.update(extra)
        self.append(payload)


def today_realized_pnl_usdt(journal: LiveTradeJournal) -> float:
    """Сумма realized_pnl_usdt из событий ‘trade_closed’ за сегодня (UTC).

    Используется для проверки MAX_LIVE_DAILY_LOSS_USDT.
    """
    today = datetime.now(tz=timezone.utc).date().isoformat()
    total = 0.0
    for rec in journal._load():
        if rec.get("event") not in ("trade_closed", "live_trade_closed"):
            continue
        ts = rec.get("logged_at", "")
        if not ts.startswith(today):
            continue
        v = rec.get("realized_pnl_usdt")
        if v is not None:
            try:
                total += float(v)
            except (TypeError, ValueError):
                pass
    return total
