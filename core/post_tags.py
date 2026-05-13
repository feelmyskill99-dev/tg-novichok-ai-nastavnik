"""Pure HTML-tag helpers для post-builder (этап 2.4 шаг 2).

Раньше эта логика жила inline в `bot.py:build_post_html`. Здесь — чистые
функции без зависимостей на runtime-конфиг.

Используется в bot.build_post_html для финального tag-block постов.
"""
from __future__ import annotations

from typing import Iterable


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


def system_tags_for(post_type: str, *, has_hamster: bool) -> list[str]:
    """Системные теги, которые добавляются ко всем постам автоматически."""
    tags = ["#честный_путь"]
    if has_hamster:
        tags.append("#не_будь_хомяком")
    else:
        tags.append("#ошибки_новичка")
    if post_type == "flash":
        tags.append("#flash")
    elif post_type == "fallback_education":
        tags.append("#термин_без_боли")
    return tags


def merge_tags(claude_tags: Iterable[str], *, post_type: str, has_hamster: bool) -> list[str]:
    """Финальный список тегов: claude_tags (нормализованные) + system_tags.

    Дубликаты убираются с сохранением порядка.
    """
    normalized = normalize_tags(claude_tags)
    system = system_tags_for(post_type, has_hamster=has_hamster)
    return list(dict.fromkeys(normalized + system))
