import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.html_safe import escape_html, sanitize_telegram_html


# ---------------------------------------------------------------------------
# escape_html
# ---------------------------------------------------------------------------

def test_escape_html_with_float_value():
    assert escape_html(3.14) == "3.14"


def test_escape_html_with_bool():
    assert escape_html(True) == "True"
    assert escape_html(False) == "False"


def test_escape_html_with_list_coerces_via_str():
    assert escape_html([1, 2]) == "[1, 2]"


def test_escape_html_with_dict():
    result = escape_html({"a": 1})
    assert "a" in result
    assert "1" in result


def test_escape_html_only_amp_lt_gt_escaped():
    assert escape_html("&<>") == "&amp;&lt;&gt;"


def test_escape_html_unicode_preserved():
    assert escape_html("привет мир 🌍") == "привет мир 🌍"


def test_escape_html_newlines_preserved():
    assert escape_html("a\nb") == "a\nb"


# ---------------------------------------------------------------------------
# sanitize_telegram_html — XSS vectors
# ---------------------------------------------------------------------------

def test_sanitize_data_uri_href_dropped():
    result = sanitize_telegram_html('<a href="data:text/html,...">x</a>')
    assert "x" in result
    assert "data:" not in result
    assert "<a" not in result


def test_sanitize_relative_href_dropped():
    result = sanitize_telegram_html('<a href="/path">x</a>')
    assert "x" in result
    assert "<a" not in result


def test_sanitize_uppercase_javascript_dropped():
    result = sanitize_telegram_html('<a href="JavaScript:alert(1)">x</a>')
    assert "x" in result
    assert "<a" not in result


def test_sanitize_with_no_quotes_around_href_dropped():
    result = sanitize_telegram_html('<a href=https://x.com>y</a>')
    assert "y" in result
    assert "<a" not in result


def test_sanitize_a_with_single_quotes_href_dropped():
    result = sanitize_telegram_html("<a href='https://x.com'>y</a>")
    assert "y" in result
    assert "<a" not in result


# ---------------------------------------------------------------------------
# sanitize_telegram_html — broken HTML
# ---------------------------------------------------------------------------

def test_sanitize_unclosed_tag():
    result = sanitize_telegram_html("<b>missing close")
    assert result == "<b>missing close"


def test_sanitize_only_opening_angle():
    result = sanitize_telegram_html("a < b")
    assert result == "a &lt; b"


def test_sanitize_malformed_attribute():
    # doesn't throw, returns some string
    result = sanitize_telegram_html('<b class="oops>text</b>')
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# sanitize_telegram_html — nested
# ---------------------------------------------------------------------------

def test_sanitize_b_inside_i_preserves_both():
    result = sanitize_telegram_html("<i><b>nested</b></i>")
    assert result == "<i><b>nested</b></i>"


def test_sanitize_disallowed_inside_allowed_escaped():
    result = sanitize_telegram_html("<b><script>alert(1)</script></b>")
    assert "<b>" in result
    assert "&lt;script&gt;" in result
    assert "&lt;/script&gt;" in result


def test_sanitize_self_closing_br_escaped():
    result = sanitize_telegram_html("<br>")
    assert result == "&lt;br&gt;"


# ---------------------------------------------------------------------------
# sanitize_telegram_html — Unicode + edge
# ---------------------------------------------------------------------------

def test_sanitize_preserves_emoji_text():
    result = sanitize_telegram_html("<b>Привет 🐹</b>")
    assert "<b>Привет 🐹</b>" in result


def test_sanitize_only_whitespace_returns_empty_or_whitespace():
    result = sanitize_telegram_html("   ")
    assert isinstance(result, str)


def test_sanitize_empty_returns_empty():
    assert sanitize_telegram_html("") == ""