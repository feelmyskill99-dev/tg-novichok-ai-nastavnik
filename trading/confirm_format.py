"""HTML-форматирование сообщений confirm-режима для OWNER_CHAT_ID.

Inline-кнопки:
  [✅ Открыть]  → callback_data = confirm_open:<trade_id>
  [❌ Отклонить] → callback_data = confirm_reject:<trade_id>
"""

from __future__ import annotations

import html
from typing import Iterable

from .confirm_models import ConfirmTrade


CONFIRM_DISCLAIMER = (
    "Это не финансовый совет. Подтверждение означает, что ты сам принимаешь риск. "
    "Реальный ордер на Gate.io будет выставлен только после нажатия кнопки."
)


def _e(s) -> str:
    return html.escape("" if s is None else str(s), quote=False)


def _fmt_price(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:,.2f}"


def format_confirm_message(trade: ConfirmTrade, *, est_margin: float | None = None) -> str:
    safety = trade.safety_summary or {}
    parts: list[str] = []
    parts.append("<b>📒 [CONFIRM REAL TRADE]</b>")
    parts.append("")
    parts.append("⚠️ Это <b>реальная сделка</b> на Gate.io Futures.")
    parts.append("Ордер будет выставлен только после подтверждения.")
    parts.append("")
    parts.append(f"<b>Asset:</b> {_e(trade.symbol)}")
    parts.append(f"<b>Side:</b> {_e(trade.direction)}")
    parts.append(f"<b>Entry:</b> {_fmt_price(trade.entry)}")
    parts.append(f"<b>Stop Loss:</b> {_fmt_price(trade.stop_loss)}")
    parts.append(f"<b>Take Profit:</b> {_fmt_price(trade.take_profit)}")
    parts.append(f"<b>Leverage:</b> x{trade.leverage:.1f}")
    parts.append(f"<b>Margin mode:</b> {_e(trade.margin_mode)}")
    parts.append(f"<b>Risk:</b> {_fmt_price(trade.risk_amount_usdt)} USDT")
    parts.append(f"<b>Notional:</b> {_fmt_price(trade.notional_usdt)} USDT")
    if est_margin is not None:
        parts.append(f"<b>Estimated margin:</b> {_fmt_price(est_margin)} USDT")
    parts.append(f"<b>RR:</b> {trade.rr:.2f}")
    parts.append("")
    parts.append("<b>Reason:</b>")
    parts.append(_e(trade.rationale))
    parts.append("")
    parts.append("<b>Beginner risk:</b>")
    parts.append(_e(_beginner_risk(trade.direction)))
    parts.append("")
    parts.append("<b>Safety checks:</b>")
    parts.append(_format_safety_checks(safety))
    parts.append("")
    parts.append(f"<b>Trade ID:</b> <code>{_e(trade.id)}</code>")
    parts.append(f"<b>Confirm timeout:</b> ждём кнопку, потом expired_confirmation")
    parts.append("")
    parts.append(f"<i>{_e(CONFIRM_DISCLAIMER)}</i>")
    return "\n".join(parts)


def confirm_buttons_payload(trade_id: str) -> dict:
    """Возвращает inline_keyboard в формате aiogram InlineKeyboardMarkup.to_dict-совместимом.

    Мы не зависим от aiogram здесь, чтобы оставить модуль форматирования чистым.
    bot.py соберёт настоящий InlineKeyboardMarkup из этого dict.
    """
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Открыть", "callback_data": f"confirm_open:{trade_id}"},
                {"text": "❌ Отклонить", "callback_data": f"confirm_reject:{trade_id}"},
            ]
        ]
    }


def format_kill_switch_status(
    *,
    kill_switch: bool,
    open_live_trades: int,
    open_exchange_positions: int,
    pending_confirmations: int,
    today_pnl_usdt: float,
    extra_warnings: Iterable[str] = (),
) -> str:
    state = "🛑 ON" if kill_switch else "🟢 OFF"
    parts = [
        "<b>🚦 [KILL SWITCH STATUS]</b>",
        "",
        f"KILL_SWITCH: {state}",
        f"Открытых live-сделок (локально): {open_live_trades}",
        f"Открытых позиций на бирже: {open_exchange_positions}",
        f"Ожидающих подтверждения: {pending_confirmations}",
        f"Realized PnL за сегодня: {today_pnl_usdt:+.4f} USDT",
    ]
    for w in extra_warnings:
        parts.append("")
        parts.append(f"⚠️ {_e(w)}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _format_safety_checks(safety: dict) -> str:
    if not safety:
        return "—"
    lines = []
    for key in ("whitelist", "leverage_cap", "daily_loss", "open_positions", "sl_tp", "min_balance"):
        if key in safety:
            lines.append(f"- {key}: {_e(safety[key])}")
    # дополнительные ключи добавим после стандартных
    for k, v in safety.items():
        if k in ("whitelist", "leverage_cap", "daily_loss", "open_positions", "sl_tp", "min_balance"):
            continue
        lines.append(f"- {_e(k)}: {_e(v)}")
    return "\n".join(lines) if lines else "—"


def _beginner_risk(direction: str) -> str:
    if direction == "long":
        return ("Самая частая ошибка — снять стоп после первого касания и «дать рынку шанс». "
                "Здесь стоп стоит под структурным уровнем не просто так — если он пробит, идея сломана.")
    return ("Шорт против сильного тренда — особенно опасно. "
            "Стоп выше структурного максимума существует именно для этого.")
