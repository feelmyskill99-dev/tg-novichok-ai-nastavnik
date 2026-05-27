"""Stage 14e — Fear & Greed Index из alternative.me API.

Используется в morning briefing'е (как у @invest_zonaa: «⭕Индекс F/G: 25 - страх»).

Кэшируется на 1 час в state.json чтобы не дёргать API при каждой публикации.
Падение API → возвращаем (None, "") fallback; morning briefing рендерит
без строки F&G, остальное не ломается.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

log = logging.getLogger("core.fear_greed")

FG_API_URL = "https://api.alternative.me/fng/?limit=1"
FG_CACHE_TTL_SECONDS = 3600
FG_HTTP_TIMEOUT_S = 8.0


def _label_from_value(value: int) -> str:
    """Convert F&G value (0-100) to Russian-ish label.

    Schema alternative.me uses ('Extreme Fear' / 'Fear' / 'Neutral' / 'Greed' /
    'Extreme Greed'), но мы возвращаем компактные русские для канала.
    """
    if value < 25:
        return "сильный страх"
    if value < 45:
        return "страх"
    if value < 55:
        return "нейтрально"
    if value < 75:
        return "жадность"
    return "сильная жадность"


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _is_cache_fresh(cached_at_iso: str, *, ttl_s: int = FG_CACHE_TTL_SECONDS, now: Optional[datetime] = None) -> bool:
    if not cached_at_iso:
        return False
    try:
        cached_at = datetime.fromisoformat(cached_at_iso.replace("Z", "+00:00"))
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)
    except Exception:
        return False
    now = now or _now()
    return (now - cached_at).total_seconds() < ttl_s


def fetch_fear_greed_raw(*, timeout_s: float = FG_HTTP_TIMEOUT_S) -> Optional[int]:
    """Прямой вызов API. Возвращает value 0-100 или None при ошибке.

    Не использует кэш. Для production-use возьми fetch_fear_greed(state_path).
    """
    try:
        r = httpx.get(FG_API_URL, timeout=timeout_s)
        if r.status_code != 200:
            log.warning("fear_greed: HTTP %d", r.status_code)
            return None
        data = r.json()
        items = data.get("data") or []
        if not items:
            return None
        raw = items[0].get("value")
        return int(raw) if raw is not None else None
    except Exception as e:
        log.warning("fear_greed fetch failed: %s", e)
        return None


def fetch_fear_greed(state_path: Optional[Path] = None) -> tuple[Optional[int], str]:
    """Кэшированный F&G. Возвращает (value, label).

    state_path — путь к state.json для кэша. Если None — без кэша, прямой fetch.
    Кэш хранится в `state.fear_greed_cache = {"value": int, "cached_at": ISO}`.

    При ошибке API возвращаем (None, "") — caller отрисует без строки F&G.
    """
    if state_path is None:
        v = fetch_fear_greed_raw()
        return (v, _label_from_value(v) if v is not None else "")

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        state = {}

    cached = state.get("fear_greed_cache") or {}
    if isinstance(cached, dict) and _is_cache_fresh(cached.get("cached_at", "")):
        v = cached.get("value")
        if isinstance(v, int) and 0 <= v <= 100:
            return (v, _label_from_value(v))

    v = fetch_fear_greed_raw()
    if v is None:
        return (None, "")

    try:
        state["fear_greed_cache"] = {
            "value": v,
            "cached_at": _now().isoformat(timespec="seconds"),
        }
        state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        log.warning("fear_greed: cache write failed: %s", e)

    return (v, _label_from_value(v))
