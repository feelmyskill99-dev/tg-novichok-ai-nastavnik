"""Stage 14 smoke tests for news v2 helpers."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from news.publisher import merge_hashtags, normalize_payload_v2, SECTOR_EMOJI_FALLBACK
from news.models import NewsItem


def _make_item(sector="ai_crypto", title="test", url="https://example.com/x"):
    return NewsItem(
        title=title, url=url, source="src", published_at="",
        summary="", assets=[], category="other", sector=sector,
        impact_score=80.0,
    )


def test_merge_hashtags_basic():
    """Базовый merge: rubric + claude_tags + assets, max 4."""
    result = merge_hashtags(
        claude_tags=["#DeFi", "#whitehat"],
        sector="security_hacks_scams",
        assets=["BTC"],
    )
    assert result == ["#безопасность_депозита", "#BTC", "#DeFi", "#whitehat"]


def test_merge_hashtags_caps_at_4():
    """Max 4 даже если входов больше."""
    result = merge_hashtags(
        claude_tags=["#DeFi", "#whitehat", "#hack", "#audit", "#extra"],
        sector="security_hacks_scams",
        assets=["BTC", "ETH"],
    )
    assert len(result) == 4
    assert result[0] == "#безопасность_депозита"
    assert "#BTC" in result and "#ETH" in result


def test_merge_hashtags_dedupe_case_insensitive():
    """Дедупликация регистронезависимая, порядок сохраняется."""
    result = merge_hashtags(
        claude_tags=["#defi", "#DeFi", "#WhiteHat"],
        sector="security_hacks_scams",
        assets=[],
    )
    # rubric + #defi (первая встреченная) + #WhiteHat
    assert result == ["#безопасность_депозита", "#defi", "#WhiteHat"]


def test_merge_hashtags_no_rubric_no_assets():
    """Если sector неизвестен и нет assets — только claude_tags."""
    result = merge_hashtags(
        claude_tags=["#xyz", "#abc"],
        sector="unknown_sector",
        assets=[],
    )
    assert result == ["#xyz", "#abc"]


def test_merge_hashtags_ticker_whitelist_known_assets():
    """Stage 14c: asset-тикеры из whitelist первых двух assets попадают
    в хэштеги (раньше — только BTC/ETH, теперь 25 крупных)."""
    # DOGE и PEPE теперь в whitelist
    result = merge_hashtags(
        claude_tags=["#meme"],
        sector="memecoins_low_priority",
        assets=["DOGE", "PEPE", "BTC"],
    )
    assert "#DOGE" in result
    assert "#PEPE" in result
    assert "#BTC" not in result  # BTC за пределами assets[:2]


def test_merge_hashtags_ignores_unknown_assets():
    """Тикеры вне whitelist (например, NEWCOIN123) НЕ попадают как хэштеги."""
    result = merge_hashtags(
        claude_tags=["#smth"],
        sector="memecoins_low_priority",
        assets=["NEWCOIN123", "WTF"],
    )
    assert "#NEWCOIN123" not in result
    assert "#WTF" not in result


def test_merge_hashtags_btc_in_first_two_added():
    """BTC в первой позиции assets добавляется."""
    result = merge_hashtags(
        claude_tags=["#meme"],
        sector="memecoins_low_priority",
        assets=["BTC", "DOGE"],
    )
    assert "#BTC" in result
    # DOGE теперь тоже в whitelist (Stage 14c)
    assert "#DOGE" in result


# --- normalize_payload_v2 -------------------------------------------------


def test_normalize_fills_title_emoji_from_sector():
    """Если Claude не дал title_emoji — берём из SECTOR_EMOJI_FALLBACK."""
    payload = {
        "should_publish": True,
        "specific_title": "Some title",
        "lead": "x" * 100,
        "facts": ["a" * 50, "b" * 50, "c" * 50],
        "newbie_voice": "y" * 50,
        "tone": "calm",
    }
    item = _make_item(sector="ai_crypto")
    normalized = normalize_payload_v2(payload, item)
    assert normalized["title_emoji"] == SECTOR_EMOJI_FALLBACK["ai_crypto"]


def test_normalize_keeps_explicit_emoji():
    """Если title_emoji уже задан Claude — не перезаписываем."""
    payload = {
        "should_publish": True,
        "specific_title": "Some title",
        "title_emoji": "🎯",
        "lead": "x" * 100,
        "facts": ["a" * 50, "b" * 50, "c" * 50],
        "newbie_voice": "y" * 50,
        "tone": "harsh",
    }
    item = _make_item(sector="security_hacks_scams")
    normalized = normalize_payload_v2(payload, item)
    assert normalized["title_emoji"] == "🎯"


def test_normalize_fixes_invalid_tone():
    """Если tone не из enum — заменяем на pick_tone."""
    payload = {
        "should_publish": True,
        "specific_title": "Some title",
        "lead": "x" * 100,
        "facts": ["a" * 50, "b" * 50, "c" * 50],
        "newbie_voice": "y" * 50,
        "tone": "weird_unknown_tone",
    }
    item = _make_item(sector="security_hacks_scams")
    normalized = normalize_payload_v2(payload, item)
    assert normalized["tone"] in ("harsh", "confused", "ironic", "calm")


def test_normalize_does_not_mutate_input():
    """normalize возвращает новый dict, не трогает входной."""
    payload = {"should_publish": True, "tone": "invalid"}
    item = _make_item()
    original = dict(payload)
    normalize_payload_v2(payload, item)
    assert payload == original


def test_final_caption_guard_passes_valid():
    from news.publisher import final_caption_guard
    html = "<b>Title</b>\n\nLead text\n\n➤ fact"
    ok, reason = final_caption_guard(html)
    assert ok is True
    assert reason == ""


def test_final_caption_guard_rejects_over_limit():
    from news.publisher import final_caption_guard
    html = "x" * 1100
    ok, reason = final_caption_guard(html)
    assert ok is False
    assert "1024" in reason


def test_final_caption_guard_rejects_broken_html_tag():
    from news.publisher import final_caption_guard
    html = "<b>Title without closing"
    ok, reason = final_caption_guard(html)
    assert ok is False
    assert "html" in reason.lower() or "tag" in reason.lower()


def test_normalize_applies_merge_hashtags():
    """normalize прогоняет хэштеги через merge_hashtags."""
    payload = {
        "should_publish": True,
        "tone": "harsh",
        "hashtags": ["#DeFi"],
    }
    item = _make_item(sector="security_hacks_scams")
    item.assets = ["BTC"]
    normalized = normalize_payload_v2(payload, item)
    # rubric + #BTC + #DeFi
    assert normalized["hashtags"][0] == "#безопасность_депозита"
    assert "#BTC" in normalized["hashtags"]
    assert "#DeFi" in normalized["hashtags"]
