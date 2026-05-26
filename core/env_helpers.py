"""Этап 2.3: единые env-helpers.

Чтобы не дублировать `_bool/_int/_float/_str` по 7 раз в bot.py, news/config.py,
trading/config.py, author_notes.py, weekly_diary.py, trade_visuals.py,
news/publisher.py — собираем здесь.

Контракты совпадают с историческими реализациями:
- env_bool: truthy = {"1","true","yes","on"} (case-insensitive); пустая строка → default? Нет, исторически пустая считалась "default" в bot.py, но "false" в author_notes. Здесь принимаем: ПУСТАЯ строка → default (как и unset).
- env_int / env_float: при невалидном значении возвращают default.
- env_str: возвращает значение через `.strip()`, пустая/whitespace → default.
"""
from __future__ import annotations

import os
from typing import Optional


_TRUTHY = {"1", "true", "yes", "on"}


def env_bool(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    stripped = raw.strip().lower()
    if not stripped:
        return default
    return stripped in _TRUTHY


def env_int(name: str, *, default: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    stripped = raw.strip()
    if not stripped:
        return default
    try:
        return int(stripped)
    except ValueError:
        return default


def env_float(name: str, *, default: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    stripped = raw.strip()
    if not stripped:
        return default
    try:
        return float(stripped)
    except ValueError:
        return default


def env_str(name: str, *, default: str = "") -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    stripped = raw.strip()
    if not stripped:
        return default
    return stripped
