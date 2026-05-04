"""Paper-trading подсистема: rule-based setup detector, risk checker, paper broker, journal.

Ничего реального не отправляет на биржу. LiveBroker/ConfirmBroker — заглушки.
"""

from .config import TradingConfig, TRADE_PUBLISH_MODES
from .risk import RiskChecker, RiskError
from .setup_detector import RuleBasedSetupDetector, Setup
from .broker import PaperBroker, LiveBroker, PaperTrade, TradePlan
from .journal import TradeJournal
from .backtest import BacktestResult, run_backtest
from .formatting import format_trade_plan_dm, format_trade_close_dm, format_backtest_report
from .balance import fetch_paper_equity
from .market_source import TradingMarket
from .review import TradeReviewGenerator
from .channel_post import format_channel_trade_post, format_owner_dm_review
from .orchestrator import (
    StateHelpers,
    TradeContext,
    scan_for_new_setup,
    tick_open_trades,
    run_trade_now,
    run_paper_backtest,
    run_review_last_trade,
    publish_last_trade,
)
# --- Stage 8a: confirm-mode ---
from .safety import (
    SafetyVerdict,
    can_use_confirm_mode,
    can_use_live_mode,
    cap_leverage,
    cap_equity,
    evaluate_confirm_plan,
    is_confirmation_expired,
)
from .confirm_models import (
    ConfirmTrade,
    ConfirmTradesStore,
    LiveTradesStore,
    LiveTradeJournal,
    today_realized_pnl_usdt,
    STATUS_AWAITING_CONFIRMATION,
    STATUS_APPROVED,
    STATUS_REJECTED,
    STATUS_EXPIRED_CONFIRMATION,
    STATUS_ENTRY_ORDER_SUBMITTED,
    STATUS_ENTRY_FILLED,
    STATUS_ACTIVE,
    STATUS_CLOSED_TAKE_PROFIT,
    STATUS_CLOSED_STOP_LOSS,
    STATUS_CLOSED_MANUAL,
    STATUS_CLOSED_ERROR,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_MANUAL_INTERVENTION,
)
from .exchange import GateRWClient, ExchangeError
from .confirm_broker import ConfirmBroker, ConfirmBrokerError
from .confirm_format import (
    format_confirm_message,
    confirm_buttons_payload,
    format_kill_switch_status,
)
from .confirm_orchestrator import (
    confirm_trade_now,
    handle_approve,
    handle_reject,
    expire_confirmations,
    live_reconcile,
    kill_switch_status_text,
)

__all__ = [
    "TradingConfig",
    "TRADE_PUBLISH_MODES",
    "RiskChecker",
    "RiskError",
    "RuleBasedSetupDetector",
    "Setup",
    "PaperBroker",
    "LiveBroker",
    "PaperTrade",
    "TradePlan",
    "TradeJournal",
    "BacktestResult",
    "run_backtest",
    "format_trade_plan_dm",
    "format_trade_close_dm",
    "format_backtest_report",
    "format_channel_trade_post",
    "format_owner_dm_review",
    "fetch_paper_equity",
    "TradingMarket",
    "TradeReviewGenerator",
    "StateHelpers",
    "TradeContext",
    "scan_for_new_setup",
    "tick_open_trades",
    "run_trade_now",
    "run_paper_backtest",
    "run_review_last_trade",
    "publish_last_trade",
    # Stage 8a
    "SafetyVerdict",
    "can_use_confirm_mode",
    "can_use_live_mode",
    "cap_leverage",
    "cap_equity",
    "evaluate_confirm_plan",
    "is_confirmation_expired",
    "ConfirmTrade",
    "ConfirmTradesStore",
    "LiveTradesStore",
    "LiveTradeJournal",
    "today_realized_pnl_usdt",
    "STATUS_AWAITING_CONFIRMATION",
    "STATUS_APPROVED",
    "STATUS_REJECTED",
    "STATUS_EXPIRED_CONFIRMATION",
    "STATUS_ENTRY_ORDER_SUBMITTED",
    "STATUS_ENTRY_FILLED",
    "STATUS_ACTIVE",
    "STATUS_CLOSED_TAKE_PROFIT",
    "STATUS_CLOSED_STOP_LOSS",
    "STATUS_CLOSED_MANUAL",
    "STATUS_CLOSED_ERROR",
    "STATUS_CANCELLED",
    "STATUS_FAILED",
    "STATUS_MANUAL_INTERVENTION",
    "GateRWClient",
    "ExchangeError",
    "ConfirmBroker",
    "ConfirmBrokerError",
    "format_confirm_message",
    "confirm_buttons_payload",
    "format_kill_switch_status",
    "confirm_trade_now",
    "handle_approve",
    "handle_reject",
    "expire_confirmations",
    "live_reconcile",
    "kill_switch_status_text",
]
