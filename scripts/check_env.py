"""Проверка .env: только имена отсутствующих переменных, без значений."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=ROOT / ".env")


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


def main() -> int:
    missing = [name for name in REQUIRED if not (os.getenv(name) or "").strip()]
    if missing:
        print("MISSING REQUIRED:")
        for n in missing:
            print(f"  - {n}")
    else:
        print("REQUIRED: all present")

    print()
    print("FLAGS:")
    flag_problems = []
    for name, expected in EXPECTED_FLAGS.items():
        actual = (os.getenv(name) or "").strip().lower()
        ok = actual == expected
        mark = "OK" if ok else "WRONG"
        print(f"  {name}={actual or '<empty>'}  expected={expected}  [{mark}]")
        if not ok:
            flag_problems.append(name)

    print()
    if missing or flag_problems:
        return 1
    print("config check: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
