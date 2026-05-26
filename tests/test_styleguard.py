"""Tests for core/styleguard.py — валидация post-payload перед публикацией."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.styleguard import StyleGuard


@pytest.fixture
def style_file(tmp_path: Path) -> Path:
    """Создаёт временный forbidden_words.json со списком запретов и маркеров."""
    p = tmp_path / "forbidden_words.json"
    p.write_text(
        json.dumps({
            "forbidden": ["сигнал", "гарантированно"],
            "style_markers": ["новичок", "AI-наставник"],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    return p


@pytest.fixture
def no_markers_file(tmp_path: Path) -> Path:
    """forbidden есть, маркеров нет — проверка отключения markers-check."""
    p = tmp_path / "forbidden_only.json"
    p.write_text(
        json.dumps({"forbidden": ["сигнал"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    return p


def _valid_post() -> dict:
    return {
        "human_part": "новичок задумался и решил подождать",
        "mentor_part": "AI-наставник напомнил про стоп",
        "lesson": "терпение важнее скорости",
    }


def test_validate_passes_for_well_formed_post(style_file):
    guard = StyleGuard(forbidden_words_file=str(style_file))
    ok, reason = guard.validate(_valid_post())

    assert ok
    assert reason == ""


def test_validate_rejects_missing_required_field(style_file):
    guard = StyleGuard(forbidden_words_file=str(style_file))
    post = _valid_post()
    del post["lesson"]

    ok, reason = guard.validate(post)

    assert not ok
    assert "lesson" in reason


def test_validate_rejects_forbidden_word(style_file):
    guard = StyleGuard(forbidden_words_file=str(style_file))
    post = _valid_post()
    post["human_part"] = "сигнал на покупку — новичок думает войти"

    ok, reason = guard.validate(post)

    assert not ok
    assert "сигнал" in reason


def test_validate_forbidden_case_insensitive(style_file):
    guard = StyleGuard(forbidden_words_file=str(style_file))
    post = _valid_post()
    post["mentor_part"] = "Это ГАРАНТИРОВАННО прибыль — AI-наставник"

    ok, reason = guard.validate(post)

    assert not ok
    assert "гарантированно" in reason.lower()


def test_validate_rejects_when_no_style_marker(style_file):
    guard = StyleGuard(forbidden_words_file=str(style_file))
    post = {
        "human_part": "тут просто текст",
        "mentor_part": "и здесь тоже текст",
        "lesson": "без маркеров стиля",
    }

    ok, reason = guard.validate(post)

    assert not ok
    assert "маркер" in reason.lower() or "стил" in reason.lower()


def test_validate_no_markers_config_skips_marker_check(no_markers_file):
    """Если в config нет style_markers — проверка маркеров отключается."""
    guard = StyleGuard(forbidden_words_file=str(no_markers_file))
    post = {
        "human_part": "произвольный текст",
        "mentor_part": "ещё текст",
        "lesson": "урок",
    }

    ok, reason = guard.validate(post)

    assert ok
    assert reason == ""


def test_validate_non_string_values_skipped(style_file):
    """Если в post есть не-строковые поля — они не должны падать validator."""
    guard = StyleGuard(forbidden_words_file=str(style_file))
    post = _valid_post()
    post["impact_score"] = 95
    post["assets"] = ["BTC", "ETH"]

    ok, reason = guard.validate(post)

    assert ok
    assert reason == ""
