"""TradingConfig — загружает торговые параметры из .env.

Только чтение. Никаких мутаций. Если параметр отсутствует — используется безопасный дефолт.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _str(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


TRADE_PUBLISH_MODES = (
    "owner_only",
    "opened_only",
    "closed_only",
    "opened_and_closed",
    "manual_only",
)


@dataclass(frozen=True)
class TradingConfig:
    # --- режим ---
    trading_mode: str = "paper"            # paper | confirm | live (но реализован только paper)
    read_real_balance: bool = True
    paper_equity_usdt: float = 50.0

    # --- Gate.io read-only (для баланса) ---
    gate_api_key: str = ""
    gate_api_secret: str = ""

    # --- риск и объёмы ---
    max_risk_per_trade: float = 0.002      # 0.2% от equity
    max_leverage: float = 2.0
    max_daily_loss: float = 0.02           # 2% от equity
    max_open_trades: int = 1
    min_risk_reward: float = 1.5

    # --- инструмент и таймфреймы ---
    default_symbol: str = "BTC/USDT:USDT"
    default_timeframe: str = "1h"
    trend_timeframe: str = "4h"
    default_margin_mode: str = "isolated"

    # --- флаги ---
    allow_futures: bool = True
    allow_shorts: bool = False
    require_manual_confirmation: bool = True
    live_trading_enabled: bool = False
    publish_trade_updates_to_channel: bool = False

    # --- срок жизни setup ---
    trade_setup_expires_bars: int = 6

    # --- Stage 7: автоматический paper-trading + публикация в канал ---
    auto_trade_enabled: bool = False
    auto_trade_scan_interval_minutes: int = 60
    auto_trade_tick_interval_minutes: int = 60

    trade_publish_mode: str = "closed_only"
    trade_claude_review: bool = True
    trade_min_channel_impact: int = 70
    trade_max_channel_posts_per_day: int = 1

    trade_publish_losses: bool = True
    trade_publish_wins: bool = True
    trade_publish_expired: bool = False

    trade_require_lesson: bool = True
    trade_no_signal_language: bool = True

    # --- Stage 8a: Confirm-mode (real Gate.io futures with manual button) ---
    confirm_trading_enabled: bool = False
    confirm_timeout_minutes: int = 15
    confirm_entry_order_type: str = "limit"          # сейчас только limit
    confirm_order_expires_minutes: int = 15
    max_entry_price_deviation_pct: float = 0.003     # 0.3%

    # отдельные read-write ключи (read-only — это GATE_API_KEY/GATE_API_SECRET)
    gate_api_key_rw: str = ""
    gate_api_secret_rw: str = ""

    # safety-guards
    live_whitelist: tuple[str, ...] = ("BTC/USDT:USDT",)
    max_live_equity_usdt: float = 20.0
    min_live_balance_usdt: float = 10.0
    max_live_risk_per_trade: float = 0.002
    max_live_daily_loss_usdt: float = 2.0
    max_live_open_positions: int = 1
    hard_max_leverage: float = 3.0
    max_allowed_notional_usdt: float = 30.0

    kill_switch: bool = False
    close_positions_on_kill_switch: bool = False

    # live-mode гейт. Пока CONFIRM_MODE_PROVEN=false — live игнорируется,
    # даже если LIVE_TRADING_ENABLED=true.
    confirm_mode_proven: bool = False

    # reconciliation
    live_reconcile_interval_minutes: int = 5

    @classmethod
    def from_env(cls) -> "TradingConfig":
        publish_mode = _str("TRADE_PUBLISH_MODE", "closed_only").lower()
        if publish_mode not in TRADE_PUBLISH_MODES:
            publish_mode = "closed_only"

        return cls(
            trading_mode=_str("TRADING_MODE", "paper").lower(),
            read_real_balance=_bool("READ_REAL_BALANCE", True),
            paper_equity_usdt=_float("PAPER_EQUITY_USDT", 50.0),

            gate_api_key=_str("GATE_API_KEY", ""),
            gate_api_secret=_str("GATE_API_SECRET", ""),

            max_risk_per_trade=_float("MAX_RISK_PER_TRADE", 0.002),
            max_leverage=_float("MAX_LEVERAGE", 2.0),
            max_daily_loss=_float("MAX_DAILY_LOSS", 0.02),
            max_open_trades=_int("MAX_OPEN_TRADES", 1),
            min_risk_reward=_float("MIN_RISK_REWARD", 1.5),

            default_symbol=_str("DEFAULT_SYMBOL", "BTC/USDT:USDT"),
            default_timeframe=_str("DEFAULT_TIMEFRAME", "1h"),
            trend_timeframe=_str("TREND_TIMEFRAME", "4h"),
            default_margin_mode=_str("DEFAULT_MARGIN_MODE", "isolated"),

            allow_futures=_bool("ALLOW_FUTURES", True),
            allow_shorts=_bool("ALLOW_SHORTS", False),
            require_manual_confirmation=_bool("REQUIRE_MANUAL_CONFIRMATION", True),
            live_trading_enabled=_bool("LIVE_TRADING_ENABLED", False),
            publish_trade_updates_to_channel=_bool("PUBLISH_TRADE_UPDATES_TO_CHANNEL", False),

            trade_setup_expires_bars=_int("TRADE_SETUP_EXPIRES_BARS", 6),

            auto_trade_enabled=_bool("AUTO_TRADE_ENABLED", False),
            auto_trade_scan_interval_minutes=_int("AUTO_TRADE_SCAN_INTERVAL_MINUTES", 60),
            auto_trade_tick_interval_minutes=_int("AUTO_TRADE_TICK_INTERVAL_MINUTES", 60),

            trade_publish_mode=publish_mode,
            trade_claude_review=_bool("TRADE_CLAUDE_REVIEW", True),
            trade_min_channel_impact=_int("TRADE_MIN_CHANNEL_IMPACT", 70),
            trade_max_channel_posts_per_day=_int("TRADE_MAX_CHANNEL_POSTS_PER_DAY", 1),

            trade_publish_losses=_bool("TRADE_PUBLISH_LOSSES", True),
            trade_publish_wins=_bool("TRADE_PUBLISH_WINS", True),
            trade_publish_expired=_bool("TRADE_PUBLISH_EXPIRED", False),

            trade_require_lesson=_bool("TRADE_REQUIRE_LESSON", True),
            trade_no_signal_language=_bool("TRADE_NO_SIGNAL_LANGUAGE", True),

            # --- Stage 8a ---
            confirm_trading_enabled=_bool("CONFIRM_TRADING_ENABLED", False),
            confirm_timeout_minutes=_int("CONFIRM_TIMEOUT_MINUTES", 15),
            confirm_entry_order_type=_str("CONFIRM_ENTRY_ORDER_TYPE", "limit").lower(),
            confirm_order_expires_minutes=_int("CONFIRM_ORDER_EXPIRES_MINUTES", 15),
            max_entry_price_deviation_pct=_float("MAX_ENTRY_PRICE_DEVIATION_PCT", 0.003),

            gate_api_key_rw=_str("GATE_API_KEY_RW", ""),
            gate_api_secret_rw=_str("GATE_API_SECRET_RW", ""),

            live_whitelist=_parse_whitelist(_str("LIVE_WHITELIST", "BTC/USDT:USDT")),
            max_live_equity_usdt=_float("MAX_LIVE_EQUITY_USDT", 20.0),
            min_live_balance_usdt=_float("MIN_LIVE_BALANCE_USDT", 10.0),
            max_live_risk_per_trade=_float("MAX_LIVE_RISK_PER_TRADE", 0.002),
            max_live_daily_loss_usdt=_float("MAX_LIVE_DAILY_LOSS_USDT", 2.0),
            max_live_open_positions=_int("MAX_LIVE_OPEN_POSITIONS", 1),
            hard_max_leverage=_float("HARD_MAX_LEVERAGE", 3.0),
            max_allowed_notional_usdt=_float("MAX_ALLOWED_NOTIONAL_USDT", 30.0),

            kill_switch=_bool("KILL_SWITCH", False),
            close_positions_on_kill_switch=_bool("CLOSE_POSITIONS_ON_KILL_SWITCH", False),

            confirm_mode_proven=_bool("CONFIRM_MODE_PROVEN", False),

            live_reconcile_interval_minutes=_int("LIVE_RECONCILE_INTERVAL_MINUTES", 5),
        )


def _parse_whitelist(raw: str) -> tuple[str, ...]:
    """Парсит LIVE_WHITELIST="BTC/USDT:USDT,ETH/USDT:USDT" → tuple."""
    items = tuple(s.strip() for s in raw.split(",") if s.strip())
    return items or ("BTC/USDT:USDT",)
