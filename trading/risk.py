"""RiskChecker — валидация торгового плана перед открытием paper-сделки.

Никакой реальной торговли не ведёт. Только проверяет, что план не нарушает консервативные правила.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .config import TradingConfig


# Дистанция стопа от цены в процентах. Жёстко консервативно.
MIN_STOP_DISTANCE_PCT = 0.003   # 0.3%
MAX_STOP_DISTANCE_PCT = 0.05    # 5%


class RiskError(ValueError):
    """План не прошёл риск-проверку. Сообщение — причина отказа."""


@dataclass
class RiskCheckResult:
    ok: bool
    reason: str = ""
    risk_amount_usdt: float = 0.0
    risk_percent: float = 0.0
    rr: float = 0.0
    position_size: float = 0.0


class RiskChecker:
    """Валидатор торгового плана под набор консервативных правил.

    Зоны ответственности:
    - формат плана (все поля > 0, направление валидно, SL/TP с правильной стороны)
    - дистанция стопа (не слишком близко и не слишком далеко)
    - RR >= min_risk_reward
    - leverage <= max_leverage
    - shorts только если разрешены
    - количество активных сделок < max_open_trades
    - расчёт размера позиции по % риска
    """

    def __init__(self, config: TradingConfig):
        self.cfg = config

    def check(
        self,
        *,
        direction: str,
        entry: float,
        stop_loss: float,
        take_profit: float,
        leverage: float,
        equity_usdt: float,
        open_trades_count: int,
    ) -> RiskCheckResult:
        direction = direction.lower().strip()
        if direction not in ("long", "short"):
            return RiskCheckResult(False, f"invalid direction: {direction}")

        if direction == "short" and not self.cfg.allow_shorts:
            return RiskCheckResult(False, "shorts disabled (ALLOW_SHORTS=false)")

        if any(v <= 0 for v in (entry, stop_loss, take_profit, leverage, equity_usdt)):
            return RiskCheckResult(False, "non-positive price/leverage/equity")

        if leverage > self.cfg.max_leverage:
            return RiskCheckResult(False, f"leverage {leverage} > max {self.cfg.max_leverage}")

        if open_trades_count >= self.cfg.max_open_trades:
            return RiskCheckResult(False, f"open trades {open_trades_count} >= max {self.cfg.max_open_trades}")

        # стороны SL/TP относительно entry
        if direction == "long":
            if stop_loss >= entry:
                return RiskCheckResult(False, "long: stop_loss must be below entry")
            if take_profit <= entry:
                return RiskCheckResult(False, "long: take_profit must be above entry")
        else:  # short
            if stop_loss <= entry:
                return RiskCheckResult(False, "short: stop_loss must be above entry")
            if take_profit >= entry:
                return RiskCheckResult(False, "short: take_profit must be below entry")

        stop_distance = abs(entry - stop_loss)
        stop_pct = stop_distance / entry
        if stop_pct < MIN_STOP_DISTANCE_PCT:
            return RiskCheckResult(False, f"stop too close: {stop_pct*100:.2f}% < {MIN_STOP_DISTANCE_PCT*100:.2f}%")
        if stop_pct > MAX_STOP_DISTANCE_PCT:
            return RiskCheckResult(False, f"stop too far: {stop_pct*100:.2f}% > {MAX_STOP_DISTANCE_PCT*100:.2f}%")

        reward = abs(take_profit - entry)
        if stop_distance == 0:
            return RiskCheckResult(False, "stop distance is zero")
        rr = reward / stop_distance
        if rr < self.cfg.min_risk_reward:
            return RiskCheckResult(False, f"RR {rr:.2f} < min {self.cfg.min_risk_reward}")

        # размер позиции: при риске `max_risk_per_trade` от equity, потеря на stop = equity*risk_pct.
        # size_in_base = (equity * risk_pct) / stop_distance
        risk_amount_usdt = equity_usdt * self.cfg.max_risk_per_trade
        position_size = risk_amount_usdt / stop_distance

        return RiskCheckResult(
            ok=True,
            reason="ok",
            risk_amount_usdt=risk_amount_usdt,
            risk_percent=self.cfg.max_risk_per_trade,
            rr=rr,
            position_size=position_size,
        )

    def daily_loss_exceeded(self, today_pnl_usdt: float, equity_usdt: float) -> bool:
        """True, если совокупный дневной убыток уже превысил max_daily_loss."""
        if equity_usdt <= 0:
            return True
        return today_pnl_usdt <= -abs(equity_usdt * self.cfg.max_daily_loss)
