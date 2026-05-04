"""ConfirmBroker — управление жизненным циклом confirm-сделки.

Никогда не ставит ордер без явного approve_trade() от пользователя.
На каждом критическом шаге проверяет safety и kill_switch.
Если SL не удалось поставить после entry — немедленно отменяет / закрывает позицию.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import TradingConfig
from .confirm_models import (
    STATUS_ACTIVE,
    STATUS_APPROVED,
    STATUS_AWAITING_CONFIRMATION,
    STATUS_CANCELLED,
    STATUS_CLOSED_ERROR,
    STATUS_ENTRY_FILLED,
    STATUS_ENTRY_ORDER_SUBMITTED,
    STATUS_EXPIRED_CONFIRMATION,
    STATUS_FAILED,
    STATUS_PROTECTION_ORDERS_SUBMITTED,
    STATUS_REJECTED,
    ConfirmTrade,
    ConfirmTradesStore,
    LiveTradeJournal,
    LiveTradesStore,
    today_realized_pnl_usdt,
)
from .exchange import ExchangeError, GateRWClient
from .safety import (
    SafetyVerdict,
    can_use_confirm_mode,
    cap_leverage,
    check_entry_price_deviation,
    evaluate_confirm_plan,
    is_confirmation_expired,
)
from .setup_detector import Setup


log = logging.getLogger("trading.confirm_broker")


class ConfirmBrokerError(RuntimeError):
    """Любая логическая ошибка ConfirmBroker (не биржи). Сопровождается сообщением."""


class ConfirmBroker:
    def __init__(
        self,
        cfg: TradingConfig,
        *,
        confirm_store: ConfirmTradesStore,
        live_store: LiveTradesStore,
        live_journal: LiveTradeJournal,
        exchange: Optional[GateRWClient] = None,
    ):
        self.cfg = cfg
        self.confirm_store = confirm_store
        self.live_store = live_store
        self.live_journal = live_journal
        # exchange может быть None — например, при создании плана без RW-ключей.
        # Для approve экземпляр обязателен; провереам в _require_exchange().
        self.exchange = exchange

    # ---------------------------------------------------------------------
    # public API
    # ---------------------------------------------------------------------

    def create_confirm_plan(
        self,
        setup: Setup,
        *,
        market_snapshot: dict,
        real_balance_usdt: float,
        open_positions_count: int,
        today_pnl_usdt: float,
    ) -> tuple[Optional[ConfirmTrade], SafetyVerdict]:
        """Создаёт план + safety-вердикт. План сохраняется только если safety.ok.

        Возвращает (trade_or_None, verdict).
        """
        symbol = self.cfg.default_symbol
        requested_lev = cap_leverage(self.cfg, self.cfg.max_leverage)

        verdict = evaluate_confirm_plan(
            self.cfg,
            symbol=symbol,
            direction=setup.direction or "long",
            entry=setup.entry or 0.0,
            stop_loss=setup.stop_loss or 0.0,
            take_profit=setup.take_profit or 0.0,
            requested_leverage=requested_lev,
            real_balance_usdt=real_balance_usdt,
            open_positions_count=open_positions_count,
            today_realized_pnl_usdt=today_pnl_usdt,
            market_data_available=True,
        )
        if not verdict.ok:
            return None, verdict

        trade = ConfirmTrade.new(
            symbol=symbol,
            direction=setup.direction or "long",
            entry=setup.entry or 0.0,
            stop_loss=setup.stop_loss or 0.0,
            take_profit=setup.take_profit or 0.0,
            leverage=verdict.effective_leverage,
            position_size=verdict.position_size,
            notional_usdt=verdict.notional_usdt,
            risk_amount_usdt=verdict.risk_amount_usdt,
            rr=setup.rr or 0.0,
            rationale=_rationale(setup),
            margin_mode="isolated",
            safety_summary={
                "whitelist": "OK" if symbol in self.cfg.live_whitelist else "FAIL",
                "leverage_cap": f"OK (eff {verdict.effective_leverage})",
                "daily_loss": f"OK (today {today_pnl_usdt:+.2f})",
                "open_positions": f"OK ({open_positions_count}/{self.cfg.max_live_open_positions})",
                "sl_tp": "OK",
                "min_balance": f"OK (balance {real_balance_usdt:.2f})",
            },
        )
        trade.transition(STATUS_AWAITING_CONFIRMATION, note="ждём кнопки владельца")
        trade.awaiting_since = trade.last_status_change_at
        self.confirm_store.upsert(trade)
        self.live_journal.log_trade_event(trade, "confirm_plan_created")
        return trade, verdict

    def attach_message_id(self, trade_id: str, message_id: int) -> None:
        """После отправки кнопочного сообщения сохраняем message_id, чтобы потом отредактировать."""
        t = self.confirm_store.find(trade_id)
        if not t:
            return
        t.confirm_message_id = message_id
        self.confirm_store.upsert(t)

    def reject_trade(self, trade_id: str, *, reason: str = "owner pressed reject") -> ConfirmTrade | None:
        t = self.confirm_store.find(trade_id)
        if t is None:
            return None
        if t.status != STATUS_AWAITING_CONFIRMATION:
            return t  # idempotent: уже не в ожидании — ничего не делаем
        t.transition(STATUS_REJECTED, note=reason)
        t.decided_at = t.last_status_change_at
        self.confirm_store.upsert(t)
        self.live_journal.log_trade_event(t, "confirm_rejected", {"reason": reason})
        return t

    def expire_pending_confirmations(self) -> list[ConfirmTrade]:
        """Помечает все awaiting_confirmation, которые висят дольше CONFIRM_TIMEOUT_MINUTES."""
        expired = []
        for t in self.confirm_store.pending():
            if is_confirmation_expired(self.cfg, created_at_iso=t.created_at):
                t.transition(STATUS_EXPIRED_CONFIRMATION, note="истёк CONFIRM_TIMEOUT_MINUTES")
                t.decided_at = t.last_status_change_at
                self.confirm_store.upsert(t)
                self.live_journal.log_trade_event(t, "confirm_expired")
                expired.append(t)
        return expired

    def approve_trade(
        self,
        trade_id: str,
        *,
        real_balance_usdt: float,
        open_positions_count: int,
        today_pnl_usdt: float,
    ) -> tuple[ConfirmTrade | None, str]:
        """Главный путь: повторно прогоняем safety + проверка цены + entry + protection.

        Возвращает (trade, message). message — короткое объяснение результата
        для DM владельцу.
        """
        # 0. Гейт confirm-mode
        ok, why = can_use_confirm_mode(self.cfg)
        if not ok:
            return None, f"confirm mode не активен: {why}"

        t = self.confirm_store.find(trade_id)
        if t is None:
            return None, "сделка не найдена"
        if t.status == STATUS_REJECTED:
            return t, "сделка уже отклонена"
        if t.status == STATUS_EXPIRED_CONFIRMATION:
            return t, "сделка уже истекла"
        if t.status != STATUS_AWAITING_CONFIRMATION:
            return t, f"сделка в статусе {t.status}, approve невозможен"

        # 1. Истёк ли confirm-таймаут прямо сейчас
        if is_confirmation_expired(self.cfg, created_at_iso=t.created_at):
            t.transition(STATUS_EXPIRED_CONFIRMATION, note="истёк к моменту нажатия")
            t.decided_at = t.last_status_change_at
            self.confirm_store.upsert(t)
            self.live_journal.log_trade_event(t, "confirm_expired_on_approve")
            return t, "confirm timeout истёк к моменту нажатия"

        ex = self._require_exchange()

        # 2. Повторный safety-чек на актуальном балансе
        verdict = evaluate_confirm_plan(
            self.cfg,
            symbol=t.symbol,
            direction=t.direction,
            entry=t.entry,
            stop_loss=t.stop_loss,
            take_profit=t.take_profit,
            requested_leverage=t.leverage,
            real_balance_usdt=real_balance_usdt,
            open_positions_count=open_positions_count,
            today_realized_pnl_usdt=today_pnl_usdt,
            market_data_available=True,
        )
        if not verdict.ok:
            t.transition(STATUS_REJECTED, note=f"safety re-check failed: {'; '.join(verdict.reasons)}")
            t.decided_at = t.last_status_change_at
            self.confirm_store.upsert(t)
            self.live_journal.log_trade_event(t, "confirm_rejected_safety", {"reasons": verdict.reasons})
            return t, "safety re-check не прошёл: " + "; ".join(verdict.reasons)

        # 3. Проверка отклонения цены
        try:
            current_price = ex.get_last_price(t.symbol)
        except ExchangeError as e:
            t.transition(STATUS_FAILED, note=f"fetch_ticker: {e}")
            self.confirm_store.upsert(t)
            self.live_journal.log_trade_event(t, "approve_failed", {"error": str(e)})
            return t, f"не удалось получить цену: {e}"

        ok_dev, deviation = check_entry_price_deviation(
            self.cfg, plan_entry=t.entry, current_price=current_price,
        )
        if not ok_dev:
            t.transition(
                STATUS_REJECTED,
                note=f"price deviation {deviation*100:.2f}% > {self.cfg.max_entry_price_deviation_pct*100:.2f}%",
            )
            t.decided_at = t.last_status_change_at
            self.confirm_store.upsert(t)
            self.live_journal.log_trade_event(t, "confirm_rejected_deviation",
                                              {"plan_entry": t.entry, "current_price": current_price,
                                               "deviation_pct": deviation})
            return t, (f"цена ушла от плана: {deviation*100:.2f}% > порога "
                       f"{self.cfg.max_entry_price_deviation_pct*100:.2f}%")

        # 4. Approved — переходим к выставлению entry
        t.transition(STATUS_APPROVED, note="owner pressed approve")
        t.decided_at = t.last_status_change_at
        self.confirm_store.upsert(t)
        self.live_journal.log_trade_event(t, "confirm_approved")

        try:
            ex.set_leverage_isolated(t.symbol, t.leverage)
        except ExchangeError as e:
            t.transition(STATUS_FAILED, note=f"set_leverage: {e}")
            self.confirm_store.upsert(t)
            self.live_journal.log_trade_event(t, "leverage_failed", {"error": str(e)})
            return t, f"не удалось выставить плечо: {e}"

        try:
            entry_order = ex.place_limit_entry(
                symbol=t.symbol, direction=t.direction,
                amount=t.position_size, price=t.entry,
            )
        except ExchangeError as e:
            t.transition(STATUS_FAILED, note=f"entry order failed: {e}")
            self.confirm_store.upsert(t)
            self.live_journal.log_trade_event(t, "entry_failed", {"error": str(e)})
            return t, f"не удалось выставить entry: {e}"

        order_id = str(entry_order.get("id") or "")
        if not order_id:
            t.transition(STATUS_FAILED, note="entry order without id")
            self.confirm_store.upsert(t)
            self.live_journal.log_trade_event(t, "entry_no_id")
            return t, "биржа вернула entry order без id"

        t.entry_order_id = order_id
        t.submitted_at = _now_iso()
        t.transition(STATUS_ENTRY_ORDER_SUBMITTED, note=f"entry id={order_id}")
        self.confirm_store.upsert(t)
        self.live_store.upsert(t)
        self.live_journal.log_trade_event(t, "entry_submitted")

        return t, "entry ордер выставлен. TP/SL будут поставлены после исполнения (см. reconcile)."

    def submit_protection_orders(self, trade_id: str) -> tuple[ConfirmTrade | None, str]:
        """После того, как entry заполнен, ставим SL и TP.

        Если SL не удалось поставить — закрываем позицию по рынку (no-SL запрещён).
        """
        t = self.live_store.find(trade_id) or self.confirm_store.find(trade_id)
        if t is None:
            return None, "сделка не найдена"
        if t.status != STATUS_ENTRY_FILLED:
            return t, f"protection submission ожидает entry_filled, текущий: {t.status}"

        ex = self._require_exchange()

        # 1. SL первым — он критический
        try:
            sl_order = ex.place_stop_loss(
                symbol=t.symbol, direction=t.direction,
                amount=t.position_size, stop_price=t.stop_loss,
            )
            t.sl_order_id = str(sl_order.get("id") or "")
        except ExchangeError as e:
            # КРИТИЧНО: позиция открыта, SL не встал. Закрываем по рынку.
            log.error("SL placement failed → закрываем позицию по рынку: %s", e)
            try:
                ex.close_position_market(symbol=t.symbol, direction=t.direction, amount=t.position_size)
                t.transition(STATUS_CLOSED_ERROR, note=f"SL fail → emergency close: {e}")
            except ExchangeError as e2:
                t.transition(STATUS_FAILED, note=f"SL fail + emergency close fail: {e}; {e2}")
            self.live_store.upsert(t)
            self.live_journal.log_trade_event(t, "sl_failed_emergency_close", {"error": str(e)})
            return t, f"SL не встал, позиция закрыта аварийно: {e}"

        if not t.sl_order_id:
            # тоже отдельный кейс: id пустой → ненадёжно, лучше закрыть
            try:
                ex.close_position_market(symbol=t.symbol, direction=t.direction, amount=t.position_size)
            except ExchangeError:
                pass
            t.transition(STATUS_CLOSED_ERROR, note="SL без id → emergency close")
            self.live_store.upsert(t)
            self.live_journal.log_trade_event(t, "sl_no_id_emergency_close")
            return t, "SL вернулся без id, позиция закрыта аварийно"

        # 2. TP
        try:
            tp_order = ex.place_take_profit(
                symbol=t.symbol, direction=t.direction,
                amount=t.position_size, take_price=t.take_profit,
            )
            t.tp_order_id = str(tp_order.get("id") or "")
        except ExchangeError as e:
            # TP не встал — это менее критично, но всё равно отказываемся управлять.
            # Отменяем SL и закрываем позицию (полугосударственное состояние).
            log.error("TP placement failed → откат позиции: %s", e)
            try:
                if t.sl_order_id:
                    ex.cancel_order(t.sl_order_id, t.symbol)
                ex.close_position_market(symbol=t.symbol, direction=t.direction, amount=t.position_size)
            except ExchangeError:
                pass
            t.transition(STATUS_CLOSED_ERROR, note=f"TP fail → cancel SL + emergency close: {e}")
            self.live_store.upsert(t)
            self.live_journal.log_trade_event(t, "tp_failed_emergency_close", {"error": str(e)})
            return t, f"TP не встал, позиция закрыта аварийно: {e}"

        # 3. оба встали — переходим в active
        t.transition(STATUS_PROTECTION_ORDERS_SUBMITTED, note=f"sl={t.sl_order_id}, tp={t.tp_order_id}")
        self.live_store.upsert(t)
        # active выставит reconcile, когда увидит, что оба активны и позиция открыта.
        t.transition(STATUS_ACTIVE, note="protection orders live")
        self.live_store.upsert(t)
        self.live_journal.log_trade_event(t, "protection_submitted")
        return t, "TP/SL выставлены, сделка active"

    def cancel_entry_order(self, trade_id: str, *, reason: str = "manual cancel") -> tuple[ConfirmTrade | None, str]:
        """Отменяет entry ордер, если он ещё не исполнился."""
        t = self.live_store.find(trade_id) or self.confirm_store.find(trade_id)
        if t is None:
            return None, "сделка не найдена"
        if t.status != STATUS_ENTRY_ORDER_SUBMITTED:
            return t, f"cancel доступен только для entry_order_submitted, статус: {t.status}"
        ex = self._require_exchange()
        try:
            if t.entry_order_id:
                ex.cancel_order(t.entry_order_id, t.symbol)
        except ExchangeError as e:
            t.transition(STATUS_FAILED, note=f"cancel failed: {e}")
            self.live_store.upsert(t)
            self.live_journal.log_trade_event(t, "cancel_failed", {"error": str(e)})
            return t, f"не удалось отменить: {e}"
        t.transition(STATUS_CANCELLED, note=reason)
        self.live_store.upsert(t)
        self.live_journal.log_trade_event(t, "entry_cancelled", {"reason": reason})
        return t, "entry ордер отменён"

    # ---------------------------------------------------------------------
    # internal
    # ---------------------------------------------------------------------

    def _require_exchange(self) -> GateRWClient:
        if self.exchange is None:
            raise ConfirmBrokerError(
                "Exchange client не инициализирован (нужны GATE_API_KEY_RW/GATE_API_SECRET_RW)"
            )
        return self.exchange


def _rationale(setup: Setup) -> str:
    facts = setup.rationale_facts or {}
    bits = []
    if facts.get("trend"):
        bits.append(f"тренд: {facts['trend']}")
    if facts.get("rsi") is not None:
        bits.append(f"RSI {facts['rsi']}")
    if facts.get("rr") is not None:
        bits.append(f"RR {facts['rr']}")
    return "; ".join(bits) if bits else "rule-based setup"


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
