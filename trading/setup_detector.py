"""RuleBasedSetupDetector — консервативный rule-based фильтр setup'ов.

Никаких «сигналов». Только механическая проверка условий.
Если условия не выполнены — no_trade. Claude вступает ПОСЛЕ, только для объяснения.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

import pandas as pd

from .config import TradingConfig


@dataclass
class Setup:
    """Результат детектора. `action` = trade | no_trade."""
    action: str                     # "trade" | "no_trade"
    direction: Optional[str] = None  # "long" | "short" | None
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    support: Optional[float] = None
    resistance: Optional[float] = None
    rr: Optional[float] = None
    rationale_facts: Optional[dict] = None   # сырые факты для Claude (без интерпретации)
    reason: Optional[str] = None             # если no_trade — почему

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}


# буфер под/над уровнем для стопа (доля от цены)
STOP_BUFFER_PCT = 0.002   # 0.2%
# насколько близко к support должна быть цена, чтобы считать это «close to support»
NEAR_SUPPORT_PCT = 0.015  # цена не дальше 1.5% над support


class RuleBasedSetupDetector:
    """Консервативный фильтр. Long only (пока ALLOW_SHORTS=false)."""

    def __init__(self, config: TradingConfig):
        self.cfg = config

    def detect(self, df: pd.DataFrame) -> Setup:
        """df — OHLCV с колонками Open/High/Low/Close/Volume и индикаторами ema50/ema200/rsi.

        Возвращает Setup. Если условия не выполнены → action=no_trade + reason.
        """
        if df is None or len(df) < 50:
            return Setup(action="no_trade", reason="недостаточно данных для индикаторов")

        last = df.iloc[-1]
        close = float(last["Close"])

        ema50 = self._safe(last, "ema50")
        ema200 = self._safe(last, "ema200")
        rsi = self._safe(last, "rsi")

        if rsi is None:
            return Setup(action="no_trade", reason="нет RSI")

        # 1. trend filter
        trend_ok = False
        trend_fact = ""
        if ema200 is not None and close > ema200:
            trend_ok = True
            trend_fact = "price > EMA200"
        elif ema50 is not None and ema200 is not None and ema50 > ema200:
            trend_ok = True
            trend_fact = "EMA50 > EMA200"

        if not trend_ok:
            return Setup(
                action="no_trade",
                reason="тренд не подтверждён: нет price>EMA200 и нет EMA50>EMA200",
            )

        # 2. RSI не перегрет
        if rsi > 65:
            return Setup(action="no_trade", reason=f"RSI перегрет: {rsi:.1f} > 65")

        # 3. уровни
        near = df.tail(40)
        far = df.tail(120) if len(df) >= 120 else df
        support = float(near["Low"].min())
        resistance = float(near["High"].max())
        # дополнительный дальний горизонт для more reliable resistance
        resistance_far = float(far["High"].max())

        # 4. цена близко к support (не дальше NEAR_SUPPORT_PCT над ним)
        if support <= 0 or close <= support:
            return Setup(
                action="no_trade",
                reason="цена ниже или на support — нет понятной структуры для long",
            )
        distance_to_support = (close - support) / close
        if distance_to_support > NEAR_SUPPORT_PCT:
            return Setup(
                action="no_trade",
                reason=f"цена далеко от support: {distance_to_support*100:.2f}% > {NEAR_SUPPORT_PCT*100:.2f}%",
                support=support,
                resistance=resistance,
            )

        # 5. stop_loss под support с буфером
        stop_loss = support * (1 - STOP_BUFFER_PCT)
        if stop_loss >= close:
            return Setup(action="no_trade", reason="стоп получается выше цены входа")

        # 6. take_profit = ближайший resistance. Если он очень близко — пробуем дальний.
        candidates = sorted({resistance, resistance_far})
        take_profit = None
        for lvl in candidates:
            if lvl > close:
                tp_candidate = lvl
                rr_candidate = (tp_candidate - close) / (close - stop_loss)
                if rr_candidate >= self.cfg.min_risk_reward:
                    take_profit = tp_candidate
                    break

        if take_profit is None:
            return Setup(
                action="no_trade",
                reason=f"нет понятного уровня TP, дающего RR >= {self.cfg.min_risk_reward}",
                support=support,
                resistance=resistance,
            )

        rr = (take_profit - close) / (close - stop_loss)

        facts = {
            "trend": trend_fact,
            "rsi": round(rsi, 2),
            "ema50": round(ema50, 2) if ema50 is not None else None,
            "ema200": round(ema200, 2) if ema200 is not None else None,
            "close": round(close, 2),
            "support": round(support, 2),
            "resistance": round(resistance, 2),
            "distance_to_support_pct": round(distance_to_support * 100, 3),
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "rr": round(rr, 3),
        }

        return Setup(
            action="trade",
            direction="long",
            entry=close,
            stop_loss=stop_loss,
            take_profit=take_profit,
            support=support,
            resistance=resistance,
            rr=rr,
            rationale_facts=facts,
        )

    @staticmethod
    def _safe(row, col: str) -> Optional[float]:
        if col not in row.index:
            return None
        v = row[col]
        if v is None or pd.isna(v):
            return None
        return float(v)
