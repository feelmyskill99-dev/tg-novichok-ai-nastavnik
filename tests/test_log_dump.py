"""Tests for core/log_dump.py."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.log_dump import safe_log_dict


def test_safe_log_dict_basic():
    assert safe_log_dict({"key": "value"}) == '{"key": "value"}'


def test_safe_log_dict_list():
    assert safe_log_dict([1, 2, 3]) == "[1, 2, 3]"


def test_safe_log_dict_unicode_preserved():
    result = safe_log_dict({"msg": "привет"})
    assert "привет" in result


def test_safe_log_dict_truncates_at_limit():
    big = {"x": "a" * 1000}
    result = safe_log_dict(big, limit=50)
    assert len(result) == 50


def test_safe_log_dict_default_limit_500():
    big = {"x": "a" * 2000}
    result = safe_log_dict(big)
    assert len(result) == 500


def test_safe_log_dict_none_value():
    assert safe_log_dict(None) == "null"


def test_safe_log_dict_int_value():
    assert safe_log_dict(42) == "42"


def test_safe_log_dict_bool_value():
    assert safe_log_dict(True) == "true"
    assert safe_log_dict(False) == "false"


def test_safe_log_dict_nested():
    result = safe_log_dict({"a": {"b": [1, 2]}})
    assert '"a"' in result
    assert '"b"' in result
    assert "[1, 2]" in result


def test_safe_log_dict_non_serializable_fallback_via_str():
    """default=str превращает не-JSON-объекты в строки."""
    class _Custom:
        def __str__(self):
            return "CustomObject(x=1)"

    result = safe_log_dict({"obj": _Custom()})
    assert "CustomObject(x=1)" in result


def test_safe_log_dict_set_via_default_str():
    """set не JSON-сериализуем, default=str → 'set(...)' repr."""
    result = safe_log_dict({"items": {1, 2, 3}})
    # default=str вернёт str({1,2,3}) → "{1, 2, 3}"
    assert "1" in result and "2" in result


def test_safe_log_dict_empty_dict():
    assert safe_log_dict({}) == "{}"


def test_safe_log_dict_empty_list():
    assert safe_log_dict([]) == "[]"


def test_safe_log_dict_empty_string():
    assert safe_log_dict("") == '""'


def test_safe_log_dict_long_unicode_truncates_correctly():
    """Truncation работает по character-count, не byte-count."""
    s = "ё" * 1000  # 1000 кириллицы (в UTF-8 = 2000 bytes, но 1000 chars)
    result = safe_log_dict({"x": s}, limit=100)
    assert len(result) == 100


def test_safe_log_dict_limit_zero_returns_empty():
    assert safe_log_dict({"x": 1}, limit=0) == ""


def test_safe_log_dict_limit_larger_than_content():
    result = safe_log_dict({"x": 1}, limit=10000)
    assert result == '{"x": 1}'


def test_safe_log_dict_circular_reference_fallback_to_str():
    """Циклические ссылки — json.dumps падает, falls back to str(value)."""
    a = {}
    a["self"] = a  # circular
    # safe_log_dict не должен бросать, даже если str(a) тоже сломается.
    result = safe_log_dict(a)
    assert isinstance(result, str)


def test_safe_log_dict_returns_string():
    """Контракт: всегда str, никогда не None / exception."""
    for v in [None, 0, "", [], {}, [1, 2], {"a": 1}, True]:
        assert isinstance(safe_log_dict(v), str)
