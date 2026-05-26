"""Pure helpers для распознавания image-intent в feedback владельца (этап 2.4 шаг 7).

Stage 12e — две интенции:
- AI-картинка: нужно вызвать OpenAI (`looks_like_ai_image_request`)
- Source-превью: нужно вытащить og:image из источника (`looks_like_source_image_request`)

Раньше эти функции жили в bot.py. Здесь — pure, без зависимостей.
"""
from __future__ import annotations

_AI_IMAGE_PATTERNS = (
    "сгенери",                  # сгенери / сгенерируй
    "нарисуй",
    "сделай ai-картин",
    "сделай ии-картин",
    "сделай арт",
    "новая ai",
    "новую ai",
    "ai-картин",
    "ии-картин",
    "ai картин",
    "ии картин",
    "тематичес",                # «сгенерируй тематическое изображение»
    "перерисуй картин",
    "перегенери картин",
    "regenerate image",
    "generate image",
    "new image",
    "another image",
    "🖼",
)

_SOURCE_IMAGE_PATTERNS = (
    "из источника",             # «возьми картинку из источника»
    "превью источника",
    "обнови превью",
    "обнови картин",            # «обнови картинку из источника»
    "source image",
    "og image",
    "og:image",
    "twitter:image",
    "🔄",
)

_GENERIC_AI_KEYWORDS_KARTIN = ("сгенери", "нарисуй", "сделай", "новая", "новую", "перерисуй")
_GENERIC_AI_KEYWORDS_IZOBRAZH = ("сгенери", "нарисуй", "сделай", "новое", "перерисуй")
_MAX_INTENT_TEXT_LEN = 80


def _norm(text: str) -> str:
    return (text or "").strip().lower()


def looks_like_ai_image_request(text: str) -> bool:
    """True если в тексте есть просьба сгенерировать AI-картинку.

    Эвристики:
    - явные AI-маркеры (сгенери/нарисуй/ai-картин/ии-картин/🖼)
    - «AI» + «картин»/«изображ»
    - generic «сделай картинку» / «новую картинку» БЕЗ source-маркера
    - короткое сообщение (≤80 chars), чтобы не путать с большим текстом
    """
    s = _norm(text)
    if not s or len(s) > _MAX_INTENT_TEXT_LEN:
        return False
    if "ai" in s and ("картин" in s or "изображ" in s):
        return True
    if any(p in s for p in _AI_IMAGE_PATTERNS):
        return True
    # generic «картинку/изображение» без явного AI — считаем AI (legacy),
    # но только если нет source-маркера в той же фразе.
    if "из источник" in s or "source" in s or "og:" in s:
        return False
    if "картин" in s and any(k in s for k in _GENERIC_AI_KEYWORDS_KARTIN):
        return True
    if "изображ" in s and any(k in s for k in _GENERIC_AI_KEYWORDS_IZOBRAZH):
        return True
    return False


def looks_like_source_image_request(text: str) -> bool:
    """True если владелец просит обновить превью из источника (og:image)."""
    s = _norm(text)
    if not s or len(s) > _MAX_INTENT_TEXT_LEN:
        return False
    return any(p in s for p in _SOURCE_IMAGE_PATTERNS)


def looks_like_image_request(text: str) -> bool:
    """Legacy alias — TRUE если любая image-intent."""
    return looks_like_ai_image_request(text) or looks_like_source_image_request(text)
