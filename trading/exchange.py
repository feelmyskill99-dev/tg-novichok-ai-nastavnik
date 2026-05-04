"""GateRWClient — тонкая обёртка над ccxt.gateio с RW-ключами.

Только методы, которые реально используем в Stage 8a:
- get_usdt_futures_balance (для проверки min_balance, daily-loss и тд)
- get_open_positions
- get_open_orders
- set_leverage_isolated
- place_limit_entry
- place_protection_orders (TP + SL, reduce-only)
- cancel_order
- close_position_market

ВАЖНО:
- никогда не логировать API key/secret;
- любая ошибка биржи поднимается наружу как ExchangeError, чтобы вызывающий код
  мог принять решение (откатить план, отправить алёрт, отказать в approve);
- reduce-only обязателен для TP/SL, иначе они могут случайно открыть встречную позицию.

Endpoint Gate.io futures через ccxt:
- defaultType="swap" → перпы USDT-margined
- TP/SL в Gate API: используется `triggerPrice` + `reduceOnly: true`. ccxt
  стандартизирует это через unified API: trigger orders.
"""

from __future__ import annotations

import logging
from typing import Any

import ccxt

from .config import TradingConfig


log = logging.getLogger("trading.exchange")


class ExchangeError(RuntimeError):
    """Любая ошибка взаимодействия с биржей. Не наследуем напрямую от ccxt-исключений,
    чтобы вызывающему коду не нужно было импортировать ccxt."""


class GateRWClient:
    def __init__(self, cfg: TradingConfig):
        if not cfg.gate_api_key_rw or not cfg.gate_api_secret_rw:
            raise ExchangeError("GATE_API_KEY_RW/GATE_API_SECRET_RW не заданы")
        self.cfg = cfg
        self.ex = ccxt.gateio({
            "apiKey": cfg.gate_api_key_rw,
            "secret": cfg.gate_api_secret_rw,
            "enableRateLimit": True,
            "options": {"defaultType": "swap"},
        })

    # ---------- balance ----------
    def get_usdt_futures_balance(self) -> float:
        """Сколько USDT в futures-кошельке (total). Возвращает 0.0 если не нашли."""
        try:
            bal = self.ex.fetch_balance({"type": "swap"})
        except Exception as e:
            raise ExchangeError(f"fetch_balance failed: {e}") from e
        # Структура ccxt: bal["USDT"]["total"] либо bal["total"]["USDT"]
        usdt = bal.get("USDT")
        if isinstance(usdt, dict):
            v = usdt.get("total") or usdt.get("free")
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
        total = bal.get("total")
        if isinstance(total, dict):
            v = total.get("USDT")
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
        return 0.0

    # ---------- positions / orders ----------
    def get_open_positions(self, symbols: list[str] | None = None) -> list[dict]:
        try:
            if symbols:
                positions = self.ex.fetch_positions(symbols)
            else:
                positions = self.ex.fetch_positions()
        except Exception as e:
            raise ExchangeError(f"fetch_positions failed: {e}") from e
        # Только реально открытые (contracts/qty > 0)
        out = []
        for p in positions or []:
            contracts = p.get("contracts") or p.get("contractSize") or 0
            try:
                if float(contracts) > 0:
                    out.append(p)
            except (TypeError, ValueError):
                continue
        return out

    def get_open_orders(self, symbol: str) -> list[dict]:
        try:
            return self.ex.fetch_open_orders(symbol) or []
        except Exception as e:
            raise ExchangeError(f"fetch_open_orders failed: {e}") from e

    def get_order(self, order_id: str, symbol: str) -> dict:
        try:
            return self.ex.fetch_order(order_id, symbol) or {}
        except Exception as e:
            raise ExchangeError(f"fetch_order failed: {e}") from e

    # ---------- leverage / margin ----------
    def set_leverage_isolated(self, symbol: str, leverage: float) -> None:
        """Ставит плечо в isolated mode. У Gate.io для futures это атомарная операция."""
        try:
            # сначала margin mode
            try:
                self.ex.set_margin_mode("isolated", symbol)
            except Exception as e:
                # Если уже стоит isolated — Gate может вернуть ошибку. Глотаем тихо,
                # но логируем кратко (без секретов).
                log.debug("set_margin_mode noop: %s", e)
            self.ex.set_leverage(int(leverage), symbol, params={"marginMode": "isolated"})
        except Exception as e:
            raise ExchangeError(f"set_leverage_isolated failed: {e}") from e

    # ---------- entry ----------
    def place_limit_entry(
        self,
        *,
        symbol: str,
        direction: str,
        amount: float,
        price: float,
    ) -> dict:
        """Limit entry. Возвращает dict с id, status и т.д."""
        side = "buy" if direction == "long" else "sell"
        params = {
            "marginMode": "isolated",
            "timeInForce": "GTC",
            "reduceOnly": False,
        }
        try:
            order = self.ex.create_order(symbol, "limit", side, amount, price, params)
            return order or {}
        except Exception as e:
            raise ExchangeError(f"place_limit_entry failed: {e}") from e

    def cancel_order(self, order_id: str, symbol: str) -> None:
        try:
            self.ex.cancel_order(order_id, symbol)
        except Exception as e:
            raise ExchangeError(f"cancel_order failed: {e}") from e

    # ---------- TP / SL (reduce-only) ----------
    def place_stop_loss(
        self,
        *,
        symbol: str,
        direction: str,
        amount: float,
        stop_price: float,
    ) -> dict:
        """Stop-market reduce-only ордер. Закроет позицию по рынку при касании stop_price.

        Side противоположен direction (long → sell, short → buy).
        """
        side = "sell" if direction == "long" else "buy"
        params = {
            "reduceOnly": True,
            "marginMode": "isolated",
            "trigger": "last_price",
            "triggerPrice": stop_price,
            "stopLossPrice": stop_price,
        }
        try:
            order = self.ex.create_order(symbol, "market", side, amount, None, params)
            return order or {}
        except Exception as e:
            raise ExchangeError(f"place_stop_loss failed: {e}") from e

    def place_take_profit(
        self,
        *,
        symbol: str,
        direction: str,
        amount: float,
        take_price: float,
    ) -> dict:
        """Take-profit reduce-only ордер. Закроет позицию по рынку при касании take_price."""
        side = "sell" if direction == "long" else "buy"
        params = {
            "reduceOnly": True,
            "marginMode": "isolated",
            "trigger": "last_price",
            "triggerPrice": take_price,
            "takeProfitPrice": take_price,
        }
        try:
            order = self.ex.create_order(symbol, "market", side, amount, None, params)
            return order or {}
        except Exception as e:
            raise ExchangeError(f"place_take_profit failed: {e}") from e

    # ---------- emergency close ----------
    def close_position_market(self, *, symbol: str, direction: str, amount: float) -> dict:
        """Market reduce-only — экстренное закрытие позиции (kill switch / no-SL emergency)."""
        side = "sell" if direction == "long" else "buy"
        params = {
            "reduceOnly": True,
            "marginMode": "isolated",
        }
        try:
            order = self.ex.create_order(symbol, "market", side, amount, None, params)
            return order or {}
        except Exception as e:
            raise ExchangeError(f"close_position_market failed: {e}") from e

    # ---------- spot price (для price deviation check) ----------
    def get_last_price(self, symbol: str) -> float:
        try:
            t = self.ex.fetch_ticker(symbol)
            v = t.get("last") or t.get("close")
            return float(v) if v is not None else 0.0
        except Exception as e:
            raise ExchangeError(f"fetch_ticker failed: {e}") from e
