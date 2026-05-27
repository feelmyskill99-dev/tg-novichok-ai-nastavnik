"""Stage 14e — утренний брифинг «Доброе утро + 5 новостей».

Заменяет голый market_chart форматом, увиденным у @invest_zonaa и @Coin_Post.
См. docs/briefs/morning_briefing_v1.md для полного контракта.

Структура HTML (caption ≤ 1024 chars если с картинкой):

    🌅 <b>Доброе утро!</b>

    Сегодня рынок {direction}, BTC у $XX,XXX ({+X.X}%).
    Индекс F&G: 25 — страх.

    📊 <b>Главное за ночь:</b>

    ➤ <a href="...">Title 1</a>
    ➤ <a href="...">Title 2</a>
    ➤ ...

    🐹 <i>Какой пост обсудить — пиши в @ai_deposit_diary_bot.</i>

    📈 <b><a href="...">Я торгую здесь → Gate.io</a></b>
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from html import escape as _esc
from pathlib import Path
from typing import Optional

log = logging.getLogger("core.morning_briefing")

CAPTION_LIMIT = 1024
TEXT_LIMIT = 4096

NEWS_TITLE_MAX = 90
NEWS_LOOKBACK_HOURS = 14  # с ~вечера вчера до утра


def _direction(change_24h: Optional[float]) -> str:
    if change_24h is None:
        return "в боковике"
    if change_24h >= 1.0:
        return "в плюсе"
    if change_24h <= -1.0:
        return "в минусе"
    return "в боковике"


def _format_price(price: Optional[float]) -> str:
    if price is None:
        return "—"
    return f"${price:,.0f}".replace(",", " ")


def _format_change(change_24h: Optional[float]) -> str:
    if change_24h is None:
        return ""
    return f"{change_24h:+.2f}%"


def _build_link(channel_id_for_links: str, message_id: int) -> str:
    ch = (channel_id_for_links or "").strip()
    if not ch:
        return ""
    if ch.startswith("@"):
        ch = ch[1:]
    if ch.startswith("-100"):
        return f"https://t.me/c/{ch[4:]}/{int(message_id)}"
    return f"https://t.me/{ch}/{int(message_id)}"


def _format_news_title(title: str) -> str:
    t = (title or "").strip()
    if not t:
        return "(без заголовка)"
    if len(t) > NEWS_TITLE_MAX:
        t = t[:NEWS_TITLE_MAX - 1].rstrip() + "…"
    return _esc(t, quote=False)


def _format_news_bullet(news: dict, channel_id_for_links: str) -> str:
    title_html = _format_news_title(news.get("title") or "")
    mid = news.get("message_id")
    if mid and channel_id_for_links:
        link = _build_link(channel_id_for_links, int(mid))
        return f'➤ <a href="{_esc(link, quote=True)}">{title_html}</a>'
    url = (news.get("url") or "").strip()
    if url:
        return f'➤ <a href="{_esc(url, quote=True)}">{title_html}</a>'
    return f"➤ {title_html}"


def build_morning_briefing_html(
    market_snapshot: dict,
    top_news: list[dict],
    *,
    fg_index: Optional[int] = None,
    fg_label: str = "",
    partner_url: str = "",
    bot_username: str = "",
    channel_id_for_links: str = "",
    poll_block: str = "",
    caption_limit: int = CAPTION_LIMIT,
) -> str:
    """Собрать HTML утреннего брифинга.

    market_snapshot keys (compatible with bot.py Publisher):
        symbol, price, change_24h, high_24h, low_24h, rsi, ema50, ema200
    top_news: list[{title, url, message_id?}]
    fg_index: F&G value 0-100 или None
    partner_url: уже с UTM (caller строит через build_partner_url)
    bot_username: для CTA «пиши в @bot_username»
    poll_block: Stage 14f — готовый HTML reaction-опроса (см.
        core.reaction_poll.build_poll_block). Если пустой — секция не
        рендерится. Если не влезает в caption — сначала сжимаем
        количество новостей, потом убираем опрос.

    Если caption > caption_limit — режем top_news до 3, потом до 1,
    потом убираем poll_block.
    """
    symbol = (market_snapshot.get("symbol") or "BTC/USDT").split("/")[0] or "BTC"
    price = market_snapshot.get("price")
    change_24h = market_snapshot.get("change_24h")

    direction = _direction(change_24h)
    price_s = _format_price(price)
    change_s = _format_change(change_24h)

    header = "🌅 <b>Доброе утро!</b>"

    market_line = f"Сегодня рынок {direction}, {symbol} у {price_s}"
    if change_s:
        market_line += f" ({change_s})"
    market_line += "."

    fg_line = ""
    if fg_index is not None and 0 <= fg_index <= 100:
        label = fg_label or ""
        fg_line = f"Индекс F&amp;G: {fg_index}" + (f" — {label}." if label else ".")

    news_count_max = min(len(top_news or []), 5)
    bot_cta = ""
    if bot_username:
        bot_username_clean = bot_username.lstrip("@")
        bot_cta = (
            f"🐹 <i>Какой пост обсудить — пиши в "
            f"@{_esc(bot_username_clean, quote=False)}.</i>"
        )

    partner_cta = ""
    if partner_url:
        partner_cta = (
            f'📈 <b><a href="{_esc(partner_url, quote=True)}">'
            f'Я торгую здесь → Gate.io</a></b>'
        )

    def _assemble(news_n: int, include_poll: bool) -> str:
        news = (top_news or [])[:news_n]
        bullets = [_format_news_bullet(n, channel_id_for_links) for n in news]

        parts: list[str] = [header, "", market_line]
        if fg_line:
            parts.append(fg_line)
        if bullets:
            parts.append("")
            parts.append("📊 <b>Главное за ночь:</b>")
            parts.append("")
            parts.extend(bullets)
        if include_poll and poll_block:
            parts.append("")
            parts.append(poll_block)
        if bot_cta:
            parts.append("")
            parts.append(bot_cta)
        if partner_cta:
            parts.append("")
            parts.append(partner_cta)
        return "\n".join(parts)

    # Cascade: (5, poll) → (3, poll) → (1, poll) → (5, no_poll) → (3, no_poll) → (1, no_poll) → (0, no_poll)
    plans: list[tuple[int, bool]] = []
    if poll_block:
        plans += [(news_count_max, True), (3, True), (1, True)]
    plans += [(news_count_max, False), (3, False), (1, False), (0, False)]

    seen: set[tuple[int, bool]] = set()
    for n, with_poll in plans:
        if n > news_count_max:
            n = news_count_max
        key = (n, with_poll)
        if key in seen:
            continue
        seen.add(key)
        text = _assemble(n, with_poll)
        if len(text) <= caption_limit:
            return text

    # Если даже минимальный вариант не влезает (теоретически не должно) — обрезаем.
    return _assemble(0, False)[:caption_limit]


def fetch_top_news_for_briefing(
    news_drafts_path: Path,
    *,
    now: Optional[datetime] = None,
    lookback_hours: int = NEWS_LOOKBACK_HOURS,
    limit: int = 5,
) -> list[dict]:
    """Прочитать news_drafts.json, выбрать опубликованные за последние
    lookback_hours, отсортировать по impact_score desc, вернуть top-N.

    Возвращает list[{title, url, message_id?}].
    """
    now = now or datetime.now(tz=timezone.utc)
    cutoff = now - timedelta(hours=lookback_hours)

    try:
        drafts = json.loads(news_drafts_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(drafts, list):
        return []

    candidates: list[tuple[float, dict]] = []
    for d in drafts:
        if not isinstance(d, dict):
            continue
        if d.get("status") != "published":
            continue
        created_at = d.get("created_at") or ""
        try:
            ts = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if ts < cutoff:
            continue

        sn = d.get("source_news") or {}
        cj = d.get("claude_json") or {}
        impact = float(sn.get("impact_score") or 0.0)
        title = (cj.get("specific_title") or sn.get("title") or "").strip()
        if not title:
            continue
        news_entry = {
            "title": title,
            "url": sn.get("url") or "",
        }
        # message_id может быть в самом draft (если когда-то добавим)
        # — на сегодняшний день не сохраняется, оставляем None.
        candidates.append((impact, news_entry))

    candidates.sort(key=lambda x: x[0], reverse=True)
    return [entry for _, entry in candidates[:limit]]
