"""Safety guards для confirm/live торговли.

Ничего не выставляет на биржу. Только проверяет планы и состояние перед действием.
Все проверки идут одной функцией evaluate(), которая возвращает SafetyVerdict
с человеко-читаемой причиной отказа.

Принципы:
- по умолчанию запрещаем (default-deny)
- любая ошибка → отказ (а не «допустим, всё ок»)
- никогда не логируем секреты (API key/secret)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .config import TradingConfig


log = logging.getLogger("trading.safety")


@dataclass
class SafetyVerdict:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    # Эффективные значения после применения hard-cap'ов:
    effective_leverage: float = 0.0
    effective_equity_usdt: float = 0.0
    notional_usdt: float = 0.0
    risk_amount_usdt: float = 0.0
    position_size: float = 0.0


def cap_leverage(cfg: TradingConfig, requested: float) -> float:
    """Возвращает фактическое плечо, применяя HARD_MAX_LEVERAGE."""
    if requested <= 0:
        return 0.0
    return min(requested, cfg.hard_max_leverage)


def cap_equity(cfg: TradingConfig, real_balance: float) -> float:
    """Возвращает equity, от которой можно считать риск.

    real_balance — текущий баланс на бирже.
    Возвращаем min(real_balance, MAX_LIVE_EQUITY_USDT) — даже если у владельца
    на счёте 500 USDT, бот не имеет права рисковать больше, чем от потолка.
    """
    if real_balance <= 0:
        return 0.0
    return min(real_balance, cfg.max_live_equity_usdt)


def evaluate_confirm_plan(
    cfg: TradingConfig,
    *,
    symbol: str,
    direction: str,
    entry: float,
    stop_loss: float,
    take_profit: float,
    requested_leverage: float,
    real_balance_usdt: float,
    open_positions_count: int,
    today_realized_pnl_usdt: float,
    market_data_available: bool,
) -> SafetyVerdict:
    """Полная проверка плана перед постановкой подтверждения и/или ордера на биржу.

    `today_realized_pnl_usdt` — отрицательное число для убытков.
    """
    reasons: list[str] = []

    # 0. KILL SWITCH
    if cfg.kill_switch:
        reasons.append("KILL_SWITCH=true")

    # 1. рынок
    if not market_data_available:
        reasons.append("market data недоступен")

    # 2. whitelist
    if symbol not in cfg.live_whitelist:
        reasons.append(f"symbol {symbol} не в LIVE_WHITELIST {list(cfg.live_whitelist)}")

    # 3. направление и shorts
    direction = (direction or "").lower()
    if direction not in ("long", "short"):
        reasons.append(f"invalid direction: {direction}")
    if direction == "short" and not cfg.allow_shorts:
        reasons.append("ALLOW_SHORTS=false")

    # 4. SL/TP must exist and быть с правильной стороны
    if stop_loss <= 0 or take_profit <= 0 or entry <= 0:
        reasons.append("entry/SL/TP должны быть > 0")
    else:
        if direction == "long":
            if stop_loss >= entry:
                reasons.append("long: SL должен быть ниже entry")
            if take_profit <= entry:
                reasons.append("long: TP должен быть выше entry")
        elif direction == "short":
            if stop_loss <= entry:
                reasons.append("short: SL должен быть выше entry")
            if take_profit >= entry:
                reasons.append("short: TP должен быть ниже entry")

    # 5. RR
    if entry > 0 and stop_loss > 0 and take_profit > 0:
        stop_dist = abs(entry - stop_loss)
        if stop_dist == 0:
            reasons.append("stop_distance = 0")
        else:
            rr = abs(take_profit - entry) / stop_dist
            if rr < cfg.min_risk_reward:
                reasons.append(f"RR {rr:.2f} < MIN_RISK_REWARD {cfg.min_risk_reward}")

    # 6. min balance
    if real_balance_usdt < cfg.min_live_balance_usdt:
        reasons.append(
            f"баланс {real_balance_usdt:.2f} < MIN_LIVE_BALANCE_USDT {cfg.min_live_balance_usdt}"
        )

    # 7. open positions
    if open_positions_count >= cfg.max_live_open_positions:
        reasons.append(
            f"открытых позиций {open_positions_count} >= MAX_LIVE_OPEN_POSITIONS {cfg.max_live_open_positions}"
        )

    # 8. дневной убыток
    if today_realized_pnl_usdt <= -abs(cfg.max_live_daily_loss_usdt):
        reasons.append(
            f"сегодня уже -{abs(today_realized_pnl_usdt):.2f} USDT >= MAX_LIVE_DAILY_LOSS_USDT {cfg.max_live_daily_loss_usdt}"
        )

    # 9. leverage. Если в плане > HARD_MAX_LEVERAGE → ОТКАЗ (не молча режем).
    eff_leverage = 0.0
    if requested_leverage <= 0:
        reasons.append("leverage должно быть > 0")
    elif requested_leverage > cfg.hard_max_leverage:
        reasons.append(
            f"leverage {requested_leverage} > HARD_MAX_LEVERAGE {cfg.hard_max_leverage} (отклонено, не понижаем молча)"
        )
    else:
        eff_leverage = requested_leverage

    # 10. equity & risk
    eff_equity = cap_equity(cfg, real_balance_usdt)
    risk_amount = eff_equity * cfg.max_live_risk_per_trade
    max_allowed_risk = cfg.max_live_equity_usdt * cfg.max_live_risk_per_trade
    if risk_amount > max_allowed_risk + 1e-9:
        # технически невозможно, потому что eff_equity ≤ MAX_LIVE_EQUITY_USDT, но проверим.
        reasons.append(f"risk_amount {risk_amount:.4f} > max_allowed {max_allowed_risk:.4f}")

    # 11. position size & notional
    position_size = 0.0
    notional = 0.0
    if entry > 0 and stop_loss > 0 and risk_amount > 0:
        stop_dist = abs(entry - stop_loss)
        if stop_dist > 0:
            position_size = risk_amount / stop_dist
            notional = position_size * entry
            if notional > cfg.max_allowed_notional_usdt + 1e-9:
                reasons.append(
                    f"notional {notional:.2f} > MAX_ALLOWED_NOTIONAL_USDT {cfg.max_allowed_notional_usdt}"
                )

    return SafetyVerdict(
        ok=(len(reasons) == 0),
        reasons=reasons,
        effective_leverage=eff_leverage,
        effective_equity_usdt=eff_equity,
        notional_usdt=notional,
        risk_amount_usdt=risk_amount,
        position_size=position_size,
    )


def can_use_live_mode(cfg: TradingConfig) -> tuple[bool, str]:
    """Live-mode гейт. Возвращает (allowed, reason).

    Live запрещён до тех пор, пока CONFIRM_MODE_PROVEN=true. Это осознанный stop-tap:
    владелец сам должен подтвердить готовность переходить на полностью авто.
    """
    if cfg.trading_mode != "live":
        return False, f"TRADING_MODE={cfg.trading_mode}, не live"
    if not cfg.live_trading_enabled:
        return False, "LIVE_TRADING_ENABLED=false"
    if not cfg.confirm_mode_proven:
        return False, "CONFIRM_MODE_PROVEN=false (live mode заблокирован до обкатки confirm)"
    return True, "ok"


def can_use_confirm_mode(cfg: TradingConfig) -> tuple[bool, str]:
    """Confirm-mode гейт. Возвращает (allowed, reason)."""
    if cfg.kill_switch:
        return False, "KILL_SWITCH=true"
    if cfg.trading_mode != "confirm":
        return False, f"TRADING_MODE={cfg.trading_mode}, не confirm"
    if not cfg.confirm_trading_enabled:
        return False, "CONFIRM_TRADING_ENABLED=false"
    if not cfg.gate_api_key_rw or not cfg.gate_api_secret_rw:
        return False, "GATE_API_KEY_RW/GATE_API_SECRET_RW не заданы"
    return True, "ok"


def check_entry_price_deviation(
    cfg: TradingConfig,
    *,
    plan_entry: float,
    current_price: float,
) -> tuple[bool, float]:
    """Перед approve проверяем — не ушла ли цена от плана за время ожидания кнопки."""
    if plan_entry <= 0 or current_price <= 0:
        return False, 0.0
    deviation = abs(current_price - plan_entry) / plan_entry
    return (deviation <= cfg.max_entry_price_deviation_pct), deviation


def is_confirmation_expired(
    cfg: TradingConfig,
    *,
    created_at_iso: str,
    now: Optional[datetime] = None,
) -> bool:
    if not created_at_iso:
        return True
    try:
        created = datetime.fromisoformat(created_at_iso.replace("Z", "+00:00"))
    except Exception:
        return True
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    now = (now or datetime.now(tz=timezone.utc))
    age_minutes = (now - created).total_seconds() / 60.0
    return age_minutes > cfg.confirm_timeout_minutes
