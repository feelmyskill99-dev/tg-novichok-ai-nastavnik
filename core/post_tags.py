"""Pure HTML-tag helpers для post-builder (этап 2.4 шаг 2).

Stage rebranding-1.3: добавлена ротация системных тегов по day_seed.
"""
from __future__ import annotations

from datetime import date as _date
from typing import Iterable

_ROTATING_HAMSTER_POOL = (
    "#не_будь_хомяком",
    "#риск_менеджмент",
    "#дисциплина",
    "#психология_трейдинга",
)

_ROTATING_NO_HAMSTER_POOL = (
    "#ошибки_новичка",
    "#риск_менеджмент",
    "#дисциплина",
    "#психология_трейдинга",
)


def normalize_tags(raw_tags: Iterable[str]) -> list[str]:
    """Приводит сырые теги от Claude к формату '#тег'. Дубликаты убираются
    с сохранением порядка."""
    out: list[str] = []
    for t in raw_tags or []:
        s = str(t).strip()
        if not s:
            continue
        if not s.startswith("#"):
            s = f"#{s}"
        out.append(s)
    return list(dict.fromkeys(out))


def system_tags_for(
    post_type: str,
    *,
    has_hamster: bool,
    day_seed: _date | None = None,
) -> list[str]:
    """Системные теги: '#честный_путь' (всегда) + 1 ротируемый + type-specific.

    Без day_seed — детерминированное поведение (legacy compat):
    has_hamster=True → '#не_будь_хомяком'; False → '#ошибки_новичка'.

    С day_seed — ротация по дню: выбор из пула в зависимости от has_hamster.
    """
    tags = ["#честный_путь"]

    if day_seed is None:
        tags.append("#не_будь_хомяком" if has_hamster else "#ошибки_новичка")
    else:
        pool = _ROTATING_HAMSTER_POOL if has_hamster else _ROTATING_NO_HAMSTER_POOL
        idx = day_seed.toordinal() % len(pool)
        tags.append(pool[idx])

    if post_type == "flash":
        tags.append("#flash")
    elif post_type == "fallback_education":
        tags.append("#термин_без_боли")
    return tags


def merge_tags(
    claude_tags: Iterable[str],
    *,
    post_type: str,
    has_hamster: bool,
    day_seed: _date | None = None,
) -> list[str]:
    """Финальный список тегов: claude_tags (нормализованные) + system_tags.

    Дубликаты убираются с сохранением порядка.
    """
    normalized = normalize_tags(claude_tags)
    system = system_tags_for(post_type, has_hamster=has_hamster, day_seed=day_seed)
    return list(dict.fromkeys(normalized + system))
