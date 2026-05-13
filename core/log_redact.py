"""Redact-фильтр для логов (этап 1.7).

Маскирует чувствительные значения в строках логов:
- Telegram bot-token в URL (`/bot<id>:<token>/`)
- key-value пары: `api_key=...`, `token=...`, `secret=...`, `authorization=...`,
  `Authorization: Bearer ...`

Использование:
    handler.addFilter(RedactFilter())
"""
from __future__ import annotations

import logging
import re
from typing import Any

REDACTED = "***REDACTED***"

# Telegram bot-token в URL: `/bot<digits>:<base64ish>/`
_TG_TOKEN_RE = re.compile(r"/bot(\d+):([A-Za-z0-9_\-]+)")

# Authorization: Bearer <token>
_AUTH_BEARER_RE = re.compile(r"(Authorization\s*:\s*Bearer\s+)\S+", re.IGNORECASE)

# Key=value / key: "value" / key: value — общий паттерн для секретов.
_KV_KEYS = ("api_key", "apikey", "token", "secret", "authorization", "auth_token")
_KV_RE = re.compile(
    r"\b(" + "|".join(_KV_KEYS) + r")"
    r"(\s*[:=]\s*)"
    r'("[^"]+"|\'[^\']+\'|[^\s,;]+)',
    re.IGNORECASE,
)


def redact_text(text: str) -> str:
    if not text:
        return text

    text = _TG_TOKEN_RE.sub(lambda m: f"/bot{m.group(1)}:{REDACTED}", text)
    text = _AUTH_BEARER_RE.sub(lambda m: f"{m.group(1)}{REDACTED}", text)
    text = _KV_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
    return text


class RedactFilter(logging.Filter):
    """Маскирует секреты в `record.msg` и в форматированном `record.args`."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = redact_text(record.msg)
            if record.args:
                if isinstance(record.args, tuple):
                    record.args = tuple(self._redact_arg(a) for a in record.args)
                elif isinstance(record.args, dict):
                    record.args = {k: self._redact_arg(v) for k, v in record.args.items()}
        except Exception:
            # Логгер не должен падать из-за фильтра.
            pass
        return True

    @staticmethod
    def _redact_arg(arg: Any) -> Any:
        if isinstance(arg, str):
            return redact_text(arg)
        return arg
