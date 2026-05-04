"""Высокоуровневые входы Stage 8a для bot.py.

Все функции — async. Никаких глобальных state-объектов; bot.py передаёт зависимости.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Awaitable, Callable, Optional

from .confirm_broker import ConfirmBroker
from .confirm_format import (
    confirm_buttons_payload,
    format_confirm_message,
    format_kill_switch_status,
)
from .confirm_models import (
    STATUS_AWAITING_CONFIRMATION,
    STATUS_CLOSED_TAKE_PROFIT,
    STATUS_CLOSED_STOP_LOSS,
    ConfirmTradesStore,
    LiveTradeJournal,
    LiveTradesStore,
    today_realized_pnl_usdt,
)
from .config import TradingConfig
from .exchange import ExchangeError, GateRWClient
from .market_source import TradingMarket
from .reconcile import reconcile_live_state
from .risk import RiskChecker
from .safety import (
    can_use_confirm_mode,
    can_use_live_mode,
    evaluate_confirm_plan,
)
from .setup_detector import RuleBasedSetupDetector


log = logging.getLogger("trading.confirm_orchestrator")


# Колбэки от bot.py
SendDM = Callable[[str], Awaitable[None]]                              # async (text)
SendButtons = Callable[[str, dict], Awaitable[Optional[int]]]          # async (text, inline_keyboard) → message_id


# =============================================================================
# build_broker — ленивый сборщик ConfirmBroker (с/без exchange)
# =============================================================================

def build_broker(
    cfg: TradingConfig,
    *,
    confirm_path: Path,
    live_path: Path,
    journal_path: Path,
    require_exchange: bool,
) -> tuple[ConfirmBroker, Optional[GateRWClient]]:
    """Собирает ConfirmBroker. Если require_exchange=True — пытается открыть RW-клиент.

    Если RW-ключи пустые при require_exchange=True — возвращает ConfirmBroker
    с exchange=None. Вызывающий код должен проверить и предупредить владельца.
    """
    confirm_store = ConfirmTradesStore(confirm_path)
    live_store = LiveTradesStore(live_path)
    journal = LiveTradeJournal(journal_path)

    exchange: Optional[GateRWClient] = None
    if require_exchange:
        try:
            exchange = GateRWClient(cfg)
        except ExchangeError as e:
            log.warning("RW-клиент не инициализирован: %s", e)
            exchange = None

    broker = ConfirmBroker(
        cfg,
        confirm_store=confirm_store,
        live_store=live_store,
        live_journal=journal,
        exchange=exchange,
    )
    return broker, exchange


# =============================================================================
# entry: confirm-trade-now
# =============================================================================

async def confirm_trade_now(
    *,
    config: TradingConfig,
    confirm_path: Path,
    live_path: Path,
    journal_path: Path,
    send_dm: SendDM,
    send_buttons: SendButtons,
) -> dict:
    """Найти setup → создать confirm-план → отправить кнопки в OWNER.

    Реальный ордер НЕ ставится. Это только подготовка плана + сообщение с кнопками.
    """
    # 0. Гейт confirm-mode (но создавать план разрешаем даже без RW-ключей,
    # чтобы можно было увидеть формат сообщения; approve уже строго проверит).
    if config.kill_switch:
        await send_dm("<b>🛑 [CONFIRM]</b> KILL_SWITCH=true. Новые сделки запрещены.")
        return {"ok": False, "reason": "kill_switch"}

    if config.trading_mode != "confirm":
        await send_dm(
            f"<b>📒 [CONFIRM]</b> TRADING_MODE={config.trading_mode}, не confirm. "
            "План создаётся, но кнопка approve будет отказывать."
        )

    # 1. setup
    market = TradingMarket(config.default_symbol)
    df = market.fetch_ohlcv(config.default_timeframe, limit=300)
    if df is None or len(df) < 50:
        await send_dm("<b>📒 [CONFIRM]</b> рыночные данные недоступны, no_trade.")
        return {"ok": False, "reason": "no market data"}

    detector = RuleBasedSetupDetector(config)
    setup = detector.detect(df)
    if setup.action != "trade":
        await send_dm(f"<b>📒 [CONFIRM]</b> setup нет: {setup.reason}")
        return {"ok": False, "reason": setup.reason}

    # 2. RW-balance
    broker, exchange = build_broker(
        config,
        confirm_path=confirm_path, live_path=live_path, journal_path=journal_path,
        require_exchange=True,
    )

    real_balance = 0.0
    if exchange is not None:
        try:
            real_balance = exchange.get_usdt_futures_balance()
        except ExchangeError as e:
            await send_dm(f"<b>⚠️ [CONFIRM]</b> не удалось прочитать RW-баланс: {e}")
            return {"ok": False, "reason": f"balance: {e}"}

    if real_balance <= 0:
        await send_dm(
            "<b>⚠️ [CONFIRM]</b> RW-баланс не получен или 0. "
            "Проверь GATE_API_KEY_RW и наличие средств в futures-кошельке."
        )

    # 3. open positions / today_pnl
    open_positions_count = 0
    if exchange is not None:
        try:
            open_positions_count = len(exchange.get_open_positions(list(config.live_whitelist)))
        except ExchangeError as e:
            log.warning("get_open_positions failed: %s", e)

    journal_obj = LiveTradeJournal(journal_path)
    today_pnl = today_realized_pnl_usdt(journal_obj)

    # 4. Создаём план через broker (сам прогонит safety)
    plan, verdict = broker.create_confirm_plan(
        setup,
        market_snapshot={},
        real_balance_usdt=real_balance,
        open_positions_count=open_positions_count,
        today_pnl_usdt=today_pnl,
    )

    if plan is None:
        await send_dm(
            "<b>📒 [CONFIRM]</b> план отклонён safety:\n"
            + "\n".join(f"- {r}" for r in verdict.reasons)
        )
        return {"ok": False, "reason": "safety failed", "details": verdict.reasons}

    # 5. Отправляем сообщение с кнопками
    text = format_confirm_message(plan)
    keyboard = confirm_buttons_payload(plan.id)
    try:
        message_id = await send_buttons(text, keyboard)
        if message_id is not None:
            broker.attach_message_id(plan.id, int(message_id))
    except Exception as e:
        log.exception("send confirm message failed: %s", e)
        return {"ok": False, "reason": f"send failed: {e}"}

    return {
        "ok": True,
        "trade_id": plan.id,
        "status": plan.status,
    }


# =============================================================================
# callbacks: approve / reject (вызывается из bot.py при нажатии кнопки)
# =============================================================================

async def handle_approve(
    *,
    config: TradingConfig,
    trade_id: str,
    confirm_path: Path,
    live_path: Path,
    journal_path: Path,
    send_dm: SendDM,
) -> dict:
    """Главный путь: проверки + entry order + переход в entry_order_submitted.

    Protection orders ставит reconcile, когда увидит filled entry.
    """
    if config.kill_switch:
        await send_dm("<b>🛑 [CONFIRM]</b> KILL_SWITCH=true — approve отклонён.")
        return {"ok": False, "reason": "kill_switch"}

    ok, why = can_use_confirm_mode(config)
    if not ok:
        await send_dm(f"<b>📒 [CONFIRM]</b> approve отклонён: {why}")
        return {"ok": False, "reason": why}

    broker, exchange = build_broker(
        config,
        confirm_path=confirm_path, live_path=live_path, journal_path=journal_path,
        require_exchange=True,
    )
    if exchange is None:
        await send_dm("<b>⚠️ [CONFIRM]</b> RW-клиент не инициализирован, approve невозможен.")
        return {"ok": False, "reason": "no exchange"}

    real_balance = 0.0
    try:
        real_balance = exchange.get_usdt_futures_balance()
    except ExchangeError as e:
        await send_dm(f"<b>⚠️ [CONFIRM]</b> RW-баланс недоступен: {e}")
        return {"ok": False, "reason": f"balance: {e}"}

    open_positions_count = 0
    try:
        open_positions_count = len(exchange.get_open_positions(list(config.live_whitelist)))
    except ExchangeError as e:
        log.warning("get_open_positions failed: %s", e)

    journal_obj = LiveTradeJournal(journal_path)
    today_pnl = today_realized_pnl_usdt(journal_obj)

    trade, msg = broker.approve_trade(
        trade_id,
        real_balance_usdt=real_balance,
        open_positions_count=open_positions_count,
        today_pnl_usdt=today_pnl,
    )
    await send_dm(f"<b>📒 [CONFIRM approve]</b> {msg}")
    return {"ok": trade is not None, "status": trade.status if trade else None, "msg": msg}


async def handle_reject(
    *,
    config: TradingConfig,
    trade_id: str,
    confirm_path: Path,
    live_path: Path,
    journal_path: Path,
    send_dm: SendDM,
) -> dict:
    broker, _ = build_broker(
        config,
        confirm_path=confirm_path, live_path=live_path, journal_path=journal_path,
        require_exchange=False,
    )
    trade = broker.reject_trade(trade_id, reason="owner pressed reject")
    if trade is None:
        await send_dm("<b>📒 [CONFIRM reject]</b> сделка не найдена.")
        return {"ok": False, "reason": "not found"}
    await send_dm(f"<b>📒 [CONFIRM reject]</b> сделка {trade.id} отклонена.")
    return {"ok": True, "status": trade.status}


# =============================================================================
# expire / reconcile / kill-switch-status
# =============================================================================

async def expire_confirmations(
    *,
    config: TradingConfig,
    confirm_path: Path,
    live_path: Path,
    journal_path: Path,
    send_dm: SendDM,
) -> dict:
    broker, _ = build_broker(
        config,
        confirm_path=confirm_path, live_path=live_path, journal_path=journal_path,
        require_exchange=False,
    )
    expired = broker.expire_pending_confirmations()
    if expired:
        for t in expired:
            await send_dm(
                f"<b>📒 [CONFIRM expire]</b> Идея {t.id} ({t.symbol} {t.direction}) "
                "отменена: истёк таймаут подтверждения."
            )
    return {"expired_count": len(expired), "ids": [t.id for t in expired]}


async def live_reconcile(
    *,
    config: TradingConfig,
    confirm_path: Path,
    live_path: Path,
    journal_path: Path,
    send_dm: SendDM,
) -> dict:
    broker, exchange = build_broker(
        config,
        confirm_path=confirm_path, live_path=live_path, journal_path=journal_path,
        require_exchange=True,
    )
    if exchange is None:
        await send_dm("<b>⚠️ [RECONCILE]</b> RW-клиент не инициализирован — reconcile пропущен.")
        return {"ok": False, "reason": "no exchange"}

    summary = await reconcile_live_state(
        config,
        exchange=exchange,
        live_store=broker.live_store,
        journal=broker.live_journal,
        broker=broker,
        alert=send_dm,
    )
    return {"ok": True, **summary}


async def kill_switch_status_text(
    *,
    config: TradingConfig,
    confirm_path: Path,
    live_path: Path,
    journal_path: Path,
) -> str:
    confirm_store = ConfirmTradesStore(confirm_path)
    live_store = LiveTradesStore(live_path)
    journal = LiveTradeJournal(journal_path)

    pending = confirm_store.pending()
    open_local = live_store.active_or_pending_live()
    today_pnl = today_realized_pnl_usdt(journal)

    open_exchange_positions = 0
    extra: list[str] = []
    if config.gate_api_key_rw and config.gate_api_secret_rw:
        try:
            ex = GateRWClient(config)
            positions = ex.get_open_positions(list(config.live_whitelist))
            open_exchange_positions = len(positions)
        except ExchangeError as e:
            extra.append(f"не удалось прочитать позиции с биржи: {e}")
    else:
        extra.append("RW-ключи не заданы — статус позиций с биржи неизвестен.")

    # warn о live-mode
    live_ok, live_why = can_use_live_mode(config)
    if config.live_trading_enabled and not config.confirm_mode_proven:
        extra.append("LIVE_TRADING_ENABLED=true, но CONFIRM_MODE_PROVEN=false → live ИГНОРИРУЕТСЯ.")
    if not live_ok and config.trading_mode == "live":
        extra.append(f"live mode заблокирован: {live_why}")

    return format_kill_switch_status(
        kill_switch=config.kill_switch,
        open_live_trades=len(open_local),
        open_exchange_positions=open_exchange_positions,
        pending_confirmations=len(pending),
        today_pnl_usdt=today_pnl,
        extra_warnings=extra,
    )
