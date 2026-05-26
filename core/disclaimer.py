"""Disclaimer rotation. Stage 1 anti-AI-slop fix."""
from __future__ import annotations

from datetime import date

DISCLAIMER_LONG = (
    "Не является финансовым советом. Это личный дневник обучения, "
    "а AI-анализ носит ознакомительный характер."
)

DISCLAIMER_VARIANTS = (
    "Не финсовет. Это дневник обучения и AI-разбор.",
    "Это не сигнал и не совет. Это дневник — для меня и для тех, кто учится рядом.",
    "Я учусь публично. Не повторяй — анализируй.",
    "Дневник, не рекомендация. Любая сделка — твоя ответственность.",
)


def pick_disclaimer(post_type: str, *, day_seed: date) -> str:
    if post_type == "fallback_education":
        return DISCLAIMER_LONG
    idx = day_seed.toordinal() % len(DISCLAIMER_VARIANTS)
    return DISCLAIMER_VARIANTS[idx]
