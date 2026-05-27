"""Stage 14e — флаг страны перед title_emoji в news постах.

Берём паттерн у @markettwits (см. outputs/markettwits_sample.json):
заголовок начинается с 🇷🇺🇺🇸 + категория-теги + суть.

Тесты только на pure helper detect_country_flag. Интеграция через
build_post_html (где prefix приклеивается) — покрыта существующими
test_news_v2_smoke + ручным прогоном через смоки.
"""
from __future__ import annotations

from news.publisher import detect_country_flag


def test_detects_trump_as_us():
    assert detect_country_flag("Trump signs new executive order") == "🇺🇸"


def test_detects_russia_via_cyrillic():
    assert detect_country_flag("ЦБ РФ обсудил с Минфином") == "🇷🇺"


def test_detects_iran():
    assert detect_country_flag("Tehran exchange got hacked") == "🇮🇷"


def test_detects_japan():
    assert detect_country_flag("Япония запускает иеновый стейблкоин") == "🇯🇵"


def test_detects_eu_via_mica_keyword_is_us_first():
    # SEC + MiCA — оба есть, SEC (US) идёт первым в COUNTRY_FLAGS словаре.
    # Подтверждаем, что порядок словаря важен.
    assert detect_country_flag("SEC одобрила MiCA") == "🇺🇸"


def test_no_geo_marker_returns_empty():
    assert detect_country_flag("Bitcoin держится у $80k") == ""


def test_strategy_alone_is_not_us():
    """Strategy (MicroStrategy) — не должно ловиться как страна.

    Защита от false-positive: ключевые слова в словаре должны быть
    специфичными, не общими.
    """
    assert detect_country_flag("Strategy выкупает собственный долг") == ""


def test_empty_input():
    assert detect_country_flag("") == ""
    assert detect_country_flag("", "", "") == ""


def test_multiple_texts_concat():
    """detect_country_flag принимает несколько текстов (title + lead + summary)."""
    assert detect_country_flag("Crypto news", "", "Powell speaks at Fed") == "🇺🇸"


def test_first_match_wins():
    """Если в тексте упомянуты несколько стран — берём первую по словарю.

    🇺🇸 идёт раньше 🇷🇺 в COUNTRY_FLAGS → US-маркер выигрывает.
    """
    # «Trump» (US, шаг 1 в словаре) + «Russia» (RU, шаг 2)
    assert detect_country_flag("Trump and Russia sign deal") == "🇺🇸"


def test_case_insensitive():
    assert detect_country_flag("TRUMP") == "🇺🇸"
    assert detect_country_flag("trump") == "🇺🇸"
    assert detect_country_flag("Trump") == "🇺🇸"


def test_none_input_safe():
    """Принимает None как аргумент без падения."""
    assert detect_country_flag(None) == ""
    assert detect_country_flag(None, "Trump", None) == "🇺🇸"
