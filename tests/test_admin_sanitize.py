"""Tests for admin_panel.sanitize_telegram_html — allowlist HTML."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def sanitize(monkeypatch: pytest.MonkeyPatch):
    """Загружает admin_panel с валидным паролем — нужно для импорта модуля."""
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret!Strong#42")
    monkeypatch.setenv("TELEGRAM_TOKEN", "test:token")
    import dotenv as _dotenv
    monkeypatch.setattr(_dotenv, "load_dotenv", lambda *a, **kw: True)
    sys.modules.pop("admin_panel", None)
    mod = importlib.import_module("admin_panel")
    return mod.sanitize_telegram_html


def test_plain_text_unchanged(sanitize):
    assert sanitize("hello world") == "hello world"


def test_empty_string_returns_empty(sanitize):
    assert sanitize("") == ""


def test_allowed_bold_preserved(sanitize):
    assert sanitize("<b>важно</b>") == "<b>важно</b>"


def test_allowed_italic_preserved(sanitize):
    assert sanitize("<i>текст</i>") == "<i>текст</i>"


def test_allowed_code_preserved(sanitize):
    assert sanitize("<code>x = 1</code>") == "<code>x = 1</code>"


def test_strong_em_pre_u_s_allowed(sanitize):
    for tag in ("strong", "em", "pre", "u", "s"):
        result = sanitize(f"<{tag}>x</{tag}>")
        assert f"<{tag}>" in result
        assert f"</{tag}>" in result


def test_script_tag_escaped(sanitize):
    result = sanitize("<script>alert(1)</script>")
    assert "<script>" not in result
    assert "&lt;script&gt;" in result
    assert "alert(1)" in result


def test_unknown_tag_escaped(sanitize):
    result = sanitize("<marquee>spam</marquee>")
    assert "<marquee>" not in result
    assert "&lt;marquee&gt;" in result


def test_a_tag_with_https_href_preserved(sanitize):
    result = sanitize('<a href="https://example.com">link</a>')
    assert 'href="https://example.com"' in result
    assert "link</a>" in result


def test_a_tag_with_http_href_preserved(sanitize):
    result = sanitize('<a href="http://example.com">x</a>')
    assert 'href="http://example.com"' in result


def test_a_tag_with_javascript_href_dropped(sanitize):
    """javascript: scheme опасен, тег должен исчезнуть, текст остаться."""
    result = sanitize('<a href="javascript:alert(1)">click</a>')
    assert "javascript" not in result
    assert "<a href" not in result
    assert "click" in result


def test_a_tag_without_href_dropped(sanitize):
    """Без href тег <a> бесполезен и игнорируется."""
    result = sanitize("<a>orphan</a>")
    # Открывающий <a> без href отбрасывается, закрывающий </a> сохраняется.
    assert "<a>" not in result
    assert "orphan" in result


def test_mixed_safe_and_unsafe(sanitize):
    raw = '<b>ok</b> <script>bad</script> <a href="https://x.io">link</a>'
    result = sanitize(raw)
    assert "<b>ok</b>" in result
    assert "<script>" not in result
    assert 'href="https://x.io"' in result


def test_html_entities_not_double_escaped(sanitize):
    """Голые `<` `>` экранируются. Готовые entities `&amp;` тоже escape'ятся
    (становятся `&amp;amp;`) — это поведение html.escape с quote=False."""
    result = sanitize("a < b > c")
    assert "a &lt; b &gt; c" == result


def test_href_with_double_quote_in_value_is_safe(sanitize):
    """href с двойной кавычкой в значении не должен сломать output."""
    raw = '<a href="https://example.com">ok</a>'
    result = sanitize(raw)
    assert "https://example.com" in result
    assert 'href="' in result
