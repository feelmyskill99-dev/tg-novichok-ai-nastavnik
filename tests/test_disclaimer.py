from datetime import date, timedelta

from core.disclaimer import DISCLAIMER_LONG, DISCLAIMER_VARIANTS, pick_disclaimer


def test_education_post_uses_long_disclaimer():
    text = pick_disclaimer("fallback_education", day_seed=date(2026, 5, 26))
    assert text == DISCLAIMER_LONG


def test_market_post_picks_from_variants():
    text = pick_disclaimer("market", day_seed=date(2026, 5, 26))
    assert text in DISCLAIMER_VARIANTS


def test_rotation_is_deterministic_per_day():
    a = pick_disclaimer("market", day_seed=date(2026, 5, 26))
    b = pick_disclaimer("market", day_seed=date(2026, 5, 26))
    assert a == b


def test_rotation_changes_across_days():
    start = date(2026, 5, 26)
    seen = {pick_disclaimer("market", day_seed=start + timedelta(days=i)) for i in range(7)}
    assert len(seen) >= 3, "across 7 days should hit at least 3 different variants"


def test_variants_count_is_four():
    assert len(DISCLAIMER_VARIANTS) == 4
