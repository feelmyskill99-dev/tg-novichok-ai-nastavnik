import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.telegram_send import split_html_for_telegram


def test_limit_one_char_returns_each_char():
    text = "abcde"
    result = split_html_for_telegram(text, limit=1)
    assert len(result) == 5
    for c in result:
        assert len(c) == 1


def test_very_small_limit_with_html():
    """При limit меньше длины самого тега </b> (5 chars) гарантия баланса
    невозможна — алгоритм только обеспечивает progress без infinite loop."""
    text = "<b>hello world</b>"
    result = split_html_for_telegram(text, limit=10)
    assert isinstance(result, list)
    for chunk in result:
        assert len(chunk) <= 10


def test_limit_larger_than_text():
    text = "hello"
    result = split_html_for_telegram(text, limit=100)
    assert result == ["hello"]


def test_zero_limit_does_not_infinite_loop():
    text = "hello"
    result = split_html_for_telegram(text, limit=0)
    assert isinstance(result, list)


def test_flat_tags_split_keeps_balance():
    """Flat (не вложенные) теги: алгоритм гарантирует opens==closes в каждом
    куске. Вложенные теги (<b><i>...</i></b>) алгоритм НЕ гарантирует —
    он считает opens/closes как множества, не учитывая вложенность."""
    fragment = "<b>important</b> "
    text = fragment * 2000
    limit = 4096
    result = split_html_for_telegram(text, limit=limit)
    for chunk in result:
        assert len(chunk) <= limit
        assert chunk.count("<b>") == chunk.count("</b>")


def test_self_closing_like_tag_handled():
    text = "<br> some text <hr> more"
    result = split_html_for_telegram(text)
    assert isinstance(result, list)


def test_html_entities_preserved():
    text = "&amp; &lt; &gt; &quot; " * 500   # more than 4096 total
    result = split_html_for_telegram(text)
    for entity in ["&amp;", "&lt;", "&gt;", "&quot;"]:
        assert any(entity in chunk for chunk in result)


def test_text_with_only_newlines():
    assert split_html_for_telegram("\n\n\n\n") == []


def test_text_with_tabs_only():
    assert split_html_for_telegram("\t\t\t") == []


def test_text_with_unicode_whitespace_only():
    assert split_html_for_telegram("    ") == []


def test_30k_text_splits_into_8_or_more_chunks():
    text = "abc " * 7500   # 30000 chars
    result = split_html_for_telegram(text)
    assert len(result) >= 8
    total_chars = sum(len(c) for c in result)
    assert total_chars >= 29000
    for chunk in result:
        assert len(chunk) <= 4096


def test_huge_single_word_no_spaces():
    text = "x" * 6000
    result = split_html_for_telegram(text)
    assert len(result) >= 2
    for chunk in result:
        assert len(chunk) <= 4096


def test_return_type_is_list_of_str():
    for text in ("hello", "", "<b>bold</b>", " a " * 2000):
        result = split_html_for_telegram(text)
        assert isinstance(result, list)
        assert all(isinstance(c, str) for c in result)


def test_chunks_have_no_empty_strings():
    for text in ("hello", "<b>bold</b>", " a " * 2000):
        result = split_html_for_telegram(text)
        assert "" not in result