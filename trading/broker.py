"""PaperBroker — симулятор исполнения paper-сделок.

- Никаких реальных ордеров.
- LiveBroker и ConfirmBroker — заглушки, кидают NotImplementedError.
- Логика tick():
    * pending → open, если high/low свечи коснулись entry
    * open    → closed_tp / closed_sl, если цена задела уровень
    * если в одной свече задеты оба → закрывается SL (консервативно)
    * pending истекает через `trade_setup_expires_bars` → expired
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import TradingConfig


@dataclass
class TradePlan:
    """Торговый план до открытия. Используется как DTO от SetupDetector → PaperBroker."""
    symbol: str
    direction: str
    entry: float
    stop_loss: float
    take_profit: float
    leverage: float
    position_size: float
    risk_amount_usdt: float
    rr: float
    rationale: str
    meta: dict = field(default_factory=dict)


@dataclass
class PaperTrade:
    """Paper-сделка на всём жизненном цикле.

    status:
        pending        — план создан, ждём касания entry
        open           — entry задет, позиция «открыта»
        closed_tp      — закрыта по take_profit
        closed_sl      — закрыта по stop_loss
        expired        — план протух за N свечей, не открылся
        closed_manual  — закрыта вручную
    """
    id: str
    symbol: str
    direction: str
    entry: float
    stop_loss: float
    take_profit: float
    leverage: float
    position_size: float
    risk_amount_usdt: float
    rr: float
    status: str
    created_at: str
    created_at_bar: int
    opened_at: Optional[str] = None
    opened_at_bar: Optional[int] = None
    closed_at: Optional[str] = None
    closed_at_bar: Optional[int] = None
    close_reason: Optional[str] = None
    close_price: Optional[float] = None
    pnl_usdt: Optional[float] = None
    r_multiple: Optional[float] = None
    rationale: str = ""
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PaperTrade":
        allowed = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in allowed})


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


class PaperBroker:
    """Симулятор. Хранит состояние в paper_trades.json.

    В реальном (forward) режиме:
        - create_plan() — сразу создаёт trade c status=pending
        - open_trade() — сразу после создания плана (entry = текущая цена)
    В backtest режиме:
        - create_plan() — status=pending
        - tick() — продвигает план по историческим свечам
    """

    def __init__(self, config: TradingConfig, trades_path: Path):
        self.cfg = config
        self.trades_path = trades_path

    # ---------- persistence ----------
    def load_open_trades(self) -> list[PaperTrade]:
        if not self.trades_path.exists():
            return []
        try:
            raw = json.loads(self.trades_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(raw, list):
            return []
        out: list[PaperTrade] = []
        for item in raw:
            try:
                out.append(PaperTrade.from_dict(item))
            except Exception:
                continue
        return out

    def save_open_trades(self, trades: list[PaperTrade]) -> None:
        data = [t.to_dict() for t in trades]
        self.trades_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def active_trades(self) -> list[PaperTrade]:
        """pending + open — те, которые ещё не завершены."""
        return [t for t in self.load_open_trades() if t.status in ("pending", "open")]

    # ---------- lifecycle ----------
    def create_plan(
        self,
        plan: TradePlan,
        *,
        bar_index: int,
        now: Optional[datetime] = None,
    ) -> PaperTrade:
        ts = (now.astimezone(timezone.utc) if now else datetime.now(tz=timezone.utc)).isoformat(timespec="seconds")
        trade = PaperTrade(
            id=uuid.uuid4().hex[:12],
            symbol=plan.symbol,
            direction=plan.direction,
            entry=plan.entry,
            stop_loss=plan.stop_loss,
            take_profit=plan.take_profit,
            leverage=plan.leverage,
            position_size=plan.position_size,
            risk_amount_usdt=plan.risk_amount_usdt,
            rr=plan.rr,
            status="pending",
            created_at=ts,
            created_at_bar=bar_index,
            rationale=plan.rationale,
            meta=dict(plan.meta or {}),
        )
        return trade

    def open_trade(
        self,
        trade: PaperTrade,
        *,
        open_price: Optional[float] = None,
        bar_index: Optional[int] = None,
        now: Optional[datetime] = None,
    ) -> None:
        if trade.status != "pending":
            return
        ts = (now.astimezone(timezone.utc) if now else datetime.now(tz=timezone.utc)).isoformat(timespec="seconds")
        trade.status = "open"
        trade.opened_at = ts
        trade.opened_at_bar = bar_index if bar_index is not None else trade.created_at_bar
        # Entry оставляем тем, что был в плане — это и есть предполагаемая цена исполнения.
        # open_price сохраняем в meta для честности, если отличается.
        if open_price is not None and abs(open_price - trade.entry) > 1e-9:
            trade.meta["actual_open_price"] = open_price

    def close_trade(
        self,
        trade: PaperTrade,
        *,
        reason: str,
        close_price: float,
        bar_index: Optional[int] = None,
        now: Optional[datetime] = None,
    ) -> None:
        if trade.status not in ("open", "pending"):
            return
        ts = (now.astimezone(timezone.utc) if now else datetime.now(tz=timezone.utc)).isoformat(timespec="seconds")
        trade.status = "expired" if reason == "expired" else f"closed_{reason}"
        trade.closed_at = ts
        trade.closed_at_bar = bar_index
        trade.close_reason = reason
        trade.close_price = close_price

        # PnL и R рассчитываем только если сделка реально открывалась.
        if trade.opened_at is not None and trade.status.startswith("closed"):
            if trade.direction == "long":
                pnl = (close_price - trade.entry) * trade.position_size
            else:  # short
                pnl = (trade.entry - close_price) * trade.position_size
            trade.pnl_usdt = pnl
            if trade.risk_amount_usdt > 0:
                trade.r_multiple = pnl / trade.risk_amount_usdt
        else:
            trade.pnl_usdt = 0.0
            trade.r_multiple = 0.0

    # ---------- simulation ----------
    def tick(
        self,
        trade: PaperTrade,
        *,
        bar_index: int,
        open_: float,
        high: float,
        low: float,
        close: float,
        ts: Optional[datetime] = None,
    ) -> Optional[str]:
        """Продвигает сделку по одной OHLC-свече.

        Возвращает событие: 'opened' | 'closed_tp' | 'closed_sl' | 'expired' | None.
        Если в одной свече задеты и TP, и SL — закрываем по SL (консервативно).
        """
        if trade.status not in ("pending", "open"):
            return None

        # 1. pending: проверяем касание entry
        if trade.status == "pending":
            age = bar_index - trade.created_at_bar
            # сначала — exp check (если в текущую свечу уже истёк срок, и не коснулись)
            touched = (low <= trade.entry <= high)
            if touched:
                self.open_trade(trade, open_price=trade.entry, bar_index=bar_index, now=ts)
                # продолжим, чтобы в этой же свече попробовать закрыть по TP/SL
            elif age >= self.cfg.trade_setup_expires_bars:
                self.close_trade(trade, reason="expired", close_price=close, bar_index=bar_index, now=ts)
                return "expired"
            else:
                return None

        # 2. open: проверяем TP/SL
        if trade.status == "open":
            if trade.direction == "long":
                sl_hit = low <= trade.stop_loss
                tp_hit = high >= trade.take_profit
            else:  # short
                sl_hit = high >= trade.stop_loss
                tp_hit = low <= trade.take_profit

            # оба в одной свече → SL (консервативно)
            if sl_hit and tp_hit:
                self.close_trade(trade, reason="sl", close_price=trade.stop_loss,
                                 bar_index=bar_index, now=ts)
                return "closed_sl"
            if sl_hit:
                self.close_trade(trade, reason="sl", close_price=trade.stop_loss,
                                 bar_index=bar_index, now=ts)
                return "closed_sl"
            if tp_hit:
                self.close_trade(trade, reason="tp", close_price=trade.take_profit,
                                 bar_index=bar_index, now=ts)
                return "closed_tp"
            return "opened" if trade.opened_at_bar == bar_index else None

        return None


# =============================================================================
# Заглушки для confirm/live — реализованы в будущих итерациях.
# =============================================================================

class LiveBroker:
    """LiveBroker — НЕ реализован в этом PR.

    Stage 8a поддерживает только confirm-mode (с ручным подтверждением каждой сделки).
    Полностью автоматический live будет включён в Stage 8b — после серии успешных
    confirm-сделок и явного CONFIRM_MODE_PROVEN=true.
    """

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "LiveBroker is disabled. Use confirm mode first: TRADING_MODE=confirm + "
            "CONFIRM_TRADING_ENABLED=true."
        )


# Старая заглушка ConfirmBroker (Stage 5) удалена. Реальный ConfirmBroker —
# в trading/confirm_broker.py.
