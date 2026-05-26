"""Ad-hoc DeepSeek consult about deposit_ai branding. Run-once, not part of pipeline."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

SYSTEM = (
    "Ты со-владелец / арт-директор русскоязычного Telegram-канала о трейдинге. "
    "Канал — «Депозит под надзором ИИ»: дневник новичка + строгий AI-наставник + комичный «внутренний хомяк». "
    "Тон постов уже хороший (живой, самоироничный, без сигналов). "
    "Проблема — канал выглядит «как AI-свалка»: слабые аватар/описание, генеричный визуал, посты похожи. "
    "Дай конкретные рекомендации, как партнёр в команде, а не как чат-бот."
)

USER = """Контекст:
- Канал @ai_deposit_diary, ~маленькая аудитория, цель — доверие через честный процесс.
- Текущий аватар: парень за столом обхватил голову + голубой полупрозрачный гуманоид AI + свечной график на фоне. Дарк-сайфер, синие неон-тона. Типичный AI-арт, нет уникального знака.
- Текущее описание (255 символов): "Честный дневник трейдера-новичка под надзором ИИ. Маленький депозит, ошибки без прикрас, риск-менеджмент, новости и внутренний хомяк. Без сигналов, гуру и обещаний прибыли."
- Контент-микс: 40% market chart / 20% education / 15% news / 15% author note / 10% trade diary.
- Уже работает: DALL-E пайплайн (openai gpt-image), бот может ставить аватар/title/description через setChatPhoto.

Вопросы (ответь нумерованно, коротко, в стиле «делай так — потому что»):

1. ТРИ направления визуального стиля аватара для такого канала. Каждое — один абзац: какой образ, какая палитра, какой фокус-объект. Никаких «варианты А/Б/В кратко» — нужны полностью разные подходы, чтобы выбирать осознанно.

2. Новое описание канала (≤255 символов, plain text + 1-2 эмодзи максимум). Должно за 3 секунды объяснять формат и зацепить. Дай 2 версии: одна с упором на «дневник без прикрас», вторая с упором на «AI-надзор / риск-менеджмент».

3. ТОП-3 паттерна, из-за которых посты выглядят похожими, даже когда тон живой. Что чинить в шаблонах (HTML-структура, эмодзи-сноски, концовки).

4. Что критично сделать в первую очередь, если у нас 1 неделя на ребрендинг и нельзя ломать прод-публикации? Назови порядок шагов 1→2→3→4.

Отвечай как партнёр, а не как генератор контента — мнение, не список опций. Никаких «вы могли бы рассмотреть»."""

api_key = os.getenv("DEEPSEEK_API_KEY")
if not api_key:
    print("DEEPSEEK_API_KEY missing", file=sys.stderr)
    sys.exit(1)

resp = httpx.post(
    "https://api.deepseek.com/chat/completions",
    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    json={
        "model": "deepseek-reasoner",
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": USER},
        ],
        "max_tokens": 4000,
        "temperature": 0.7,
    },
    timeout=300.0,
)
resp.raise_for_status()
data = resp.json()
content = data["choices"][0]["message"]["content"]

out = ROOT / "outputs" / "deepseek" / "_advisor_branding.md"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(content, encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")
print(content)
print(f"\n\n--- saved: {out}")
