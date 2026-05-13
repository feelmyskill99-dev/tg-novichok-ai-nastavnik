"""Tests for trading/safety.py — guards для confirm/live торговли."""
from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from trading.config import TradingConfig
from trading.safety import (
    SafetyVerdict,
    cap_equity,
    cap_leverage,
    can_use_confirm_mode,
    can_use_live_mode,
    check_entry_price_deviation,
    evaluate_confirm_plan,
    is_confirmation_expired,
)


@pytest.fixture
def base_cfg() -> TradingConfig:
    return TradingConfig()


@pytest.fixture
def base_plan() -> dict:
    return dict(
        symbol="BTC/USDT:USDT",
        direction="long",
        entry=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        requested_leverage=2.0,
        real_balance_usdt=15.0,
        open_positions_count=0,
        today_realized_pnl_usdt=0.0,
        market_data_available=True,
    )


# ---------- cap_leverage ----------

class TestCapLeverage:
    def test_requested_zero_or_negative(self, base_cfg):
        assert cap_leverage(base_cfg, 0.0) == 0.0
        assert cap_leverage(base_cfg, -1.0) == 0.0

    def test_requested_above_hard_max(self, base_cfg):
        assert cap_leverage(base_cfg, 5.0) == base_cfg.hard_max_leverage

    def test_requested_equal_hard_max(self, base_cfg):
        assert cap_leverage(base_cfg, 3.0) == 3.0

    def test_requested_below_hard_max(self, base_cfg):
        assert cap_leverage(base_cfg, 2.0) == 2.0


# ---------- cap_equity ----------

class TestCapEquity:
    def test_balance_zero_or_negative(self, base_cfg):
        assert cap_equity(base_cfg, 0.0) == 0.0
        assert cap_equity(base_cfg, -5.0) == 0.0

    def test_balance_above_max_equity(self, base_cfg):
        assert cap_equity(base_cfg, 50.0) == base_cfg.max_live_equity_usdt

    def test_balance_within_limit(self, base_cfg):
        assert cap_equity(base_cfg, 15.0) == 15.0


# ---------- evaluate_confirm_plan ----------

class TestEvaluateConfirmPlan:
    def test_happy_path(self, base_cfg, base_plan):
        verdict = evaluate_confirm_plan(base_cfg, **base_plan)
        assert verdict.ok
        assert verdict.reasons == []
        assert verdict.effective_leverage == 2.0
        assert verdict.effective_equity_usdt == 15.0
        assert verdict.notional_usdt > 0
        assert verdict.position_size > 0

    def test_kill_switch(self, base_cfg, base_plan):
        cfg = replace(base_cfg, kill_switch=True)
        verdict = evaluate_confirm_plan(cfg, **base_plan)
        assert not verdict.ok
        assert "KILL_SWITCH=true" in verdict.reasons

    def test_market_data_unavailable(self, base_cfg, base_plan):
        plan = {**base_plan, "market_data_available": False}
        verdict = evaluate_confirm_plan(base_cfg, **plan)
        assert not verdict.ok
        assert "market data недоступен" in verdict.reasons

    def test_symbol_not_in_whitelist(self, base_cfg, base_plan):
        plan = {**base_plan, "symbol": "ETH/USDT"}
        verdict = evaluate_confirm_plan(base_cfg, **plan)
        assert not verdict.ok
        assert any("не в LIVE_WHITELIST" in r for r in verdict.reasons)

    def test_short_disallowed(self, base_cfg, base_plan):
        plan = {**base_plan, "direction": "short"}
        verdict = evaluate_confirm_plan(base_cfg, **plan)
        assert not verdict.ok
        assert "ALLOW_SHORTS=false" in verdict.reasons

    def test_invalid_direction(self, base_cfg, base_plan):
        plan = {**base_plan, "direction": "invalid"}
        verdict = evaluate_confirm_plan(base_cfg, **plan)
        assert not verdict.ok
        assert any("invalid direction" in r for r in verdict.reasons)

    def test_long_sl_above_entry(self, base_cfg, base_plan):
        plan = {**base_plan, "stop_loss": 101.0}
        verdict = evaluate_confirm_plan(base_cfg, **plan)
        assert not verdict.ok
        assert "long: SL должен быть ниже entry" in verdict.reasons

    def test_long_tp_below_entry(self, base_cfg, base_plan):
        plan = {**base_plan, "take_profit": 99.0}
        verdict = evaluate_confirm_plan(base_cfg, **plan)
        assert not verdict.ok
        assert "long: TP должен быть выше entry" in verdict.reasons

    def test_short_sl_below_entry(self, base_cfg, base_plan):
        cfg = replace(base_cfg, allow_shorts=True)
        plan = {**base_plan, "direction": "short", "stop_loss": 90.0, "take_profit": 95.0}
        verdict = evaluate_confirm_plan(cfg, **plan)
        assert not verdict.ok
        assert "short: SL должен быть выше entry" in verdict.reasons

    def test_rr_below_minimum(self, base_cfg, base_plan):
        # entry=100, SL=95, TP=101 -> RR=0.2 < 1.5
        plan = {**base_plan, "entry": 100.0, "stop_loss": 95.0, "take_profit": 101.0}
        verdict = evaluate_confirm_plan(base_cfg, **plan)
        assert not verdict.ok
        assert any("RR" in r and "< MIN_RISK_REWARD" in r for r in verdict.reasons)

    def test_balance_below_min(self, base_cfg, base_plan):
        plan = {**base_plan, "real_balance_usdt": 5.0}
        verdict = evaluate_confirm_plan(base_cfg, **plan)
        assert not verdict.ok
        assert any("баланс" in r for r in verdict.reasons)

    def test_open_positions_maxed(self, base_cfg, base_plan):
        plan = {**base_plan, "open_positions_count": 1}
        verdict = evaluate_confirm_plan(base_cfg, **plan)
        assert not verdict.ok
        assert any("открытых позиций" in r for r in verdict.reasons)

    def test_daily_loss_exceeded(self, base_cfg, base_plan):
        plan = {**base_plan, "today_realized_pnl_usdt": -2.5}
        verdict = evaluate_confirm_plan(base_cfg, **plan)
        assert not verdict.ok
        assert any("сегодня уже" in r for r in verdict.reasons)

    def test_leverage_above_hard_max(self, base_cfg, base_plan):
        plan = {**base_plan, "requested_leverage": 5.0}
        verdict = evaluate_confirm_plan(base_cfg, **plan)
        assert not verdict.ok
        assert any("HARD_MAX_LEVERAGE" in r for r in verdict.reasons)

    def test_leverage_zero_or_negative(self, base_cfg, base_plan):
        plan = {**base_plan, "requested_leverage": 0.0}
        verdict = evaluate_confirm_plan(base_cfg, **plan)
        assert not verdict.ok
        assert "leverage должно быть > 0" in verdict.reasons

    def test_notional_exceeds_max(self, base_cfg, base_plan):
        # настраиваем cfg так, чтобы notional превысил max_allowed_notional_usdt
        cfg = replace(base_cfg, max_live_risk_per_trade=0.5)
        # risk_amount = 20*0.5=10, stop_dist=0.5 -> position_size=20, notional=2000 > 30
        plan = {**base_plan, "entry": 100.0, "stop_loss": 99.5}
        verdict = evaluate_confirm_plan(cfg, **plan)
        assert not verdict.ok
        assert any("notional" in r.lower() for r in verdict.reasons)

    def test_no_issues_passes(self, base_cfg, base_plan):
        verdict = evaluate_confirm_plan(base_cfg, **base_plan)
        assert verdict.ok
        assert verdict.reasons == []


# ---------- can_use_live_mode ----------

class TestCanUseLiveMode:
    def test_mode_paper(self, base_cfg):
        ok, reason = can_use_live_mode(base_cfg)
        assert not ok
        assert "paper" in reason

    def test_live_not_enabled(self, base_cfg):
        cfg = replace(base_cfg, trading_mode="live", live_trading_enabled=False)
        ok, reason = can_use_live_mode(cfg)
        assert not ok
        assert "LIVE_TRADING_ENABLED=false" in reason

    def test_confirm_mode_not_proven(self, base_cfg):
        cfg = replace(base_cfg, trading_mode="live", live_trading_enabled=True, confirm_mode_proven=False)
        ok, reason = can_use_live_mode(cfg)
        assert not ok
        assert "CONFIRM_MODE_PROVEN=false" in reason

    def test_all_conditions_met(self, base_cfg):
        cfg = replace(base_cfg, trading_mode="live", live_trading_enabled=True, confirm_mode_proven=True)
        ok, reason = can_use_live_mode(cfg)
        assert ok
        assert reason == "ok"


# ---------- can_use_confirm_mode ----------

class TestCanUseConfirmMode:
    def test_kill_switch(self, base_cfg):
        cfg = replace(base_cfg, kill_switch=True)
        ok, reason = can_use_confirm_mode(cfg)
        assert not ok
        assert "KILL_SWITCH=true" in reason

    def test_wrong_mode(self, base_cfg):
        cfg = replace(base_cfg, trading_mode="paper")
        ok, reason = can_use_confirm_mode(cfg)
        assert not ok
        assert "не confirm" in reason

    def test_confirm_mode_not_enabled(self, base_cfg):
        cfg = replace(base_cfg, trading_mode="confirm", confirm_trading_enabled=False)
        ok, reason = can_use_confirm_mode(cfg)
        assert not ok
        assert "CONFIRM_TRADING_ENABLED=false" in reason

    def test_missing_api_keys(self, base_cfg):
        cfg = replace(base_cfg, trading_mode="confirm", confirm_trading_enabled=True,
                      gate_api_key_rw="", gate_api_secret_rw="")
        ok, reason = can_use_confirm_mode(cfg)
        assert not ok
        assert "GATE_API_KEY_RW/GATE_API_SECRET_RW не заданы" in reason

    def test_all_conditions_met(self, base_cfg):
        cfg = replace(base_cfg, trading_mode="confirm", confirm_trading_enabled=True,
                      gate_api_key_rw="key", gate_api_secret_rw="secret")
        ok, reason = can_use_confirm_mode(cfg)
        assert ok
        assert reason == "ok"


# ---------- check_entry_price_deviation ----------

class TestCheckEntryPriceDeviation:
    def test_zero_or_negative_prices(self, base_cfg):
        ok, dev = check_entry_price_deviation(base_cfg, plan_entry=0.0, current_price=100.0)
        assert not ok and dev == 0.0
        ok, dev = check_entry_price_deviation(base_cfg, plan_entry=100.0, current_price=0.0)
        assert not ok and dev == 0.0

    def test_deviation_exactly_at_threshold(self, base_cfg):
        # max_entry_price_deviation_pct=0.003, plan=100, current=100.3 -> deviation=0.003
        ok, dev = check_entry_price_deviation(base_cfg, plan_entry=100.0, current_price=100.3)
        assert ok
        assert dev == pytest.approx(0.003, rel=1e-9)

    def test_deviation_above_threshold(self, base_cfg):
        ok, dev = check_entry_price_deviation(base_cfg, plan_entry=100.0, current_price=100.4)
        assert not ok
        assert dev > 0.003

    def test_deviation_below_threshold(self, base_cfg):
        ok, dev = check_entry_price_deviation(base_cfg, plan_entry=100.0, current_price=100.1)
        assert ok
        assert dev < 0.003


# ---------- is_confirmation_expired ----------

class TestIsConfirmationExpired:
    def test_empty_string(self, base_cfg):
        assert is_confirmation_expired(base_cfg, created_at_iso="")

    def test_invalid_iso(self, base_cfg):
        assert is_confirmation_expired(base_cfg, created_at_iso="not-a-date")

    def test_fresh_confirmation(self, base_cfg):
        now = datetime.now(tz=timezone.utc)
        created = (now - timedelta(minutes=5)).isoformat()
        assert not is_confirmation_expired(base_cfg, created_at_iso=created, now=now)

    def test_expired_confirmation(self, base_cfg):
        now = datetime.now(tz=timezone.utc)
        created = (now - timedelta(minutes=20)).isoformat()
        assert is_confirmation_expired(base_cfg, created_at_iso=created, now=now)

    def test_created_without_tz(self, base_cfg):
        now = datetime.now(tz=timezone.utc)
        # строка без часового пояса (должна интерпретироваться как UTC)
        created = (now - timedelta(minutes=5)).replace(tzinfo=None).isoformat()
        assert not is_confirmation_expired(base_cfg, created_at_iso=created, now=now)