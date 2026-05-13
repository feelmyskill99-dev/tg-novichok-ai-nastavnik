"""Tests for core/html_safe.py."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.html_safe import escape_html, sanitize_telegram_html


# ---------- escape_html ----------


def test_escape_html_basic():
    assert escape_html("hello") == "hello"


def test_escape_html_special_chars():
    assert escape_html("<b>x</b>") == "&lt;b&gt;x&lt;/b&gt;"


def test_escape_html_ampersand():
    assert escape_html("a & b") == "a &amp; b"


def test_escape_html_none_returns_empty():
    assert escape_html(None) == ""


def test_escape_html_int_coerced():
    assert escape_html(42) == "42"


def test_escape_html_does_not_escape_quotes():
    """quote=False — двойные/одинарные кавычки не трогаем (мы не в attr)."""
    assert escape_html('say "hi"') == 'say "hi"'


def test_escape_html_empty_string():
    assert escape_html("") == ""


# ---------- sanitize_telegram_html ----------


def test_sanitize_plain_text_unchanged():
    assert sanitize_telegram_html("hello world") == "hello world"


def test_sanitize_empty_returns_empty():
    assert sanitize_telegram_html("") == ""


def test_sanitize_allowed_b_preserved():
    assert sanitize_telegram_html("<b>x</b>") == "<b>x</b>"


def test_sanitize_all_allowed_tags():
    for tag in ("b", "strong", "i", "em", "u", "s", "code", "pre"):
        result = sanitize_telegram_html(f"<{tag}>x</{tag}>")
        assert f"<{tag}>" in result
        assert f"</{tag}>" in result


def test_sanitize_script_escaped():
    result = sanitize_telegram_html("<script>alert(1)</script>")
    assert "<script>" not in result
    assert "&lt;script&gt;" in result
    assert "alert(1)" in result


def test_sanitize_unknown_tag_escaped():
    result = sanitize_telegram_html("<marquee>spam</marquee>")
    assert "<marquee>" not in result
    assert "&lt;marquee&gt;" in result


def test_sanitize_a_with_https_href():
    result = sanitize_telegram_html('<a href="https://example.com">x</a>')
    assert 'href="https://example.com"' in result
    assert "x</a>" in result


def test_sanitize_a_with_http_href():
    result = sanitize_telegram_html('<a href="http://example.com">x</a>')
    assert 'href="http://example.com"' in result


def test_sanitize_a_with_javascript_href_dropped():
    result = sanitize_telegram_html('<a href="javascript:alert(1)">click</a>')
    assert "javascript" not in result
    assert "<a href" not in result
    assert "click" in result


def test_sanitize_a_without_href_dropped():
    result = sanitize_telegram_html("<a>orphan</a>")
    assert "<a>" not in result
    assert "orphan" in result


def test_sanitize_mixed_safe_unsafe():
    raw = '<b>ok</b> <script>bad</script> <a href="https://x.io">link</a>'
    result = sanitize_telegram_html(raw)
    assert "<b>ok</b>" in result
    assert "<script>" not in result
    assert 'href="https://x.io"' in result


def test_sanitize_bare_angles_escaped():
    result = sanitize_telegram_html("a < b > c")
    assert result == "a &lt; b &gt; c"
