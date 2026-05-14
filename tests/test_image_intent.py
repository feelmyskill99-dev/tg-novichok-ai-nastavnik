"""Tests for core/image_intent.py."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.image_intent import (
    looks_like_ai_image_request,
    looks_like_image_request,
    looks_like_source_image_request,
)


# ---------- looks_like_ai_image_request ----------


@pytest.mark.parametrize("text", [
    "сгенерируй картинку",
    "Сгенери AI-картинку",
    "нарисуй мне что-нибудь",
    "сделай ai-картинку про BTC",
    "перерисуй картинку",
    "новая ai картинка",
    "regenerate image",
    "generate image please",
    "new image",
    "🖼",
    "🖼 сгенери",
    "AI картинка про крипту",
    "AI изображение про рынок",
    "тематическое изображение нужно",
])
def test_ai_image_patterns_detected(text):
    assert looks_like_ai_image_request(text) is True


@pytest.mark.parametrize("text", [
    "",
    "обычный текст без триггеров",
    "это просто заметка",
    "пост готов, публикуй",
])
def test_no_ai_intent_when_no_keywords(text):
    assert looks_like_ai_image_request(text) is False


def test_ai_intent_ignored_when_source_marker_present():
    """Generic «обнови картинку» + «из источника» → НЕ AI-intent."""
    assert looks_like_ai_image_request("обнови картинку из источника") is False


def test_ai_intent_ignored_for_long_text():
    """Очень длинный feedback (>80 chars) — не считается image-intent."""
    long_text = "сгенерируй картинку " * 10  # ~200 chars
    assert looks_like_ai_image_request(long_text) is False


def test_ai_intent_none_input():
    assert looks_like_ai_image_request(None) is False  # type: ignore


def test_ai_intent_whitespace_only():
    assert looks_like_ai_image_request("   ") is False


def test_ai_intent_generic_kartinku_without_ai():
    """«сделай картинку» без AI-маркера — всё равно AI (legacy backward-compat)."""
    assert looks_like_ai_image_request("сделай картинку") is True


def test_ai_intent_generic_izobrazh_without_ai():
    """«новое изображение» — generic, считается AI."""
    assert looks_like_ai_image_request("новое изображение") is True


# ---------- looks_like_source_image_request ----------


@pytest.mark.parametrize("text", [
    "из источника",
    "возьми из источника картинку",
    "обнови превью",
    "обнови превью источника",
    "обнови картинку из источника",
    "source image please",
    "og image",
    "og:image",
    "twitter:image",
    "🔄",
])
def test_source_image_patterns_detected(text):
    assert looks_like_source_image_request(text) is True


@pytest.mark.parametrize("text", [
    "",
    "просто текст",
    "сгенерируй ai",
])
def test_no_source_intent_when_no_keywords(text):
    assert looks_like_source_image_request(text) is False


def test_source_intent_ignored_for_long_text():
    long_text = "обнови превью " * 20
    assert looks_like_source_image_request(long_text) is False


def test_source_intent_none_input():
    assert looks_like_source_image_request(None) is False  # type: ignore


# ---------- looks_like_image_request (legacy) ----------


def test_legacy_alias_returns_true_for_ai():
    assert looks_like_image_request("сгенерируй картинку") is True


def test_legacy_alias_returns_true_for_source():
    assert looks_like_image_request("обнови превью источника") is True


def test_legacy_alias_returns_false_for_neither():
    assert looks_like_image_request("просто текст") is False


# ---------- Boundary ----------


def test_exactly_80_chars_is_allowed():
    """Граница: 80 символов — допустимая длина."""
    text = "сгенери" + " x" * 36  # ~ 7 + 72 = 79 chars
    assert looks_like_ai_image_request(text) is True


def test_81_chars_is_rejected():
    """81 символ — больше лимита, должен отклониться."""
    text = "сгенерируй картинку" + " x" * 50  # значительно > 80
    assert looks_like_ai_image_request(text) is False


def test_case_insensitive_detection():
    """Поиск регистронезависимый (lower)."""
    assert looks_like_ai_image_request("СГЕНЕРИ КАРТИНКУ") is True
    assert looks_like_source_image_request("OG:IMAGE") is True


def test_strips_whitespace_before_check():
    """Trim перед проверкой."""
    assert looks_like_ai_image_request("   сгенери картинку   ") is True
