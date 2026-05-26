"""Делегировать задачу DeepSeek API и сохранить результат в outputs/deepseek/.

Использование:
    python scripts/delegate_to_deepseek.py \
        --brief docs/briefs/<task>.md \
        --context trading/safety.py trading/config.py tests/test_external.py \
        --out tests/test_trading_safety.py \
        [--model deepseek-reasoner|deepseek-chat]

Что делает:
1. Читает DEEPSEEK_API_KEY из .env.
2. Собирает messages: system (роль) + user (брифинг + контекст-файлы).
3. Дёргает https://api.deepseek.com/chat/completions.
4. Извлекает код из ответа (markdown ```python ... ```).
5. Сохраняет два файла:
   - outputs/deepseek/<timestamp>/raw.json   — полный ответ API
   - outputs/deepseek/<timestamp>/extracted.py — извлечённый код (если найден)
6. Если --out задан и код извлечён — копирует extracted.py в --out.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-reasoner"
TIMEOUT_S = 300.0

SYSTEM_PROMPT = """\
Ты опытный Python-инженер, работаешь в рамках проекта deposit_ai.

Правила:
1. TDD: тесты ДОЛЖНЫ запускаться и проходить против предоставленного кода.
2. Surgical changes: ничего не добавляй сверх того, что запрошено в брифинге.
3. Не пиши docstring'и/комментарии длиннее одной строки, если они не объясняют WHY.
4. Не используй эмодзи в коде/комментариях.
5. Если в брифинге сказано «использовать pytest» — используй pytest fixtures (tmp_path, monkeypatch), без unittest.
6. Импорты — только из стандартной библиотеки или модулей, упомянутых в брифинге/контексте.
7. Не выдумывай несуществующие функции/классы. Если что-то отсутствует в контексте — задай вопрос в начале ответа, не пиши код.
8. Финальный ответ: один Python-блок ```python ... ```. Никакого пояснительного текста после кода.
"""


def _read_files(paths: list[Path]) -> str:
    parts: list[str] = []
    for p in paths:
        abs_p = p if p.is_absolute() else (ROOT / p)
        try:
            content = abs_p.read_text(encoding="utf-8")
        except Exception as e:
            print(f"WARN: cannot read {abs_p}: {e}", file=sys.stderr)
            continue
        try:
            rel = abs_p.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            rel = abs_p.as_posix()
        parts.append(f"--- FILE: {rel} ---\n{content}\n")
    return "\n".join(parts)


def _build_user_message(brief: str, context: str) -> str:
    return f"""\
# Брифинг задачи

{brief}

# Контекстные файлы

{context}

# Что вернуть

Один Python-блок ```python ... ``` — готовый к сохранению файл. Без пояснений.
"""


def _extract_python_block(text: str) -> str | None:
    m = re.search(r"```python\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        return m.group(1)
    m = re.search(r"```\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        return m.group(1)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--brief", type=Path, required=True, help="путь к .md с брифингом задачи")
    parser.add_argument("--context", type=Path, nargs="*", default=[], help="файлы контекста")
    parser.add_argument("--out", type=Path, default=None, help="куда положить извлечённый код")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"модель ({DEFAULT_MODEL})")
    parser.add_argument("--max-tokens", type=int, default=8000)
    args = parser.parse_args()

    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        print("ERROR: DEEPSEEK_API_KEY не задан в .env", file=sys.stderr)
        return 1

    if not args.brief.exists():
        print(f"ERROR: brief file {args.brief} not found", file=sys.stderr)
        return 1

    brief_text = args.brief.read_text(encoding="utf-8")
    context_text = _read_files(args.context) if args.context else "(no context)"

    payload = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_message(brief_text, context_text)},
        ],
        "max_tokens": args.max_tokens,
        "stream": False,
    }

    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = ROOT / "outputs" / "deepseek" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[POST] POST {DEEPSEEK_URL} model={args.model} timeout={TIMEOUT_S}s")
    try:
        r = httpx.post(
            DEEPSEEK_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=TIMEOUT_S,
        )
    except Exception as e:
        print(f"ERROR: HTTP request failed: {e}", file=sys.stderr)
        return 1

    raw_path = out_dir / "raw.json"
    raw_path.write_text(
        json.dumps({"status_code": r.status_code, "body": _safe_json(r)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if r.status_code != 200:
        print(f"ERROR: status {r.status_code}. raw [POST] {raw_path}", file=sys.stderr)
        print(r.text[:500], file=sys.stderr)
        return 1

    data = r.json()
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    content = msg.get("content") or ""

    usage = data.get("usage") or {}
    print(f"[OK] tokens prompt={usage.get('prompt_tokens')} completion={usage.get('completion_tokens')} total={usage.get('total_tokens')}")
    print(f"[OK] raw [POST] {raw_path}")

    code = _extract_python_block(content)
    if not code:
        print("WARN: не нашёл ```python ...``` блок в ответе. См. raw.json", file=sys.stderr)
        return 2

    extracted_path = out_dir / "extracted.py"
    extracted_path.write_text(code, encoding="utf-8")
    print(f"[OK] extracted [POST] {extracted_path}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(code, encoding="utf-8")
        print(f"[OK] saved [POST] {args.out}")

    return 0


def _safe_json(r: httpx.Response) -> object:
    try:
        return r.json()
    except Exception:
        return {"text": r.text}


if __name__ == "__main__":
    sys.exit(main())
