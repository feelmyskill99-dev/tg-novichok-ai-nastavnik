"""Форматирование торговых сообщений для DM владельцу.

HTML-safe. Весь user-controlled текст прогоняется через html.escape.
Никакой публикации в канал — это только для owner_chat_id.
"""

from __future__ import annotations

import html

from .backtest import BacktestResult
from .broker import PaperTrade


DISCLAIMER_SHORT = (
    "Учебная paper-сделка. Виртуальная. Не является финансовым советом. "
    "AI-анализ носит ознакомительный характер."
)


def _e(s) -> str:
    return html.escape("" if s is None else str(s), quote=False)


def _fmt_price(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:,.2f}"


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v*100:.2f}%"


def format_trade_plan_dm(
    trade: PaperTrade,
    *,
    equity_usdt: float,
    paper_equity_source: str,
    beginner_mistake: str | None = None,
) -> str:
    """HTML-сообщение с открытой paper-сделкой для владельца.

    `paper_equity_source`: 'real' (снято с Gate.io), 'env' (взят PAPER_EQUITY_USDT),
                           'fallback' (API упал, используем дефолт).
    """
    lines: list[str] = []
    lines.append("<b>📒 [PAPER TRADE] учебная paper-сделка</b>")
    lines.append("")
    lines.append(f"💼 <b>Баланс (paper):</b> {_fmt_price(equity_usdt)} USDT <i>({_e(paper_equity_source)})</i>")
    lines.append(f"📊 <b>Символ:</b> {_e(trade.symbol)}")
    lines.append(f"➡️ <b>Направление:</b> {_e(trade.direction)}")
    lines.append(f"🎯 <b>Entry:</b> {_fmt_price(trade.entry)}")
    lines.append(f"🛑 <b>Stop:</b> {_fmt_price(trade.stop_loss)}")
    lines.append(f"🏁 <b>Take:</b> {_fmt_price(trade.take_profit)}")
    lines.append(f"⚖️ <b>Плечо:</b> x{trade.leverage:.1f}")
    lines.append(f"📏 <b>Размер позиции:</b> {trade.position_size:.6f}")
    lines.append(f"💥 <b>Риск:</b> {_fmt_price(trade.risk_amount_usdt)} USDT ≈ {_fmt_pct(trade.risk_amount_usdt/equity_usdt if equity_usdt else None)}")
    lines.append(f"📐 <b>RR:</b> {trade.rr:.2f}")
    lines.append("")
    lines.append("<b>Почему сделка допустима:</b>")
    lines.append(_e(trade.rationale))
    if beginner_mistake:
        lines.append("")
        lines.append("<b>⚠️ Где здесь может ошибиться новичок:</b>")
        lines.append(_e(beginner_mistake))
    lines.append("")
    lines.append(f"<i>{_e(DISCLAIMER_SHORT)}</i>")
    return "\n".join(lines)


def format_trade_close_dm(trade: PaperTrade) -> str:
    lines: list[str] = []
    lines.append("<b>📒 [PAPER TRADE CLOSED]</b>")
    lines.append("")
    lines.append(f"📊 <b>Символ:</b> {_e(trade.symbol)}")
    lines.append(f"➡️ <b>Направление:</b> {_e(trade.direction)}")
    lines.append(f"🎯 <b>Entry:</b> {_fmt_price(trade.entry)}")
    lines.append(f"🧯 <b>Close:</b> {_fmt_price(trade.close_price)} <i>({_e(trade.close_reason)})</i>")
    pnl = trade.pnl_usdt or 0.0
    r = trade.r_multiple or 0.0
    sign = "+" if pnl >= 0 else ""
    lines.append(f"💰 <b>PnL:</b> {sign}{pnl:.4f} USDT")
    lines.append(f"📐 <b>R:</b> {sign}{r:.2f}")
    lines.append("")
    lines.append(f"<i>{_e(DISCLAIMER_SHORT)}</i>")
    return "\n".join(lines)


def format_backtest_report(result: BacktestResult, *, bars: int, symbol: str) -> str:
    lines: list[str] = []
    lines.append("<b>📊 [PAPER BACKTEST] результат</b>")
    lines.append("")
    lines.append(f"📈 <b>Символ:</b> {_e(symbol)}")
    lines.append(f"🧱 <b>Баров:</b> {bars}")
    lines.append("")
    lines.append(f"🔢 <b>Сделок:</b> {result.total_trades}")
    lines.append(f"🎯 <b>Wins:</b> {result.wins}  |  <b>Losses:</b> {result.losses}")
    lines.append(f"📊 <b>Winrate:</b> {result.winrate*100:.1f}%")
    lines.append(f"🏁 <b>TP:</b> {result.tp_count}  |  🛑 <b>SL:</b> {result.sl_count}  |  ⏳ <b>Expired:</b> {result.expired_count}")
    lines.append(f"🚫 <b>Skipped setups:</b> {result.skipped_setups}")
    lines.append("")
    lines.append(f"💰 <b>Total PnL:</b> {result.total_pnl_usdt:+.4f} USDT")
    lines.append(f"📐 <b>Total R:</b> {result.total_R:+.2f}  |  <b>Avg R:</b> {result.average_R:+.2f}")
    lines.append(f"📉 <b>Max drawdown:</b> {result.max_drawdown:.4f} USDT")
    lines.append("")
    lines.append(f"💼 <b>Initial equity:</b> {result.initial_equity:.2f} USDT")
    lines.append(f"💼 <b>Final equity:</b>   {result.final_paper_equity:.2f} USDT")
    lines.append("")
    lines.append(f"<i>{_e(DISCLAIMER_SHORT)}</i>")
    return "\n".join(lines)
