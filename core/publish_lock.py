"""Idempotency для publish-callback'ов.

Используется в news_publish / author_publish / weekly_publish:

    draft = try_claim_for_publishing(store, draft_id)
    if draft is None:
        # уже в publishing/published/rejected — второй клик игнорируется
        return
    try:
        await send_to_channel(...)
    except Exception:
        release_claim(store, draft_id, new_status="pending_review")
        raise
    draft.status = "published"
    store.update(draft)

Контракт store (duck-typed):
    .get(draft_id) -> draft | None
    .update(draft) -> None
    draft.status: str  (mutable)
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

TERMINAL_STATUSES = ("publishing", "published", "rejected")
PUBLISHING_STATUS = "publishing"


def try_claim_for_publishing(
    store: Any,
    draft_id: str,
    *,
    terminal: Iterable[str] = TERMINAL_STATUSES,
) -> Optional[Any]:
    """Compare-and-set: если draft в pending — переводит в "publishing" и возвращает.
    Иначе возвращает None.
    """
    draft = store.get(draft_id)
    if draft is None:
        return None
    if draft.status in set(terminal):
        return None
    draft.status = PUBLISHING_STATUS
    store.update(draft)
    return draft


def release_claim(
    store: Any,
    draft_id: str,
    *,
    new_status: str = "pending_review",
) -> None:
    """Откат claim после ошибки send: возвращает draft в редактируемое состояние."""
    draft = store.get(draft_id)
    if draft is None:
        return
    if draft.status != PUBLISHING_STATUS:
        return
    draft.status = new_status
    store.update(draft)
