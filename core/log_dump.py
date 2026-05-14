"""Pure helper для безопасного логирования объектов (этап 2.4 шаг 8).

`safe_log_dict(obj, limit=500)` — JSON-сериализует объект для лога,
ограничивая длину; не падает на не-сериализуемых типах (даёт str fallback).

Раньше эта функция жила в bot.py как `_safe_log_dict`.
"""
from __future__ import annotations

import json
from typing import Any


def safe_log_dict(value: Any, *, limit: int = 500) -> str:
    """Возвращает JSON-представление (или str fallback) обрезанное до limit chars.

    - JSON через `default=str` (объекты с __str__ конвертируются)
    - При любой ошибке — `str(value)[:limit]`
    - Никогда не бросает exception
    """
    try:
        return json.dumps(value, ensure_ascii=False, default=str)[:limit]
    except Exception:
        try:
            return str(value)[:limit]
        except Exception:
            return ""
