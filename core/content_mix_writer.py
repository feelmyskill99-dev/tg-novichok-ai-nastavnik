"""Pure helpers для записи content_mix событий (этап 2.4 шаг 1).

Раньше эта логика лежала в `bot.py` как `_migrate_content_mix_state_if_needed`,
`_log_post_event` и подобные. Здесь — чистые функции без I/O:

- `migrate_state(state)`: миграция legacy `posts_log` -> `content_mix_log`.
- `make_event(post_type, published_to, title, source, now=None)`: построение
  одной записи события.
- `prune_log(log_list, now=None, days=14, cap=500)`: удаление старых событий +
  cap на размер.
- `append_event(state, event, *, days=14, cap=500, now=None)`: операция над
  in-memory state-dict — мутация ради удобства caller'а.

bot.py остаётся ответственным за load_state/save_state и валидацию
`published_to ∈ {"owner", "channel"}` (там есть logger).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from .content_mix import (
    CONTENT_MIX_LOG_CAP,
    category_for,
)


log = logging.getLogger("core.content_mix_writer")


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def migrate_state(state: dict) -> bool:
    """Мягкая миграция: legacy `posts_log` -> `content_mix_log`.

    Возвращает True если state был изменён.
    """
    if "content_mix_log" in state and isinstance(state["content_mix_log"], list):
        return False
    legacy = state.get("posts_log")
    if isinstance(legacy, list) and legacy:
        migrated: list[dict] = []
        for rec in legacy:
            if not isinstance(rec, dict):
                continue
            old_type = rec.get("type") or ""
            ts = rec.get("ts") or _now().isoformat(timespec="seconds")
            migrated.append({
                "timestamp": ts,
                "post_type": old_type,
                "category": category_for(old_type),
                "published_to": "channel",
                "title": "",
                "source": "legacy",
            })
        state["content_mix_log"] = migrated
        state.pop("posts_log", None)
        log.info("migrated %d entries from posts_log -> content_mix_log", len(migrated))
        return True
    if "content_mix_log" not in state:
        state["content_mix_log"] = []
        return True
    return False


def make_event(
    post_type: str,
    *,
    published_to: str,
    title: str = "",
    source: str = "",
    now: Optional[datetime] = None,
) -> dict:
    """Построить одно событие content_mix_log."""
    now = now or _now()
    return {
        "timestamp": now.isoformat(timespec="seconds"),
        "post_type": post_type or "",
        "category": category_for(post_type),
        "published_to": published_to,
        "title": (title or "")[:240],
        "source": source or "",
    }


def prune_log(
    log_list: list,
    *,
    now: Optional[datetime] = None,
    days: int = 14,
    cap: int = CONTENT_MIX_LOG_CAP,
) -> list[dict]:
    """Удалить события старше N дней, оставить максимум `cap` штук."""
    if not isinstance(log_list, list):
        return []
    now = now or _now()
    cutoff = now - timedelta(days=days)
    fresh: list[dict] = []
    for ev in log_list:
        if not isinstance(ev, dict):
            continue
        try:
            ts = datetime.fromisoformat(ev.get("timestamp") or "")
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if ts >= cutoff:
            fresh.append(ev)
    return fresh[-cap:]


def append_event(
    state: dict,
    event: dict,
    *,
    days: int = 14,
    cap: int = CONTENT_MIX_LOG_CAP,
    now: Optional[datetime] = None,
) -> None:
    """Добавить событие в state.content_mix_log + миграция + prune.

    Мутирует state in-place. Caller отвечает за save_state.
    """
    migrate_state(state)
    log_list = state.get("content_mix_log") or []
    if not isinstance(log_list, list):
        log_list = []
    log_list.append(event)
    state["content_mix_log"] = prune_log(log_list, now=now, days=days, cap=cap)


def append_channel_stats(
    state_path,
    stats: dict,
    *,
    max_entries: int = 100,
) -> None:
    """Атомарно дописать запись в state.channel_stats_log[]. Stage rebranding-3.

    Принимает путь к state.json (а не state-dict), сама делает load → mutate → save
    под json_store lock. `recorded_at` (ISO UTC) добавляется автоматически если в stats его нет.
    Список обрезается до max_entries (старые удаляются с начала).
    """
    from .json_store import update_json

    entry = dict(stats)
    entry.setdefault("recorded_at", _now().isoformat(timespec="seconds"))

    def _mutate(state: dict) -> dict:
        log_list = state.get("channel_stats_log") or []
        if not isinstance(log_list, list):
            log_list = []
        log_list.append(entry)
        if len(log_list) > max_entries:
            log_list = log_list[-max_entries:]
        state["channel_stats_log"] = log_list
        return state

    update_json(state_path, default={}, expected_type=dict, mutator=_mutate)
