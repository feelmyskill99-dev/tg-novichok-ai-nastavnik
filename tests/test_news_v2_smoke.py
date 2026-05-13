"""Stage 14 smoke tests for news v2 helpers."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from news.publisher import merge_hashtags


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


def test_merge_hashtags_ignores_non_btc_eth_assets():
    """Только BTC/ETH из первых двух assets идут в хэштеги."""
    # assets[:2] = ["DOGE", "PEPE"] — оба не BTC/ETH, не попадают.
    # BTC в третьей позиции отбрасывается (берём только assets[:2]).
    result = merge_hashtags(
        claude_tags=["#meme"],
        sector="memecoins_low_priority",
        assets=["DOGE", "PEPE", "BTC"],
    )
    assert "#DOGE" not in result
    assert "#PEPE" not in result
    assert "#BTC" not in result  # BTC за пределами assets[:2]


def test_merge_hashtags_btc_in_first_two_added():
    """BTC в первой позиции assets добавляется."""
    result = merge_hashtags(
        claude_tags=["#meme"],
        sector="memecoins_low_priority",
        assets=["BTC", "DOGE"],
    )
    assert "#BTC" in result
    assert "#DOGE" not in result
