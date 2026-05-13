"""Этап 2.6: StyleGuard как блокировка перед публикацией.

`check_payload_or_reject(payload, guard)` — pre-publish guard:
- если payload пустой или невалидный → ok=True (не блокируем missing optional fields)
- если найдено forbidden_word → ok=False, причина
- markers НЕ проверяем (soft warning, не блокировка)

При fail вызвавший должен НЕ публиковать в канал, а отправить DM владельцу.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.styleguard import StyleGuard
from core.styleguard_block import check_payload_or_reject


@pytest.fixture
def guard(tmp_path: Path) -> StyleGuard:
    p = tmp_path / "forbidden.json"
    p.write_text(json.dumps({
        "forbidden": ["торговый сигнал", "гарантированная прибыль"],
        "style_markers": ["новичок", "наставник"],
    }, ensure_ascii=False), encoding="utf-8")
    return StyleGuard(forbidden_words_file=str(p))


def test_clean_payload_passes(guard):
    payload = {
        "short_summary": "BTC консолидируется около EMA",
        "post_body": "новичок наблюдает за рынком, наставник комментирует",
    }
    ok, reason = check_payload_or_reject(payload, guard)

    assert ok
    assert reason == ""


def test_forbidden_word_blocks(guard):
    payload = {
        "short_summary": "наш торговый сигнал сегодня — long BTC",
        "post_body": "новичок, наставник",
    }
    ok, reason = check_payload_or_reject(payload, guard)

    assert not ok
    assert "торговый сигнал" in reason


def test_missing_markers_does_not_block(guard):
    """Plan 2.6: markers — soft warning, не блокировка."""
    payload = {
        "short_summary": "BTC консолидируется",
        "post_body": "обычный пост без специфических маркеров",
    }
    ok, reason = check_payload_or_reject(payload, guard)

    assert ok


def test_empty_payload_does_not_block(guard):
    """Пустой dict не должен ронять guard."""
    ok, reason = check_payload_or_reject({}, guard)

    assert ok


def test_non_string_values_ignored(guard):
    payload = {
        "short_summary": "BTC up",
        "impact_score": 95,
        "assets": ["BTC", "ETH"],
    }
    ok, reason = check_payload_or_reject(payload, guard)

    assert ok


def test_guard_is_none_does_not_block(guard):
    """Если guard не инициализирован — fail-open: пропускаем."""
    ok, reason = check_payload_or_reject({"x": "торговый сигнал"}, None)

    assert ok
    assert reason == ""
