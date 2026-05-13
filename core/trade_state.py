"""Pure state-mutators для trading-блока (этап 2.4 шаг 4).

Раньше эта логика жила в `bot.py` как `_state_*_trade_*` функции —
каждая делала load_state → mutate → save_state, дублируя паттерн.
Здесь — чистые функции над in-memory state-dict.

Bot.py остаётся ответственным за load_state/save_state. Тестировать
эти функции легко без I/O.

Конвенции:
- *_get_*(state, ...) → читает, возвращает значение
- *_set_*(state, ...) → мутирует state in-place
- *_increment_*(state) → инкрементит счётчик в state in-place
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def today_utc_iso(now: Optional[datetime] = None) -> str:
    """Возвращает текущую UTC-дату в виде 'YYYY-MM-DD'."""
    now = now or datetime.now(tz=timezone.utc)
    return now.strftime("%Y-%m-%d")


def get_trade_channel_posts_today(state: dict, *, now: Optional[datetime] = None) -> int:
    """Сколько торговых постов опубликовано в канал сегодня (UTC).

    Если в state.trade_channel_posts_date не сегодня — счётчик протух → 0.
    """
    today = today_utc_iso(now)
    if state.get("trade_channel_posts_date") != today:
        return 0
    try:
        return int(state.get("trade_channel_posts_today") or 0)
    except (TypeError, ValueError):
        return 0


def increment_trade_channel_posts_today(state: dict, *, now: Optional[datetime] = None) -> None:
    """Инкрементит счётчик. Если дата протухла — сбрасывает в 1 и обновляет."""
    today = today_utc_iso(now)
    if state.get("trade_channel_posts_date") != today:
        state["trade_channel_posts_today"] = 1
        state["trade_channel_posts_date"] = today
        return
    try:
        current = int(state.get("trade_channel_posts_today") or 0)
    except (TypeError, ValueError):
        current = 0
    state["trade_channel_posts_today"] = current + 1


def set_last_trade_scan_at(state: dict, ts: str) -> None:
    state["last_trade_scan_at"] = ts


def set_last_trade_tick_at(state: dict, ts: str) -> None:
    state["last_trade_tick_at"] = ts


def set_gate_screenshot(state: dict, trade_id: str, path: str) -> None:
    """Сохраняет путь скриншота Gate.io для trade_id."""
    if not trade_id:
        return
    m = state.get("gate_screenshots") or {}
    if not isinstance(m, dict):
        m = {}
    m[trade_id] = path
    state["gate_screenshots"] = m


def get_gate_screenshot(state: dict, trade_id: str) -> Optional[str]:
    if not trade_id:
        return None
    m = state.get("gate_screenshots") or {}
    if not isinstance(m, dict):
        return None
    return m.get(trade_id)
