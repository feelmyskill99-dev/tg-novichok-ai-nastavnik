"""post_engagement — учёт реакций под постами канала.

Хранилище: state.json → ключ "post_engagement", словарь:
    {
      "<chat_id>:<message_id>": {
        "chat_id": int,
        "message_id": int,
        "first_seen_at": "ISO8601",
        "last_updated_at": "ISO8601",
        "reactions": {"👍": 3, "🔥": 1, "🐹": 2}
      },
      ...
    }

Логика:
- На каждый MessageReactionUpdated прилетает diff: old_reaction → new_reaction
  для конкретного пользователя. Telegram уже агрегирует, бот видит only the
  change. Мы пересчитываем total через old/new dict в state.
- Реакция — это словарь emoji → count. Anonymized (без user_id), потому что
  в каналах TG обычно анонимные реакции.
- Лимит хранилища: последние MAX_TRACKED постов. Старые автоматически
  выпадают при превышении.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Iterable

MAX_TRACKED = 200   # последние N постов с реакциями


def _entry_key(chat_id: int | str, message_id: int) -> str:
    return f"{chat_id}:{message_id}"


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def apply_reaction_update(
    engagement: dict,
    *,
    chat_id: int | str,
    message_id: int,
    old_emojis: Iterable[str],
    new_emojis: Iterable[str],
    now: str | None = None,
) -> dict:
    """Применяет diff реакций к engagement-словарю in-place и возвращает его.

    old_emojis, new_emojis — итерируемые списки emoji-строк, которые пользователь
    ставил/убирал. Считаем: убираем все old (−1 count), добавляем все new (+1 count).
    Если эмодзи в new и в old — count не меняется (это случай 'тот же эмодзи остался').
    """
    if not isinstance(engagement, dict):
        engagement = {}

    key = _entry_key(chat_id, message_id)
    now = now or _now_iso()

    entry = engagement.get(key)
    if not isinstance(entry, dict):
        entry = {
            "chat_id": chat_id,
            "message_id": message_id,
            "first_seen_at": now,
            "last_updated_at": now,
            "reactions": {},
        }
        engagement[key] = entry

    reactions = entry.get("reactions") or {}
    if not isinstance(reactions, dict):
        reactions = {}

    old_set = list(old_emojis or [])
    new_set = list(new_emojis or [])

    # Сначала вычитаем старые
    for e in old_set:
        if not isinstance(e, str) or not e:
            continue
        prev = int(reactions.get(e, 0))
        if prev > 0:
            new_count = prev - 1
            if new_count <= 0:
                reactions.pop(e, None)
            else:
                reactions[e] = new_count

    # Потом добавляем новые
    for e in new_set:
        if not isinstance(e, str) or not e:
            continue
        reactions[e] = int(reactions.get(e, 0)) + 1

    entry["reactions"] = reactions
    entry["last_updated_at"] = now
    return engagement


def evict_old_entries(engagement: dict, *, max_tracked: int = MAX_TRACKED) -> dict:
    """Оставляет только последние max_tracked постов по last_updated_at."""
    if not isinstance(engagement, dict) or len(engagement) <= max_tracked:
        return engagement
    sorted_items = sorted(
        engagement.items(),
        key=lambda kv: kv[1].get("last_updated_at", "") if isinstance(kv[1], dict) else "",
        reverse=True,
    )
    keep = dict(sorted_items[:max_tracked])
    return keep


def top_posts_by_engagement(
    engagement: dict,
    *,
    limit: int = 5,
    metric: str = "total",
) -> list[tuple[str, dict, int]]:
    """Возвращает топ постов по выбранной метрике.

    metric:
    - "total" — сумма всех реакций
    - "unique" — число разных эмодзи

    Возвращает: [(key, entry, score), ...] в порядке убывания.
    """
    if not isinstance(engagement, dict):
        return []
    scored: list[tuple[str, dict, int]] = []
    for key, entry in engagement.items():
        if not isinstance(entry, dict):
            continue
        reactions = entry.get("reactions") or {}
        if not isinstance(reactions, dict):
            continue
        if metric == "unique":
            score = len(reactions)
        else:
            score = sum(int(v) for v in reactions.values() if isinstance(v, int))
        scored.append((key, entry, score))
    scored.sort(key=lambda x: x[2], reverse=True)
    return scored[:limit]


def total_reaction_count(engagement: dict) -> int:
    """Сумма всех реакций по всем постам — для health/dashboard."""
    if not isinstance(engagement, dict):
        return 0
    total = 0
    for entry in engagement.values():
        if not isinstance(entry, dict):
            continue
        reactions = entry.get("reactions") or {}
        if not isinstance(reactions, dict):
            continue
        for v in reactions.values():
            try:
                total += int(v)
            except (TypeError, ValueError):
                pass
    return total
