"""Этап 1.7: redact-фильтр для логов.

`RedactFilter` — logging.Filter, который маскирует значения чувствительных полей:
    token, api_key, secret, authorization, и Telegram bot-token в URL.
"""
from __future__ import annotations

import logging
import sys
from io import StringIO
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.log_redact import RedactFilter, redact_text


# --- Чистая функция redact_text ----------------------------------------------


def test_redact_telegram_bot_token_in_url():
    raw = "GET https://api.telegram.org/bot123456:ABC-DEF_secret/sendMessage"

    out = redact_text(raw)

    assert "123456:ABC-DEF_secret" not in out
    assert "***" in out or "REDACTED" in out


def test_redact_api_key_in_keyvalue():
    raw = 'api_key="sk-proj-secret-xyz"'

    out = redact_text(raw)

    assert "sk-proj-secret-xyz" not in out


def test_redact_token_field():
    raw = "token=abc123xyz extra"

    out = redact_text(raw)

    assert "abc123xyz" not in out


def test_redact_authorization_header():
    raw = "Authorization: Bearer eyJhbGciOi.secret.payload"

    out = redact_text(raw)

    assert "eyJhbGciOi.secret.payload" not in out


def test_redact_secret_keyvalue():
    raw = 'secret: "topsecret_value"'

    out = redact_text(raw)

    assert "topsecret_value" not in out


def test_short_or_no_match_passes_through():
    raw = "this is a normal log line"
    assert redact_text(raw) == raw


# --- logging.Filter integration ----------------------------------------------


def test_filter_redacts_log_record_message():
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(RedactFilter())

    logger = logging.getLogger("test_redact_filter")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    logger.info("calling token=secret-abc-123 right now")

    out = stream.getvalue()
    assert "secret-abc-123" not in out
    assert "calling token=" in out


def test_filter_redacts_log_record_args():
    """RedactFilter должен покрывать и %s-форматирование."""
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(RedactFilter())

    logger = logging.getLogger("test_redact_filter_args")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    logger.info("got url=%s", "https://api.telegram.org/bot42:SUPER_SECRET/me")

    out = stream.getvalue()
    assert "SUPER_SECRET" not in out
