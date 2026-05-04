"""HTML-формат торгового поста для канала.

Используется ТОЛЬКО когда:
- TRADE_PUBLISH_MODE разрешает событие
- Claude вернул should_publish_to_channel=true
- channel_impact_score >= TRADE_MIN_CHANNEL_IMPACT
- лимит TRADE_MAX_CHANNEL_POSTS_PER_DAY не превышен

В DRY_RUN-превью добавляется маркер [DRY_RUN CHANNEL PREVIEW] и поста идёт владельцу.
"""

from __future__ import annotations

import html

from .broker import PaperTrade


CHANNEL_DISCLAIMER = (
    "Не является финансовым советом. Это личный дневник обучения, "
    "а AI-анализ носит ознакомительный характер."
)


def _e(s) -> str:
    return html.escape("" if s is None else str(s), quote=False)


def _fmt_price(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:,.2f}"


def _header_for(event_type: str, trade: PaperTrade) -> str:
    if event_type == "opened":
        return "📍 <b>Учебная paper-сделка открыта</b>"
    # closed
    reason = (trade.close_reason or "").lower()
    if reason == "tp":
        return "📍 <b>Учебная paper-сделка завершена — цель достигнута</b>"
    if reason == "sl":
        return "📍 <b>Учебная paper-сделка завершена — стоп сработал</b>"
    if reason == "expired":
        return "📍 <b>Учебная paper-сделка истекла</b>"
    return "📍 <b>Учебная paper-сделка завершена</b>"


def format_channel_trade_post(
    trade: PaperTrade,
    review: dict,
    *,
    event_type: str,
    dry_run_preview: bool = False,
) -> str:
    """Собирает безопасный HTML-пост со структурой из ТЗ Stage 7 §7."""
    human = _e(review.get("human_part", "")).strip()
    mentor = _e(review.get("mentor_part", "")).strip()
    mistake = _e(review.get("beginner_mistake", "")).strip()
    lesson = _e(review.get("lesson", "")).strip()
    conclusion = _e(review.get("conclusion", "")).strip()
    humor = _e(review.get("humor_line") or "").strip()

    parts: list[str] = []
    if dry_run_preview:
        parts.append("<i>[DRY_RUN CHANNEL PREVIEW]</i>")
        parts.append("")

    parts.append(_header_for(event_type, trade))
    parts.append("")

    if human:
        parts.append("😬 <b>Мысли новичка</b>")
        parts.append(human)
        parts.append("")

    parts.append("📊 <b>План был такой</b>")
    parts.append(f"Актив: {_e(trade.symbol)}")
    parts.append(f"Направление: {_e(trade.direction)}")
    parts.append(f"Вход: {_fmt_price(trade.entry)}")
    parts.append(f"Стоп: {_fmt_price(trade.stop_loss)}")
    parts.append(f"Тейк: {_fmt_price(trade.take_profit)}")
    parts.append(f"RR: {trade.rr:.2f}")

    # для closed — добавляем как закрылись
    if event_type == "closed" and trade.close_price is not None:
        parts.append(f"Закрытие: {_fmt_price(trade.close_price)} <i>({_e(trade.close_reason)})</i>")
        if trade.r_multiple is not None:
            sign = "+" if trade.r_multiple >= 0 else ""
            parts.append(f"Результат: {sign}{trade.r_multiple:.2f}R")
    parts.append("")

    if mentor:
        parts.append("🤖 <b>AI-наставник</b>")
        parts.append(mentor)
        parts.append("")

    if mistake:
        parts.append("⚠️ <b>Ошибка новичка</b>")
        parts.append(mistake)
        parts.append("")

    if lesson:
        parts.append("📌 <b>Урок</b>")
        parts.append(lesson)
        parts.append("")

    if conclusion:
        parts.append(conclusion)
        parts.append("")

    if humor:
        parts.append("😅 " + humor)
        parts.append("")

    parts.append(f"<i>{_e(CHANNEL_DISCLAIMER)}</i>")

    # хэштеги
    raw_tags = review.get("hashtags") or []
    tags = [t if str(t).startswith("#") else f"#{t}" for t in raw_tags if t]
    system_tags = ["#честный_путь", "#риск_менеджмент"]
    asset = trade.symbol.split("/")[0] if "/" in trade.symbol else trade.symbol
    if asset:
        system_tags.append(f"#{asset}")
    all_tags = list(dict.fromkeys(tags + system_tags))
    parts.append("")
    parts.append(" ".join(_e(t) for t in all_tags))

    text = "\n".join(parts).strip()
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text


def format_owner_dm_review(
    trade: PaperTrade,
    review: dict,
    *,
    event_type: str,
    publish_decision: str,
    publish_reason: str = "",
) -> str:
    """DM владельцу — версия с полным разбором + меткой что произошло с публикацией.

    `publish_decision`: 'published_channel' | 'sent_owner' | 'channel_blocked' | 'dry_run_preview'
    """
    base = format_channel_trade_post(trade, review, event_type=event_type)

    suffix_lines = ["", "<i>[Owner DM] paper-trade event.</i>"]
    if publish_decision == "published_channel":
        suffix_lines.append("<i>Опубликовано в канал.</i>")
    elif publish_decision == "channel_blocked":
        suffix_lines.append(f"<i>В канал НЕ отправлено: {_e(publish_reason)}</i>")
    elif publish_decision == "dry_run_preview":
        suffix_lines.append("<i>DRY_RUN — превью без реальной публикации.</i>")
    else:
        suffix_lines.append("<i>Только в DM (по конфигу).</i>")

    return base + "\n" + "\n".join(suffix_lines)
