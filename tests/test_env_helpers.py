"""Этап 2.3: единые env-helpers."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.env_helpers import env_bool, env_int, env_float, env_str


# --- env_bool ----------------------------------------------------------------

@pytest.mark.parametrize("value", ["1", "true", "TRUE", "True", "yes", "YES", "on", "ON"])
def test_env_bool_truthy(monkeypatch, value):
    monkeypatch.setenv("FLAG", value)
    assert env_bool("FLAG", default=False) is True


@pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "off"])
def test_env_bool_falsy(monkeypatch, value):
    monkeypatch.setenv("FLAG", value)
    assert env_bool("FLAG", default=True) is False


@pytest.mark.parametrize("value", ["", "  "])
def test_env_bool_empty_returns_default(monkeypatch, value):
    """Пустая строка трактуется как «не задан» — возвращаем default."""
    monkeypatch.setenv("FLAG", value)
    assert env_bool("FLAG", default=True) is True
    assert env_bool("FLAG", default=False) is False


def test_env_bool_unset_returns_default(monkeypatch):
    monkeypatch.delenv("FLAG", raising=False)
    assert env_bool("FLAG", default=True) is True
    assert env_bool("FLAG", default=False) is False


# --- env_int -----------------------------------------------------------------

def test_env_int_valid(monkeypatch):
    monkeypatch.setenv("N", "42")
    assert env_int("N", default=0) == 42


def test_env_int_negative(monkeypatch):
    monkeypatch.setenv("N", "-7")
    assert env_int("N", default=0) == -7


def test_env_int_invalid_returns_default(monkeypatch):
    monkeypatch.setenv("N", "not-a-number")
    assert env_int("N", default=99) == 99


def test_env_int_unset_returns_default(monkeypatch):
    monkeypatch.delenv("N", raising=False)
    assert env_int("N", default=5) == 5


def test_env_int_empty_returns_default(monkeypatch):
    monkeypatch.setenv("N", "")
    assert env_int("N", default=5) == 5


# --- env_float ---------------------------------------------------------------

def test_env_float_valid(monkeypatch):
    monkeypatch.setenv("F", "3.14")
    assert env_float("F", default=0.0) == pytest.approx(3.14)


def test_env_float_int_string(monkeypatch):
    monkeypatch.setenv("F", "42")
    assert env_float("F", default=0.0) == pytest.approx(42.0)


def test_env_float_invalid_returns_default(monkeypatch):
    monkeypatch.setenv("F", "abc")
    assert env_float("F", default=2.5) == pytest.approx(2.5)


def test_env_float_unset_returns_default(monkeypatch):
    monkeypatch.delenv("F", raising=False)
    assert env_float("F", default=1.5) == pytest.approx(1.5)


# --- env_str -----------------------------------------------------------------

def test_env_str_returns_stripped(monkeypatch):
    monkeypatch.setenv("S", "  hello  ")
    assert env_str("S", default="x") == "hello"


def test_env_str_unset_returns_default(monkeypatch):
    monkeypatch.delenv("S", raising=False)
    assert env_str("S", default="fallback") == "fallback"


def test_env_str_empty_returns_default(monkeypatch):
    """Пустая строка трактуется как «не задан» — возвращаем default."""
    monkeypatch.setenv("S", "")
    assert env_str("S", default="fallback") == "fallback"


def test_env_str_whitespace_only_returns_default(monkeypatch):
    monkeypatch.setenv("S", "   ")
    assert env_str("S", default="fallback") == "fallback"
