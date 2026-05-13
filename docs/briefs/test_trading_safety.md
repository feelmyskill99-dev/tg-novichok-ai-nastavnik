# Задача: написать tests/test_trading_safety.py

## Цель

Pytest-тесты для функций из модуля `trading/safety.py`. Покрытие:
- `cap_leverage(cfg, requested) -> float` — обрезание плеча по hard_max_leverage.
- `cap_equity(cfg, real_balance) -> float` — equity = min(real_balance, max_live_equity_usdt); 0 если balance≤0.
- `evaluate_confirm_plan(...) -> SafetyVerdict` — комплексная проверка плана.
- `can_use_live_mode(cfg) -> (bool, str)` — гейт live-mode.
- `can_use_confirm_mode(cfg) -> (bool, str)` — гейт confirm-mode.
- `check_entry_price_deviation(cfg, plan_entry, current_price) -> (ok, deviation)` — проверка дрейфа цены.
- `is_confirmation_expired(cfg, created_at_iso, now=None) -> bool` — TTL подтверждения.

## Правила

1. **pytest** (не unittest). Используй `pytest.fixture`, `pytest.mark.parametrize`, `pytest.approx` для float-сравнений где уместно.
2. Файл — самодостаточный. Импорты:
   - `from trading.safety import cap_leverage, cap_equity, evaluate_confirm_plan, can_use_live_mode, can_use_confirm_mode, check_entry_price_deviation, is_confirmation_expired, SafetyVerdict`
   - `from trading.config import TradingConfig`
   - `from datetime import datetime, timezone, timedelta`
3. `TradingConfig` — frozen dataclass. Создавай инстансы через `dataclasses.replace(base_cfg, kill_switch=True)` или передавая kwargs прямо в `TradingConfig(...)`. НЕ читай env.
4. `evaluate_confirm_plan` принимает только keyword args после `cfg`. Базовый «корректный» план (long, BTC/USDT:USDT в whitelist):
   - entry=100.0, stop_loss=95.0, take_profit=110.0, direction="long"
   - requested_leverage=2.0, real_balance_usdt=15.0, open_positions_count=0
   - today_realized_pnl_usdt=0.0, market_data_available=True
   - С дефолтным `TradingConfig()` этот план должен пройти (`verdict.ok == True`, `verdict.reasons == []`).
5. Базовый `TradingConfig()` имеет: `live_whitelist=("BTC/USDT:USDT",)`, `min_live_balance_usdt=10.0`, `max_live_equity_usdt=20.0`, `max_live_risk_per_trade=0.002`, `max_live_daily_loss_usdt=2.0`, `max_live_open_positions=1`, `hard_max_leverage=3.0`, `max_allowed_notional_usdt=30.0`, `min_risk_reward=1.5`, `allow_shorts=False`, `kill_switch=False`, `max_entry_price_deviation_pct=0.003`, `confirm_timeout_minutes=15`, `trading_mode="paper"`, `live_trading_enabled=False`, `confirm_mode_proven=False`, `confirm_trading_enabled=False`.
6. Без эмодзи, без лишних docstring'ов. Короткие говорящие имена тестов: `test_<function>_<scenario>`.

## Покрытие — обязательные сценарии

### `cap_leverage`
- `requested <= 0 → 0.0`
- `requested > hard_max_leverage → hard_max_leverage`
- `requested == hard_max_leverage → requested`
- `0 < requested < hard_max_leverage → requested`

### `cap_equity`
- `real_balance <= 0 → 0.0`
- `real_balance > max_live_equity_usdt → max_live_equity_usdt`
- `real_balance <= max_live_equity_usdt → real_balance`

### `evaluate_confirm_plan` — обязательные негативы (каждый одним тестом):
- **kill_switch=True** → `not ok`, reasons содержит `"KILL_SWITCH=true"`
- **market_data_available=False** → reasons содержит `"market data недоступен"`
- **symbol="ETH/USDT" не в whitelist** → reasons содержит `"не в LIVE_WHITELIST"`
- **direction="short" при allow_shorts=False** → reasons содержит `"ALLOW_SHORTS=false"`
- **direction="invalid"** → reasons содержит `"invalid direction"`
- **long: stop_loss > entry** → reasons содержит `"long: SL должен быть ниже entry"`
- **long: take_profit < entry** → reasons содержит `"long: TP должен быть выше entry"`
- **short (с allow_shorts=True): stop_loss < entry** → reasons содержит `"short: SL должен быть выше entry"`
- **RR < min_risk_reward** → reasons содержит `"RR"` и `"< MIN_RISK_REWARD"` (например entry=100, SL=95, TP=101 при min_rr=1.5)
- **real_balance < min_live_balance_usdt** → reasons содержит `"баланс"`
- **open_positions_count >= max_live_open_positions** → reasons содержит `"открытых позиций"`
- **today_realized_pnl_usdt <= -max_live_daily_loss_usdt** (например -2.5 при лимите 2.0) → reasons содержит `"сегодня уже"`
- **requested_leverage > hard_max_leverage** → reasons содержит `"HARD_MAX_LEVERAGE"`
- **requested_leverage <= 0** → reasons содержит `"leverage должно быть > 0"`
- **notional > max_allowed_notional_usdt** — подобрать риск/SL так, чтобы position_size * entry превысил лимит. Подсказка: с `max_live_equity_usdt=20, max_live_risk_per_trade=0.002, max_allowed_notional_usdt=30, entry=100, stop_loss=99.5` → risk_amount=0.04, position_size=0.04/0.5=0.08, notional=8.0 → НЕ превышает. Чтобы превысить — увеличь `max_live_risk_per_trade` (например до 0.5) или уменьши stop_dist. Проверяй сам arithmetic в `evaluate_confirm_plan`. Если в простом сценарии notional не превысить — пропусти этот тест, но укажи комментарием почему.
- **happy path** → `verdict.ok == True`, `reasons == []`, `effective_leverage == 2.0`, `effective_equity_usdt == 15.0` (min(15, max_live_equity_usdt=20)), `notional > 0`, `position_size > 0`.

### `can_use_live_mode`
- `trading_mode="paper"` → `(False, ...)`
- `trading_mode="live", live_trading_enabled=False` → `(False, ...)`
- `trading_mode="live", live_trading_enabled=True, confirm_mode_proven=False` → `(False, ...)` (CONFIRM_MODE_PROVEN)
- `trading_mode="live", live_trading_enabled=True, confirm_mode_proven=True` → `(True, "ok")`

### `can_use_confirm_mode`
- `kill_switch=True` → `(False, ...)`
- `trading_mode != "confirm"` → `(False, ...)`
- `trading_mode="confirm", confirm_trading_enabled=False` → `(False, ...)`
- Нет `gate_api_key_rw` или нет `gate_api_secret_rw` → `(False, ...)`
- Все условия выполнены → `(True, "ok")`

### `check_entry_price_deviation`
- `plan_entry <= 0` или `current_price <= 0` → `(False, 0.0)`
- Девиация ровно на пороге → `(True, deviation)`
- Девиация выше порога → `(False, deviation)`
- Девиация значительно ниже порога → `(True, deviation)`

### `is_confirmation_expired`
- `created_at_iso == ""` → `True`
- невалидный ISO (`"not-a-date"`) → `True`
- свежее подтверждение (now - created < timeout) → `False`
- просроченное (now - created > timeout) → `True`
- `created_at_iso` БЕЗ tz → должен быть интерпретирован как UTC (не упасть)

## Структура файла

```python
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


# ... тесты ...
```

Дальше — все тесты по списку выше.

## Что НЕ делать

- Не моки. Все функции — pure, моки не нужны.
- Не вызывай `os.getenv`, `load_dotenv` — модулю safety env не нужен.
- Не делай `TradingConfig.from_env()` — собирай инстанс вручную через kwargs или `replace()`.
- Не пиши `if __name__ == "__main__": pytest.main()` в конце файла.
