"""Stage 14d — «ТОП ДНЯ» дайджест.

Собирает все опубликованные в канал посты за сегодня из state.content_mix_log
и формирует HTML-сообщение в стиле @crypto_hd:

    🎯 ТОП ДНЯ — <дата>

    ❕ <a href="...">{title}</a>
    ▫️ <a href="...">{title}</a>
    ▫️ ...

Если для записи есть `message_id` и известен `channel_id_for_links` — рендерим
как ссылку. Иначе — plain HTML-escaped текст.

Пустой день (< MIN_POSTS постов) — возвращаем None, чтобы caller не публиковал
бессмысленный дайджест.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape as _esc
from typing import Optional


MIN_POSTS_FOR_DIGEST = 3
MAX_POSTS_IN_DIGEST = 12
TITLE_MAX_LEN = 100


def _today_events_published_to_channel(
    log_list: list[dict],
    *,
    now: Optional[datetime] = None,
) -> list[dict]:
    """Отфильтровать события, опубликованные в канал сегодня (UTC.date == now.date)."""
    now = now or datetime.now(tz=timezone.utc)
    today = now.date()
    out: list[dict] = []
    for ev in log_list or []:
        if not isinstance(ev, dict):
            continue
        if ev.get("published_to") != "channel":
            continue
        ts_raw = ev.get("timestamp") or ""
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if ts.date() == today:
            out.append(ev)
    return out


def _build_message_link(channel_id_for_links: str, message_id: int) -> str:
    """Построить t.me-ссылку на сообщение.

    @username канал: https://t.me/<username>/<msg>
    -100... numeric: https://t.me/c/<numeric>/<msg>  (telegram convention)
    """
    ch = (channel_id_for_links or "").strip()
    if not ch:
        return ""
    if ch.startswith("@"):
        ch = ch[1:]
    if ch.startswith("-100"):
        return f"https://t.me/c/{ch[4:]}/{int(message_id)}"
    return f"https://t.me/{ch}/{int(message_id)}"


def _format_title(title: str) -> str:
    t = (title or "").strip()
    if not t:
        return "(без заголовка)"
    if len(t) > TITLE_MAX_LEN:
        t = t[:TITLE_MAX_LEN - 1].rstrip() + "…"
    return _esc(t, quote=False)


def build_digest_html(
    log_list: list[dict],
    *,
    channel_id_for_links: str = "",
    now: Optional[datetime] = None,
    min_posts: int = MIN_POSTS_FOR_DIGEST,
    max_posts: int = MAX_POSTS_IN_DIGEST,
) -> Optional[str]:
    """Собрать HTML «ТОП ДНЯ». Возвращает None если постов меньше min_posts.

    Stage 14d — minimum viable. Не различает sector'ы при сортировке, берёт
    в хронологическом порядке (как в @crypto_hd ТОП ДНЯ). Дублирующиеся
    title'ы пропускаются (защита от повторного логирования).
    """
    now = now or datetime.now(tz=timezone.utc)
    events = _today_events_published_to_channel(log_list, now=now)
    if len(events) < min_posts:
        return None

    events.sort(key=lambda e: e.get("timestamp") or "")
    events = events[:max_posts]

    seen_titles: set[str] = set()
    items: list[str] = []
    for i, ev in enumerate(events):
        title = (ev.get("title") or "").strip()
        key = title.lower()[:80]
        if key and key in seen_titles:
            continue
        seen_titles.add(key)
        title_html = _format_title(title)
        mid = ev.get("message_id")
        bullet = "❕" if i == 0 else "▫️"
        if mid and channel_id_for_links:
            link = _build_message_link(channel_id_for_links, int(mid))
            items.append(f'{bullet} <a href="{_esc(link, quote=True)}">{title_html}</a>')
        else:
            items.append(f"{bullet} {title_html}")

    if not items:
        return None

    date_str = _format_date_ru(now)
    header = f"🎯 <b>ТОП ДНЯ</b> — {_esc(date_str, quote=False)}"
    return header + "\n\n" + "\n\n".join(items)


_RU_WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
_RU_MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня",
              "июля", "августа", "сентября", "октября", "ноября", "декабря")


def _format_date_ru(now: datetime) -> str:
    from datetime import timedelta
    msk = now.astimezone(timezone(timedelta(hours=3)))
    return f"{_RU_WEEKDAYS[msk.weekday()]}, {msk.day} {_RU_MONTHS[msk.month - 1]}"
