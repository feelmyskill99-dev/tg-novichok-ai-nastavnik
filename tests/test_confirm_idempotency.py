"""ConfirmBroker.approve_trade idempotency (этап 1.2 рефакторинга).

Гарантия: двойной approve_trade(trade_id=...) не должен дважды вызвать
ex.place_limit_entry — реальный entry-ордер ставится максимум один раз.

Двойной approve моделируется как два последовательных вызова (real-world:
владелец дважды нажал inline-кнопку, прежде чем reply_markup был снят).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from trading import confirm_broker as cb_mod
from trading.confirm_broker import ConfirmBroker
from trading.confirm_models import (
    ConfirmTrade,
    ConfirmTradesStore,
    LiveTradesStore,
    LiveTradeJournal,
    STATUS_AWAITING_CONFIRMATION,
    STATUS_ENTRY_ORDER_SUBMITTED,
)


class _FakeExchange:
    def __init__(self) -> None:
        self.entry_calls = 0
        self.leverage_calls = 0

    def get_last_price(self, symbol: str) -> float:
        return 100.0

    def set_leverage_isolated(self, symbol: str, lev: float) -> None:
        self.leverage_calls += 1

    def place_limit_entry(self, *, symbol: str, direction: str, amount: float, price: float) -> dict:
        self.entry_calls += 1
        return {"id": f"ord-{self.entry_calls}"}


@pytest.fixture
def _patched_safety(monkeypatch: pytest.MonkeyPatch) -> None:
    """Замокаем safety-функции в модуле confirm_broker."""
    from trading.safety import SafetyVerdict

    monkeypatch.setattr(cb_mod, "can_use_confirm_mode", lambda cfg: (True, "ok"))
    monkeypatch.setattr(cb_mod, "is_confirmation_expired", lambda cfg, **kw: False)
    monkeypatch.setattr(
        cb_mod, "evaluate_confirm_plan",
        lambda cfg, **kw: SafetyVerdict(ok=True, reasons=[]),
    )
    monkeypatch.setattr(cb_mod, "check_entry_price_deviation", lambda cfg, **kw: (True, 0.0))


@pytest.fixture
def broker_setup(tmp_path: Path, _patched_safety) -> tuple[ConfirmBroker, ConfirmTrade, _FakeExchange]:
    cfg = MagicMock()
    cfg.max_entry_price_deviation_pct = 0.05

    confirm_store = ConfirmTradesStore(tmp_path / "confirm_trades.json")
    live_store = LiveTradesStore(tmp_path / "live_trades.json")
    live_journal = LiveTradeJournal(tmp_path / "live_trade_journal.json")
    exchange = _FakeExchange()

    trade = ConfirmTrade.new(
        symbol="BTC/USDT",
        direction="long",
        entry=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        leverage=3.0,
        position_size=0.01,
        notional_usdt=1.0,
        risk_amount_usdt=0.05,
        rr=2.0,
        rationale="test",
    )
    trade.status = STATUS_AWAITING_CONFIRMATION
    confirm_store.upsert(trade)

    broker = ConfirmBroker(
        cfg,
        confirm_store=confirm_store,
        live_store=live_store,
        live_journal=live_journal,
        exchange=exchange,
    )
    return broker, trade, exchange


def test_single_approve_places_entry_once(broker_setup):
    broker, trade, exchange = broker_setup

    result_trade, msg = broker.approve_trade(
        trade.id, real_balance_usdt=100.0, open_positions_count=0, today_pnl_usdt=0.0,
    )

    assert exchange.entry_calls == 1
    assert result_trade is not None
    assert result_trade.status == STATUS_ENTRY_ORDER_SUBMITTED


def test_double_approve_places_entry_exactly_once(broker_setup):
    """Bug-guard: двойной approve_trade не должен дважды вызвать place_limit_entry."""
    broker, trade, exchange = broker_setup

    first_trade, first_msg = broker.approve_trade(
        trade.id, real_balance_usdt=100.0, open_positions_count=0, today_pnl_usdt=0.0,
    )
    second_trade, second_msg = broker.approve_trade(
        trade.id, real_balance_usdt=100.0, open_positions_count=0, today_pnl_usdt=0.0,
    )

    assert exchange.entry_calls == 1, (
        f"place_limit_entry вызвана {exchange.entry_calls} раз, "
        f"должно быть 1 (двойной approve = двойной ордер)"
    )
    assert first_trade.status == STATUS_ENTRY_ORDER_SUBMITTED
    # Второй вызов должен вернуть отказ с понятным сообщением
    assert second_trade is not None
    assert "approve невозможен" in second_msg or "уже" in second_msg.lower()
