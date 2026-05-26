import io
import logging
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.log_redact import RedactFilter, redact_text, REDACTED


# redact_text edge cases

def test_redact_text_with_empty_input():
    assert redact_text("") == ""


def test_redact_text_no_secrets_returns_unchanged():
    s = "Hello, this is a normal string with no secrets."
    assert redact_text(s) == s


def test_redact_multiple_secrets_in_one_line():
    s = 'token=abc and api_key="xyz"'
    expected = 'token=***REDACTED*** and api_key=***REDACTED***'
    assert redact_text(s) == expected


def test_redact_telegram_token_preserves_bot_id():
    s = "/bot123456:secret/sendMessage"
    expected = "/bot123456:***REDACTED***/sendMessage"
    assert redact_text(s) == expected


def test_redact_authorization_bearer_case_insensitive():
    """Case-insensitive: token-значение не должно остаться в выводе."""
    for token in ("xxx", "yyy", "zzz"):
        for prefix in ("authorization: bearer", "Authorization: Bearer",
                       "AUTHORIZATION: BEARER"):
            result = redact_text(f"{prefix} {token}")
            assert token not in result
            assert REDACTED in result


def test_redact_key_value_with_quotes():
    s = 'api_key="quoted_value"'
    expected = 'api_key=***REDACTED***'
    assert redact_text(s) == expected


def test_redact_key_value_single_quotes():
    s = "api_key='single_quoted'"
    expected = 'api_key=***REDACTED***'
    assert redact_text(s) == expected


def test_redact_unrelated_key_not_touched():
    s = "name=John, email=foo@bar, user_id=42"
    assert redact_text(s) == s


# RedactFilter integration

def test_filter_with_no_args():
    logger = logging.getLogger("test_no_args")
    logger.setLevel(logging.DEBUG)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.DEBUG)
    handler.addFilter(RedactFilter())
    logger.addHandler(handler)

    logger.info("hello world")
    output = stream.getvalue()
    assert "***REDACTED***" not in output


def test_filter_handles_dict_args():
    logger = logging.getLogger("test_dict_args")
    logger.setLevel(logging.DEBUG)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.DEBUG)
    handler.addFilter(RedactFilter())
    logger.addHandler(handler)

    logger.info("%(key)s", {"key": "token=secret"})
    output = stream.getvalue()
    assert "token=***REDACTED***" in output


def test_filter_does_not_break_on_non_string_msg():
    logger = logging.getLogger("test_non_string")
    logger.setLevel(logging.DEBUG)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.DEBUG)
    handler.addFilter(RedactFilter())
    logger.addHandler(handler)

    logger.info(42)  # int as message
    output = stream.getvalue()
    assert "42" in output


def test_filter_returns_true_always():
    record = logging.LogRecord("test", logging.INFO, "test.py", 1, "msg", (), None)
    filter_obj = RedactFilter()
    assert filter_obj.filter(record) is True


def test_filter_preserves_record_level():
    logger = logging.getLogger("test_level")
    logger.setLevel(logging.DEBUG)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.DEBUG)
    handler.addFilter(RedactFilter())
    logger.addHandler(handler)

    logger.warning("token=x")
    # Iterate over handlers to find our record level
    for handler_obj in logger.handlers:
        # We cannot easily get the record, but we can capture it via a custom handler.
        pass

    # Alternative: Create a handler that stores the last record
    class RecordKeeper(logging.Handler):
        def __init__(self):
            super().__init__()
            self.last_record = None
        def emit(self, record):
            self.last_record = record

    keeper = RecordKeeper()
    keeper.setLevel(logging.DEBUG)
    keeper.addFilter(RedactFilter())
    logger.addHandler(keeper)

    logger.warning("token=x")
    assert keeper.last_record.levelno == logging.WARNING


# Contract REDACTED

def test_redacted_constant_is_non_empty_string():
    assert isinstance(REDACTED, str)
    assert len(REDACTED) >= 3