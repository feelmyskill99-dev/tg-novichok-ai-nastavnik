"""Проверка .env: имена отсутствующих/некорректных переменных, без значений.

Используется как smoke-check перед стартом бота:
    python scripts/check_env.py
Exit code 0 — ok, 1 — есть проблемы.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]


REQUIRED = [
    "TELEGRAM_TOKEN",
    "CHANNEL_ID",
    "OWNER_CHAT_ID",
    "CLAUDE_API_KEY",
    "OPENAI_API_KEY",
    "PARTNER_URL",
]

EXPECTED_FLAGS = {
    "DRY_RUN": "true",
    "GENERATE_IMAGES": "true",
    "GENERATE_VIDEO": "false",
    "ENABLE_WEBHOOK": "false",
}

# Этап 1.5: запрещённые пароли админки.
ADMIN_FORBIDDEN_PASSWORDS = {"", "changeme", "admin", "password", "1234"}


def check_env(env: dict[str, str] | None = None) -> tuple[bool, list[str], list[str]]:
    """Чистая проверка без вывода. Возвращает (ok, missing, flag_problems).

    Args:
        env: словарь env-переменных (для теста). По умолчанию — os.environ.
    """
    src = env if env is not None else os.environ

    missing = [name for name in REQUIRED if not (src.get(name) or "").strip()]

    flag_problems: list[str] = []
    for name, expected in EXPECTED_FLAGS.items():
        actual = (src.get(name) or "").strip().lower()
        if actual != expected:
            flag_problems.append(name)

    # ADMIN_PASSWORD: проверяем только если задан (для CLI бот не требует пароль админки).
    admin_pass = (src.get("ADMIN_PASSWORD") or "").strip().lower()
    if admin_pass and admin_pass in ADMIN_FORBIDDEN_PASSWORDS:
        flag_problems.append("ADMIN_PASSWORD")

    ok = not missing and not flag_problems
    return ok, missing, flag_problems


def main() -> int:
    load_dotenv(dotenv_path=ROOT / ".env")
    ok, missing, flag_problems = check_env()

    if missing:
        print("MISSING REQUIRED:")
        for n in missing:
            print(f"  - {n}")
    else:
        print("REQUIRED: all present")

    print()
    print("FLAGS:")
    for name, expected in EXPECTED_FLAGS.items():
        actual = (os.getenv(name) or "").strip().lower()
        mark = "OK" if actual == expected else "WRONG"
        print(f"  {name}={actual or '<empty>'}  expected={expected}  [{mark}]")

    admin_pass = (os.getenv("ADMIN_PASSWORD") or "").strip().lower()
    if admin_pass:
        admin_ok = admin_pass not in ADMIN_FORBIDDEN_PASSWORDS
        print(f"  ADMIN_PASSWORD=<set>  [{'OK' if admin_ok else 'WEAK'}]")

    print()
    if not ok:
        return 1
    print("config check: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
