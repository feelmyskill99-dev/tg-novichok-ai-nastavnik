"""Tests for core/post_tags.py."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.post_tags import merge_tags, normalize_tags, system_tags_for


# ---------- normalize_tags ----------


def test_normalize_tags_adds_hash():
    assert normalize_tags(["bitcoin", "btc"]) == ["#bitcoin", "#btc"]


def test_normalize_tags_keeps_existing_hash():
    assert normalize_tags(["#bitcoin"]) == ["#bitcoin"]


def test_normalize_tags_dedupes_preserving_order():
    assert normalize_tags(["btc", "eth", "btc", "#btc"]) == ["#btc", "#eth"]


def test_normalize_tags_empty_input():
    assert normalize_tags([]) == []
    assert normalize_tags(None) == []


def test_normalize_tags_strips_whitespace_and_skips_empty():
    assert normalize_tags(["  bitcoin  ", "", "  ", "eth"]) == ["#bitcoin", "#eth"]


def test_normalize_tags_handles_non_string():
    """Числа, объекты — приводим к str."""
    result = normalize_tags([123, "btc"])
    assert "#123" in result
    assert "#btc" in result


# ---------- system_tags_for ----------


def test_system_tags_normal_post_without_hamster():
    tags = system_tags_for("market", has_hamster=False)
    assert "#честный_путь" in tags
    assert "#ошибки_новичка" in tags
    assert "#не_будь_хомяком" not in tags


def test_system_tags_with_hamster_uses_hamster_tag():
    tags = system_tags_for("market", has_hamster=True)
    assert "#не_будь_хомяком" in tags
    assert "#ошибки_новичка" not in tags


def test_system_tags_flash_post_includes_flash_tag():
    tags = system_tags_for("flash", has_hamster=False)
    assert "#flash" in tags


def test_system_tags_fallback_education_includes_term_tag():
    tags = system_tags_for("fallback_education", has_hamster=False)
    assert "#термин_без_боли" in tags


def test_system_tags_unknown_post_type_no_extra_tag():
    tags = system_tags_for("unknown_type", has_hamster=False)
    assert "#flash" not in tags
    assert "#термин_без_боли" not in tags
    # Только базовые
    assert "#честный_путь" in tags
    assert "#ошибки_новичка" in tags


# ---------- merge_tags ----------


def test_merge_tags_combines_claude_and_system():
    tags = merge_tags(["bitcoin", "eth"], post_type="market", has_hamster=False)
    assert "#bitcoin" in tags
    assert "#eth" in tags
    assert "#честный_путь" in tags


def test_merge_tags_dedupes_overlap():
    """Если Claude уже выдал #ошибки_новичка — не должен дублироваться."""
    tags = merge_tags(["#ошибки_новичка", "bitcoin"], post_type="market", has_hamster=False)
    assert tags.count("#ошибки_новичка") == 1
    assert "#bitcoin" in tags


def test_merge_tags_preserves_claude_first_order():
    tags = merge_tags(["btc", "eth"], post_type="market", has_hamster=False)
    # Claude-теги идут первыми, system-теги после
    btc_idx = tags.index("#btc")
    sys_idx = tags.index("#честный_путь")
    assert btc_idx < sys_idx


def test_merge_tags_empty_claude_tags():
    tags = merge_tags([], post_type="flash", has_hamster=True)
    # Только системные
    assert tags == ["#честный_путь", "#не_будь_хомяком", "#flash"]


def test_merge_tags_none_claude_tags():
    tags = merge_tags(None, post_type="market", has_hamster=False)
    assert "#честный_путь" in tags


# ---------- rotation (rebranding-1.3) ----------


def test_anchor_tag_always_present_with_seed():
    """#честный_путь — всегда есть, даже при ротации."""
    from datetime import date, timedelta
    start = date(2026, 5, 1)
    for i in range(30):
        tags = system_tags_for("market", has_hamster=True, day_seed=start + timedelta(days=i))
        assert "#честный_путь" in tags


def test_secondary_tag_rotates_across_week_with_hamster():
    """Вторичный тег покрывает ≥3 разных значения за 7 дней."""
    from datetime import date, timedelta
    start = date(2026, 5, 1)
    seen = set()
    for i in range(7):
        tags = system_tags_for("market", has_hamster=True, day_seed=start + timedelta(days=i))
        secondary = [t for t in tags if t != "#честный_путь"][:1]
        seen.update(secondary)
    assert len(seen) >= 3, f"expected ≥3 variants across 7 days, got {seen}"


def test_secondary_tag_rotates_across_week_no_hamster():
    from datetime import date, timedelta
    start = date(2026, 5, 1)
    seen = set()
    for i in range(7):
        tags = system_tags_for("market", has_hamster=False, day_seed=start + timedelta(days=i))
        secondary = [t for t in tags if t != "#честный_путь"][:1]
        seen.update(secondary)
    assert len(seen) >= 3


def test_education_keeps_termin_tag_with_seed():
    from datetime import date
    tags = system_tags_for("fallback_education", has_hamster=False, day_seed=date(2026, 5, 26))
    assert "#термин_без_боли" in tags
    assert "#честный_путь" in tags


def test_flash_keeps_flash_tag_with_seed():
    from datetime import date
    tags = system_tags_for("flash", has_hamster=True, day_seed=date(2026, 5, 26))
    assert "#flash" in tags


def test_merge_tags_with_seed_rotates():
    from datetime import date
    a = merge_tags(["btc"], post_type="market", has_hamster=True, day_seed=date(2026, 5, 1))
    b = merge_tags(["btc"], post_type="market", has_hamster=True, day_seed=date(2026, 5, 2))
    # хотя бы один из тегов отличается между двумя днями
    assert set(a) != set(b)
