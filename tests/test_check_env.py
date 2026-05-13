"""Этап 1.7: smoke-check для .env."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from check_env import check_env, ADMIN_FORBIDDEN_PASSWORDS


_VALID_ENV = {
    "TELEGRAM_TOKEN": "123:abc",
    "CHANNEL_ID": "@chan",
    "OWNER_CHAT_ID": "1",
    "CLAUDE_API_KEY": "sk-x",
    "OPENAI_API_KEY": "sk-y",
    "PARTNER_URL": "https://example.com",
    "DRY_RUN": "true",
    "GENERATE_IMAGES": "true",
    "GENERATE_VIDEO": "false",
    "ENABLE_WEBHOOK": "false",
}


def test_valid_env_passes():
    ok, missing, problems = check_env(env=_VALID_ENV)

    assert ok, f"missing={missing} problems={problems}"


def test_missing_required_reports_them():
    env = dict(_VALID_ENV)
    del env["CLAUDE_API_KEY"]
    env["OPENAI_API_KEY"] = ""  # пустое тоже считается missing

    ok, missing, _ = check_env(env=env)

    assert not ok
    assert "CLAUDE_API_KEY" in missing
    assert "OPENAI_API_KEY" in missing


def test_wrong_flag_reported():
    env = dict(_VALID_ENV)
    env["DRY_RUN"] = "false"  # ожидается true

    ok, _, problems = check_env(env=env)

    assert not ok
    assert "DRY_RUN" in problems


def test_weak_admin_password_reported():
    env = dict(_VALID_ENV)
    env["ADMIN_PASSWORD"] = "changeme"

    ok, _, problems = check_env(env=env)

    assert not ok
    assert "ADMIN_PASSWORD" in problems


def test_strong_admin_password_ok():
    env = dict(_VALID_ENV)
    env["ADMIN_PASSWORD"] = "s3cret!Strong#42"

    ok, _, _ = check_env(env=env)

    assert ok


def test_empty_admin_password_allowed_for_cli_only():
    """Пустой ADMIN_PASSWORD не блокирует CLI бот; только админка fail-fast при старте."""
    env = dict(_VALID_ENV)
    env["ADMIN_PASSWORD"] = ""

    ok, _, _ = check_env(env=env)

    assert ok
