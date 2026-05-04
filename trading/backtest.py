"""run_backtest — прогоняет rule-based детектор по историческим свечам.

Claude не вызывается. rationale для каждой сделки = "rule-based historical setup".
Один активный трейд за раз (так как MAX_OPEN_TRADES=1 по умолчанию).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from .broker import PaperBroker, PaperTrade, TradePlan
from .config import TradingConfig
from .risk import RiskChecker
from .setup_detector import RuleBasedSetupDetector


WARMUP_BARS = 210   # чтобы успел посчитаться EMA200 (нужно >=200) + запас


@dataclass
class BacktestResult:
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    winrate: float = 0.0
    total_pnl_usdt: float = 0.0
    total_R: float = 0.0
    max_drawdown: float = 0.0
    average_R: float = 0.0
    tp_count: int = 0
    sl_count: int = 0
    expired_count: int = 0
    skipped_setups: int = 0
    final_paper_equity: float = 0.0
    initial_equity: float = 0.0
    closed_trades: list[PaperTrade] = field(default_factory=list)

    def to_summary_dict(self) -> dict:
        return {
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "winrate": round(self.winrate, 4),
            "total_pnl_usdt": round(self.total_pnl_usdt, 4),
            "total_R": round(self.total_R, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "average_R": round(self.average_R, 4),
            "tp_count": self.tp_count,
            "sl_count": self.sl_count,
            "expired_count": self.expired_count,
            "skipped_setups": self.skipped_setups,
            "final_paper_equity": round(self.final_paper_equity, 4),
            "initial_equity": round(self.initial_equity, 4),
        }


def _compute_drawdown(equity_curve: list[float]) -> float:
    peak = -float("inf")
    max_dd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = peak - v
        if dd > max_dd:
            max_dd = dd
    return max_dd


def run_backtest(
    df: pd.DataFrame,
    *,
    config: TradingConfig,
    detector: RuleBasedSetupDetector,
    risk_checker: RiskChecker,
    broker: PaperBroker,
    initial_equity: float,
) -> BacktestResult:
    if df is None or len(df) < WARMUP_BARS + 5:
        raise ValueError(f"недостаточно баров для backtest: {0 if df is None else len(df)} < {WARMUP_BARS + 5}")

    # детектор требует индикаторы в df — ожидаем, что caller уже прогнал Market.indicators
    for col in ("ema50", "ema200", "rsi"):
        if col not in df.columns:
            raise ValueError(f"df не содержит индикатор '{col}'. Прогоните Market.indicators() до backtest.")

    equity = float(initial_equity)
    equity_curve = [equity]
    active: Optional[PaperTrade] = None
    closed: list[PaperTrade] = []
    skipped = 0

    for i in range(WARMUP_BARS, len(df)):
        bar = df.iloc[i]
        bar_ts = bar.name.to_pydatetime() if hasattr(bar.name, "to_pydatetime") else None

        # 1. обновляем активный трейд по свече
        if active is not None:
            event = broker.tick(
                active,
                bar_index=i,
                open_=float(bar["Open"]),
                high=float(bar["High"]),
                low=float(bar["Low"]),
                close=float(bar["Close"]),
                ts=bar_ts,
            )
            if active.status not in ("pending", "open"):
                if active.pnl_usdt:
                    equity += float(active.pnl_usdt)
                closed.append(active)
                active = None
                equity_curve.append(equity)
            else:
                equity_curve.append(equity)

        # 2. если свободно — ищем новый setup на закрытии этой свечи
        if active is None:
            sub_df = df.iloc[: i + 1]
            setup = detector.detect(sub_df)
            if setup.action != "trade":
                skipped += 1
                continue

            result = risk_checker.check(
                direction=setup.direction or "long",
                entry=setup.entry or 0.0,
                stop_loss=setup.stop_loss or 0.0,
                take_profit=setup.take_profit or 0.0,
                leverage=config.max_leverage,
                equity_usdt=equity,
                open_trades_count=0,
            )
            if not result.ok:
                skipped += 1
                continue

            plan = TradePlan(
                symbol=config.default_symbol,
                direction=setup.direction or "long",
                entry=setup.entry or 0.0,
                stop_loss=setup.stop_loss or 0.0,
                take_profit=setup.take_profit or 0.0,
                leverage=config.max_leverage,
                position_size=result.position_size,
                risk_amount_usdt=result.risk_amount_usdt,
                rr=result.rr,
                rationale="rule-based historical setup",
                meta={"facts": setup.rationale_facts},
            )
            active = broker.create_plan(plan, bar_index=i, now=bar_ts)

    # если осталась активная сделка — закрываем как expired по close последней свечи
    if active is not None:
        last = df.iloc[-1]
        broker.close_trade(
            active,
            reason="expired",
            close_price=float(last["Close"]),
            bar_index=len(df) - 1,
        )
        if active.pnl_usdt:
            equity += float(active.pnl_usdt)
        closed.append(active)
        equity_curve.append(equity)

    # --- метрики ---
    total = len(closed)
    tp_count = sum(1 for t in closed if t.close_reason == "tp")
    sl_count = sum(1 for t in closed if t.close_reason == "sl")
    expired_count = sum(1 for t in closed if t.close_reason == "expired")

    wins = sum(1 for t in closed if (t.pnl_usdt or 0) > 0)
    losses = sum(1 for t in closed if (t.pnl_usdt or 0) < 0)
    winrate = (wins / total) if total else 0.0

    total_pnl = sum((t.pnl_usdt or 0.0) for t in closed)
    r_values = [t.r_multiple for t in closed if t.r_multiple is not None]
    total_R = sum(r_values)
    avg_R = statistics.fmean(r_values) if r_values else 0.0
    max_dd = _compute_drawdown(equity_curve)

    return BacktestResult(
        total_trades=total,
        wins=wins,
        losses=losses,
        winrate=winrate,
        total_pnl_usdt=total_pnl,
        total_R=total_R,
        max_drawdown=max_dd,
        average_R=avg_R,
        tp_count=tp_count,
        sl_count=sl_count,
        expired_count=expired_count,
        skipped_setups=skipped,
        final_paper_equity=equity,
        initial_equity=initial_equity,
        closed_trades=closed,
    )
