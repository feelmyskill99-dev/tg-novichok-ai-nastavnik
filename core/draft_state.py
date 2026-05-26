"""Pure state-mutators для draft-flow (этап 2.4 шаг 6).

awaiting_*_edit: какой draft владелец сейчас правит (news/author_notes).
news_post_counter: для mistake_theme inject (Stage 14).
author_notes_week_count: rolling weekly counter с ISO-week ключом.

Все функции работают над in-memory state-dict, без I/O. Bot.py остаётся
ответственным за load_state/save_state.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def _isoweek_key(now: Optional[datetime] = None) -> str:
    """ISO-week ключ вида '2026-19' (год + номер недели)."""
    now = now or datetime.now(tz=timezone.utc)
    cal = now.isocalendar()
    return f"{cal.year}-{cal.week:02d}"


# ---------- awaiting_*_edit ----------


def get_awaiting_edit(state: dict, kind: str) -> str:
    """Возвращает draft_id, который владелец сейчас правит (или '')."""
    key = f"awaiting_{kind}_edit_for"
    return str(state.get(key) or "")


def set_awaiting_edit(state: dict, kind: str, draft_id: Optional[str]) -> None:
    """Устанавливает или сбрасывает awaiting_*_edit. None/empty → удаляем ключ."""
    key = f"awaiting_{kind}_edit_for"
    if draft_id:
        state[key] = draft_id
    else:
        state.pop(key, None)


# ---------- news_post_counter ----------


def get_news_post_counter(state: dict) -> int:
    try:
        return int(state.get("news_post_counter") or 0)
    except (TypeError, ValueError):
        return 0


def increment_news_post_counter(state: dict) -> int:
    """Инкрементит счётчик в state. Возвращает новое значение."""
    cur = get_news_post_counter(state)
    new_val = cur + 1
    state["news_post_counter"] = new_val
    return new_val


# ---------- author_notes_week_count ----------


def get_author_notes_week_count(state: dict, *, now: Optional[datetime] = None) -> int:
    """Сколько author_notes опубликовано в текущей ISO-неделе.

    Если в state.author_notes_week_key не текущая неделя — счётчик протух → 0.
    """
    key = _isoweek_key(now)
    if state.get("author_notes_week_key") != key:
        return 0
    try:
        return int(state.get("author_notes_week_count") or 0)
    except (TypeError, ValueError):
        return 0


def increment_author_notes_week_count(state: dict, *, now: Optional[datetime] = None) -> None:
    """Инкрементит. Если неделя протухла — сбрасывает в 1 + обновляет key.
    Также проставляет last_author_note_at = now.
    """
    now = now or datetime.now(tz=timezone.utc)
    key = _isoweek_key(now)
    if state.get("author_notes_week_key") != key:
        state["author_notes_week_count"] = 1
        state["author_notes_week_key"] = key
    else:
        try:
            current = int(state.get("author_notes_week_count") or 0)
        except (TypeError, ValueError):
            current = 0
        state["author_notes_week_count"] = current + 1
    state["last_author_note_at"] = now.isoformat(timespec="seconds")
