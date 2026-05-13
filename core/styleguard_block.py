"""Этап 2.6: pre-publish guard на основе StyleGuard.

Используется в Publisher.publish() и других publish-flow:

    ok, reason = check_payload_or_reject(payload, styleguard)
    if not ok:
        await dm_owner(f"Style block: {reason}")
        return  # НЕ публикуем в канал

Отличие от base StyleGuard.validate():
1. fail-open если guard=None (не блокируем при отсутствии конфига)
2. БЕЗ marker-check: markers — soft signal, не блокировка (план 2.6)
3. БЕЗ required-fields-check: payload может иметь произвольную структуру
4. Только forbidden_words — единственный критерий блокировки
"""
from __future__ import annotations

from typing import Any, Optional

from .styleguard import StyleGuard


def check_payload_or_reject(
    payload: dict[str, Any],
    guard: Optional[StyleGuard],
) -> tuple[bool, str]:
    """Возвращает (ok, reason). ok=False → НЕ публиковать."""
    if guard is None:
        return True, ""
    if not isinstance(payload, dict) or not payload:
        return True, ""

    for key, value in payload.items():
        if not isinstance(value, str):
            continue
        lower_val = value.lower()
        for word in guard.forbidden_words:
            if word in lower_val:
                return False, f"forbidden '{word}' in '{key}'"
    return True, ""
