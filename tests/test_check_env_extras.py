import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from check_env import (
    check_env,
    ADMIN_FORBIDDEN_PASSWORDS,
    REQUIRED,
    EXPECTED_FLAGS,
)

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


def _make_env(**overrides):
    env = dict(_VALID_ENV)
    env.update(overrides)
    return env


class TestRequiredVariants:
    def test_required_whitespace_only_treated_as_missing(self):
        env = _make_env(TELEGRAM_TOKEN="   ")
        ok, missing, _ = check_env(env)
        assert ok is False
        assert "TELEGRAM_TOKEN" in missing

    @pytest.mark.parametrize("key", REQUIRED)
    def test_all_required_keys_checked(self, key):
        env = {k: v for k, v in _VALID_ENV.items() if k != key}
        ok, missing, _ = check_env(env)
        assert ok is False
        assert key in missing

    def test_missing_two_or_more_reports_all(self):
        env = {k: v for k, v in _VALID_ENV.items()
               if k not in ("CLAUDE_API_KEY", "OPENAI_API_KEY")}
        ok, missing, _ = check_env(env)
        assert ok is False
        assert "CLAUDE_API_KEY" in missing
        assert "OPENAI_API_KEY" in missing


class TestFlagVariants:
    @pytest.mark.parametrize("key", list(EXPECTED_FLAGS.keys()))
    def test_each_flag_wrong_value_reported(self, key):
        wrong = "false" if EXPECTED_FLAGS[key] == "true" else "true"
        env = _make_env(**{key: wrong})
        _, _, flag_problems = check_env(env)
        assert key in flag_problems

    def test_flag_case_insensitive_match(self):
        env = _make_env(DRY_RUN="TRUE")
        _, _, flag_problems = check_env(env)
        assert "DRY_RUN" not in flag_problems

    def test_flag_with_whitespace_stripped(self):
        env = _make_env(DRY_RUN="  true  ")
        _, _, flag_problems = check_env(env)
        assert "DRY_RUN" not in flag_problems

    def test_flag_missing_treated_as_empty_then_wrong(self):
        env = {k: v for k, v in _VALID_ENV.items() if k != "DRY_RUN"}
        _, _, flag_problems = check_env(env)
        assert "DRY_RUN" in flag_problems


class TestAdminPasswordVariants:
    @pytest.mark.parametrize("pwd", [w for w in ADMIN_FORBIDDEN_PASSWORDS if w != ""])
    def test_admin_password_weak_password_each(self, pwd):
        env = _make_env(ADMIN_PASSWORD=pwd)
        _, _, flag_problems = check_env(env)
        assert "ADMIN_PASSWORD" in flag_problems

    def test_admin_password_uppercase_forbidden_still_caught(self):
        env = _make_env(ADMIN_PASSWORD="CHANGEME")
        _, _, flag_problems = check_env(env)
        assert "ADMIN_PASSWORD" in flag_problems

    def test_admin_password_strong_passes(self):
        env = _make_env(ADMIN_PASSWORD="Tg!Bot2026XyZ")
        _, _, flag_problems = check_env(env)
        assert "ADMIN_PASSWORD" not in flag_problems

    def test_admin_password_unset_does_not_fail(self):
        env = {k: v for k, v in _VALID_ENV.items() if k != "ADMIN_PASSWORD"}
        ok, missing, flag_problems = check_env(env)
        assert ok is True
        assert "ADMIN_PASSWORD" not in flag_problems


class TestContract:
    def test_check_env_returns_tuple_of_three(self):
        result = check_env(_VALID_ENV)
        assert isinstance(result, tuple)
        assert len(result) == 3
        assert isinstance(result[0], bool)
        assert isinstance(result[1], list)
        assert isinstance(result[2], list)

    def test_check_env_with_none_reads_from_os_environ(self, monkeypatch):
        for key, value in _VALID_ENV.items():
            monkeypatch.setenv(key, value)
        ok, _, _ = check_env(env=None)
        assert ok is True

    def test_constants_contract(self):
        assert len(REQUIRED) >= 6
        assert len(EXPECTED_FLAGS) >= 4
        assert "" in ADMIN_FORBIDDEN_PASSWORDS
        assert "changeme" in ADMIN_FORBIDDEN_PASSWORDS