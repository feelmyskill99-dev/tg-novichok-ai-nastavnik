"""Чтение реального баланса Gate.io (read-only).

Если ключей нет / API упал — возвращаем PAPER_EQUITY_USDT и пишем warning.
Никаких write-операций.
"""

from __future__ import annotations

import logging
from typing import Tuple

import ccxt

from .config import TradingConfig


log = logging.getLogger("trading.balance")


def fetch_paper_equity(cfg: TradingConfig) -> Tuple[float, str]:
    """Возвращает (equity_usdt, source).

    source ∈ {"real", "env", "fallback"}:
        real      — получили с Gate.io
        env       — READ_REAL_BALANCE=false или ключи не заданы, используем PAPER_EQUITY_USDT
        fallback  — пытались сходить на Gate, но API упал / вернул пусто
    """
    if not cfg.read_real_balance or not cfg.gate_api_key or not cfg.gate_api_secret:
        return cfg.paper_equity_usdt, "env"

    try:
        ex = ccxt.gateio({
            "apiKey": cfg.gate_api_key,
            "secret": cfg.gate_api_secret,
            "enableRateLimit": True,
        })
        usdt = _extract_usdt(ex.fetch_balance({"type": "swap"}))
        if usdt is None or usdt <= 0:
            usdt = _extract_usdt(ex.fetch_balance())
        if usdt is None or usdt <= 0:
            log.warning("Gate.io balance пустой, откатываемся на PAPER_EQUITY_USDT=%s", cfg.paper_equity_usdt)
            return cfg.paper_equity_usdt, "fallback"
        return float(usdt), "real"
    except Exception as e:
        log.warning("Gate.io balance недоступен (%s), откатываемся на PAPER_EQUITY_USDT=%s",
                    e, cfg.paper_equity_usdt)
        return cfg.paper_equity_usdt, "fallback"


def _extract_usdt(balance: dict | None) -> float | None:
    if not balance:
        return None
    # Вариант 1: balance["USDT"] = {"free","used","total"}
    usdt_entry = balance.get("USDT")
    if isinstance(usdt_entry, dict):
        v = usdt_entry.get("total") or usdt_entry.get("free")
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    # Вариант 2: balance["total"]["USDT"] = N
    total = balance.get("total")
    if isinstance(total, dict):
        v = total.get("USDT")
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None
