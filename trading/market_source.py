"""TradingMarket — обёртка над ccxt.gateio специально для торгового движка.

Существующий `Market` в bot.py использует spot-символ (BTC/USDT) для OHLCV и swap только
для funding/OI. Для paper-торговли нам нужны именно futures-свечи (BTC/USDT:USDT),
поэтому держим отдельный маленький клиент.
"""

from __future__ import annotations

from typing import Optional

import ccxt
import pandas as pd
import ta


class TradingMarket:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.ex = ccxt.gateio({"enableRateLimit": True})

    def fetch_ohlcv(self, timeframe: str, limit: int) -> Optional[pd.DataFrame]:
        try:
            raw = self.ex.fetch_ohlcv(self.symbol, timeframe, limit=limit)
        except Exception:
            return None
        if not raw:
            return None
        df = pd.DataFrame(raw, columns=["ts", "Open", "High", "Low", "Close", "Volume"])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms")
        df.set_index("ts", inplace=True)
        return self._with_indicators(df)

    @staticmethod
    def _with_indicators(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or len(df) < 20:
            return df
        df = df.copy()
        if len(df) >= 50:
            df["ema50"] = ta.trend.ema_indicator(df["Close"], 50)
        if len(df) >= 200:
            df["ema200"] = ta.trend.ema_indicator(df["Close"], 200)
        df["rsi"] = ta.momentum.rsi(df["Close"], 14)
        return df
