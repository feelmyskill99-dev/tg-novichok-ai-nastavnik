"""Reconciliation: периодически сверяем live_trades.json с реальным состоянием Gate.io.

Решает:
- entry order заполнился → выставить TP/SL
- TP сработал → отменить SL и закрыть сделку
- SL сработал → отменить TP и закрыть сделку
- позиция закрыта вручную / руками владельца → пометить manual_intervention,
  больше не управлять
- позиция открыта, но нет SL → emergency: попытка поставить SL или закрыть позицию
- ордер на бирже отсутствует, а локально active → пометить failed
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from .confirm_broker import ConfirmBroker
from .confirm_models import (
    STATUS_ACTIVE,
    STATUS_CLOSED_ERROR,
    STATUS_CLOSED_MANUAL,
    STATUS_CLOSED_STOP_LOSS,
    STATUS_CLOSED_TAKE_PROFIT,
    STATUS_ENTRY_FILLED,
    STATUS_ENTRY_ORDER_SUBMITTED,
    STATUS_FAILED,
    STATUS_MANUAL_INTERVENTION,
    STATUS_PROTECTION_ORDERS_SUBMITTED,
    ConfirmTrade,
    LiveTradeJournal,
    LiveTradesStore,
)
from .config import TradingConfig
from .exchange import ExchangeError, GateRWClient


log = logging.getLogger("trading.reconcile")


AlertFn = Callable[[str], Awaitable[None]]   # async (text) → None — алёрт владельцу


async def reconcile_live_state(
    cfg: TradingConfig,
    *,
    exchange: GateRWClient,
    live_store: LiveTradesStore,
    journal: LiveTradeJournal,
    broker: ConfirmBroker,
    alert: AlertFn,
) -> dict:
    """Главный reconciliation-цикл. Возвращает summary dict для логов."""
    summary = {"checked": 0, "transitioned": [], "alerts": []}

    trades = live_store.load()
    # Только не-конечные:
    actionable = [t for t in trades if t.status in (
        STATUS_ENTRY_ORDER_SUBMITTED,
        STATUS_ENTRY_FILLED,
        STATUS_PROTECTION_ORDERS_SUBMITTED,
        STATUS_ACTIVE,
    )]

    if not actionable:
        return summary

    # Кэшируем positions/orders по символам, чтобы не дёргать API на каждый трейд.
    symbols = sorted({t.symbol for t in actionable})
    positions_by_symbol: dict[str, list[dict]] = {}
    orders_by_symbol: dict[str, list[dict]] = {}
    try:
        for sym in symbols:
            positions_by_symbol[sym] = exchange.get_open_positions([sym])
            orders_by_symbol[sym] = exchange.get_open_orders(sym)
    except ExchangeError as e:
        msg = f"reconcile: ошибка получения данных биржи: {e}"
        log.warning(msg)
        await alert(f"<b>⚠️ [RECONCILE]</b> {msg}")
        summary["alerts"].append(str(e))
        return summary

    for trade in actionable:
        summary["checked"] += 1
        try:
            await _reconcile_one(
                trade,
                cfg=cfg,
                exchange=exchange,
                live_store=live_store,
                journal=journal,
                broker=broker,
                positions=positions_by_symbol.get(trade.symbol, []),
                open_orders=orders_by_symbol.get(trade.symbol, []),
                alert=alert,
                summary=summary,
            )
        except Exception as e:
            log.exception("reconcile per-trade crashed: %s", e)
            await alert(f"<b>⚠️ [RECONCILE]</b> trade {trade.id}: {e}")
            summary["alerts"].append(f"{trade.id}: {e}")

    return summary


async def _reconcile_one(
    trade: ConfirmTrade,
    *,
    cfg: TradingConfig,
    exchange: GateRWClient,
    live_store: LiveTradesStore,
    journal: LiveTradeJournal,
    broker: ConfirmBroker,
    positions: list[dict],
    open_orders: list[dict],
    alert: AlertFn,
    summary: dict,
) -> None:
    has_position = _has_position_for(positions, trade)
    sl_active = _order_active(open_orders, trade.sl_order_id)
    tp_active = _order_active(open_orders, trade.tp_order_id)
    entry_active = _order_active(open_orders, trade.entry_order_id)

    # === case 1: ждём fill entry ордера ===
    if trade.status == STATUS_ENTRY_ORDER_SUBMITTED:
        if has_position:
            # Entry заполнился — переходим в entry_filled и сразу выставляем protection.
            trade.transition(STATUS_ENTRY_FILLED, note="entry filled (reconcile)")
            trade.filled_at = _now_iso()
            # Берём фактическую цену открытия из позиции, если можем.
            avg = _avg_entry_price(positions, trade)
            if avg is not None:
                trade.fill_price = avg
            live_store.upsert(trade)
            journal.log_trade_event(trade, "entry_filled")
            summary["transitioned"].append(f"{trade.id}: entry_filled")

            t2, msg = broker.submit_protection_orders(trade.id)
            await alert(f"<b>📒 [RECONCILE]</b> entry filled, {msg}")
            return

        if not entry_active:
            # ордера нет, позиции нет — кто-то отменил вручную или биржа отвергла.
            trade.transition(STATUS_FAILED, note="entry order vanished (no position)")
            live_store.upsert(trade)
            journal.log_trade_event(trade, "entry_vanished")
            summary["transitioned"].append(f"{trade.id}: failed (entry vanished)")
            await alert(f"<b>⚠️ [RECONCILE]</b> entry ордер пропал без позиции (id={trade.id})")
            return

        # entry order ещё висит — проверяем, не пора ли отменять (orderdeadline).
        if _order_age_minutes(trade.submitted_at) > cfg.confirm_order_expires_minutes:
            t2, msg = broker.cancel_entry_order(trade.id, reason="order expired by deadline")
            await alert(f"<b>📒 [RECONCILE]</b> entry expired: {msg}")
            return
        return

    # === case 2: protection submitted / active ===
    if trade.status in (STATUS_PROTECTION_ORDERS_SUBMITTED, STATUS_ACTIVE, STATUS_ENTRY_FILLED):
        if not has_position:
            # позиция закрыта на бирже. Определяем кем: TP / SL / вручную.
            if not tp_active and trade.tp_order_id and _order_was_filled(exchange, trade.tp_order_id, trade.symbol):
                trade.close_reason = "take_profit"
                trade.transition(STATUS_CLOSED_TAKE_PROFIT, note="TP filled")
            elif not sl_active and trade.sl_order_id and _order_was_filled(exchange, trade.sl_order_id, trade.symbol):
                trade.close_reason = "stop_loss"
                trade.transition(STATUS_CLOSED_STOP_LOSS, note="SL filled")
            else:
                trade.close_reason = "manual_or_unknown"
                trade.transition(STATUS_CLOSED_MANUAL, note="позиция исчезла, причина не TP/SL")

            trade.closed_at = _now_iso()
            # Cancel дочерний ордер, который ещё может болтаться:
            for oid in (trade.tp_order_id, trade.sl_order_id):
                if oid and _order_active(open_orders, oid):
                    try:
                        exchange.cancel_order(oid, trade.symbol)
                    except ExchangeError as e:
                        log.warning("cancel leftover order failed: %s", e)

            live_store.upsert(trade)
            journal.log_trade_event(trade, "trade_closed", {
                "close_reason": trade.close_reason,
            })
            summary["transitioned"].append(f"{trade.id}: closed_{trade.close_reason}")
            await alert(f"<b>📒 [RECONCILE]</b> сделка {trade.id} закрыта: {trade.close_reason}")
            return

        # позиция есть. Проверяем, что SL и TP всё ещё активны.
        if not sl_active:
            # КРИТИЧНО: позиция без стопа. Пытаемся восстановить или закрыть.
            await alert(
                f"<b>🚨 [RECONCILE]</b> позиция {trade.symbol} БЕЗ STOP_LOSS! "
                f"trade {trade.id}, пытаюсь восстановить."
            )
            try:
                sl_order = exchange.place_stop_loss(
                    symbol=trade.symbol, direction=trade.direction,
                    amount=trade.position_size, stop_price=trade.stop_loss,
                )
                trade.sl_order_id = str(sl_order.get("id") or "")
                if trade.sl_order_id:
                    trade.notes.append(f"{_now_iso()} SL восстановлен (reconcile)")
                    live_store.upsert(trade)
                    journal.log_trade_event(trade, "sl_restored")
                    return
                raise ExchangeError("SL вернулся без id")
            except ExchangeError as e:
                # SL восстановить не удалось — закрываем позицию по рынку.
                try:
                    exchange.close_position_market(
                        symbol=trade.symbol, direction=trade.direction, amount=trade.position_size,
                    )
                except ExchangeError as e2:
                    log.error("emergency close after SL restore fail: %s", e2)
                trade.transition(STATUS_CLOSED_ERROR, note=f"SL restore fail → emergency close: {e}")
                trade.close_reason = "emergency_no_sl"
                trade.closed_at = _now_iso()
                live_store.upsert(trade)
                journal.log_trade_event(trade, "sl_restore_emergency_close", {"error": str(e)})
                await alert(f"<b>🚨 [RECONCILE]</b> SL не восстановился, позиция закрыта аварийно: {e}")
                return

        # позиция и SL ок. Проверим manual intervention: position size изменилось?
        if _position_size_mismatch(positions, trade):
            trade.transition(
                STATUS_MANUAL_INTERVENTION,
                note="position size != plan; ручное вмешательство",
            )
            live_store.upsert(trade)
            journal.log_trade_event(trade, "manual_intervention_detected")
            await alert(
                f"<b>⚠️ [RECONCILE]</b> вмешательство в позицию {trade.symbol} (trade {trade.id}). "
                "Бот больше НЕ управляет этой сделкой. Все действия вручную."
            )
            summary["transitioned"].append(f"{trade.id}: manual_intervention")
        return


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _has_position_for(positions: list[dict], trade: ConfirmTrade) -> bool:
    for p in positions:
        if p.get("symbol") != trade.symbol:
            continue
        contracts = _to_float(p.get("contracts") or p.get("contractSize"))
        if contracts is None or contracts <= 0:
            continue
        side = (p.get("side") or "").lower()
        # gate.io futures: side = 'long' / 'short'
        if side == trade.direction:
            return True
    return False


def _avg_entry_price(positions: list[dict], trade: ConfirmTrade) -> Optional[float]:
    for p in positions:
        if p.get("symbol") == trade.symbol:
            v = _to_float(p.get("entryPrice") or p.get("averageEntryPrice"))
            if v is not None:
                return v
    return None


def _position_size_mismatch(positions: list[dict], trade: ConfirmTrade, *, tolerance: float = 0.05) -> bool:
    """Проверка: совпадает ли размер позиции с нашим планом (с допуском)."""
    for p in positions:
        if p.get("symbol") != trade.symbol:
            continue
        contracts = _to_float(p.get("contracts"))
        if contracts is None or trade.position_size <= 0:
            return False
        rel = abs(contracts - trade.position_size) / trade.position_size
        return rel > tolerance
    return False


def _order_active(open_orders: list[dict], order_id: str | None) -> bool:
    if not order_id:
        return False
    for o in open_orders:
        if str(o.get("id") or "") == order_id:
            return True
    return False


def _order_was_filled(exchange: GateRWClient, order_id: str, symbol: str) -> bool:
    try:
        o = exchange.get_order(order_id, symbol)
    except ExchangeError:
        return False
    status = (o.get("status") or "").lower()
    return status in ("closed", "filled")


def _to_float(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _order_age_minutes(submitted_at: str | None) -> float:
    if not submitted_at:
        return 0.0
    try:
        ts = datetime.fromisoformat(submitted_at.replace("Z", "+00:00"))
    except Exception:
        return 0.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(tz=timezone.utc) - ts).total_seconds() / 60.0


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
