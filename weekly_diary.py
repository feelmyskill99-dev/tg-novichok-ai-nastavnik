"""Stage 13 — Weekly Diary.

Воскресенье 19:00 МСК → собираем посты из history.json за последние 7 дней,
просим Claude сделать живой пост-агрегат «Дневник недели» от лица новичка,
показываем владельцу на ревью (✅/✏️/❌). В канал — только после одобрения.

Что МОЖНО:
    Перечислить темы/настроения недели по short_summary, признать чему научился,
    отметить повторяющиеся ошибки новичка, поставить вопрос к следующей неделе.

Что НЕЛЬЗЯ:
    Выдумывать сделки/прибыли/убытки, опираться на цифры рынка вне history,
    публиковать без одобрения владельца.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import random
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Awaitable, Callable, Optional

from anthropic import Anthropic

from core.json_store import load_json, save_json

try:
    from style_guides import compose_style_context as _compose_style
except Exception:
    def _compose_style(*_args, **_kwargs) -> str:
        return ""


log = logging.getLogger("weekly_diary")

MAX_DRAFTS = 60
SHORT_DISCLAIMER = "Не финсовет. Это дневник обучения и AI-разбор."


from core.env_helpers import env_bool as _env_bool


# Этап 2.3: алиас; реальная логика в core/env_helpers.
def _bool(name: str, default: bool) -> bool:
    return _env_bool(name, default=default)


@dataclass(frozen=True)
class WeeklyDiaryConfig:
    enable_weekly_diary: bool = True
    weekly_diary_dry_run: bool = True

    @classmethod
    def from_env(cls) -> "WeeklyDiaryConfig":
        return cls(
            enable_weekly_diary=_bool("ENABLE_WEEKLY_DIARY", True),
            weekly_diary_dry_run=_bool("WEEKLY_DIARY_DRY_RUN", True),
        )


def collect_week_posts(history_path: Path, *, days: int = 7) -> list[dict]:
    """Берём из history.json последние N дней. Возвращаем краткий вид:
    {datetime, post_type, short_summary}. Без final_text — Claude хватит.
    """
    if not history_path.exists():
        return []
    try:
        raw = json.loads(history_path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("history.json повреждён: %s", e)
        return []
    if not isinstance(raw, list):
        return []
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
    out: list[dict] = []
    for d in raw:
        try:
            dt = datetime.fromisoformat(str(d.get("datetime")).replace("Z", "+00:00"))
        except Exception:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt < cutoff:
            continue
        out.append({
            "datetime": d.get("datetime"),
            "post_type": d.get("post_type") or "unknown",
            "short_summary": (d.get("short_summary") or "")[:200],
        })
    return out


def build_system_prompt() -> str:
    style_ctx = _compose_style(["base_channel"])
    return f"""{style_ctx}

Ты — голос новичка из канала «Депозит под надзором ИИ». Воскресный итог недели.

Задача: собрать живой короткий пост «Дневник недели» по уже опубликованным
постам канала. Только то, что было — никаких выдуманных сделок и цифр.

Структура:
1) human_part — 2–4 коротких абзаца от лица новичка: что цеплял рынок,
   какие были эмоции, где удалось не нажать кнопку.
2) hamster_part — одна реплика внутреннего хомяка про неделю (или null).
3) mentor_part — спокойный комментарий AI-наставника: чему неделя научила.
4) lesson — 1–2 предложения, главный урок недели.
5) question — вопрос аудитории на следующую неделю (или null).

Тон: спокойный, человечный, можно с лёгкой самоиронией. Без «я заработал»,
без «мой портфель», без советов «покупайте/шортите».

Верни СТРОГО валидный JSON без markdown-обёртки:
{{
  "post_type": "weekly_diary",
  "title": "Дневник недели — короткий заголовок",
  "human_part": "...",
  "hamster_part": "... или null",
  "mentor_part": "...",
  "lesson": "...",
  "question": "... или null",
  "hashtags": ["#дневник_недели", "#честный_путь"],
  "short_summary": "8–14 слов для памяти"
}}
""".strip()


def ask_claude(
    claude: Anthropic,
    model: str,
    week_posts: list[dict],
    *,
    revise_feedback: Optional[str] = None,
    previous_post_html: Optional[str] = None,
) -> dict:
    system = build_system_prompt()
    user_payload: dict = {
        "week_posts": week_posts,
        "post_count": len(week_posts),
    }
    if revise_feedback:
        user_payload["instruction"] = (
            "Исправь дневник недели по комментарию владельца. Сохрани живой "
            "стиль, не выдумывай событий вне week_posts. Верни тот же JSON."
        )
        user_payload["owner_feedback"] = revise_feedback
        if previous_post_html:
            user_payload["previous_post_html"] = previous_post_html
    resp = claude.messages.create(
        model=model,
        max_tokens=1500,
        system=system,
        messages=[{"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}],
    )
    raw = (resp.content[0].text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        log.error("weekly_diary: Claude вернул не-JSON: %s\n%s", e, raw[:500])
        return {"ok": False, "reason": f"claude invalid JSON: {e}"}
    data.setdefault("post_type", "weekly_diary")
    data.setdefault("title", "Дневник недели")
    data.setdefault("human_part", "")
    data.setdefault("hamster_part", None)
    data.setdefault("mentor_part", "")
    data.setdefault("lesson", "")
    data.setdefault("question", None)
    data.setdefault("hashtags", [])
    data.setdefault("short_summary", "")
    data["ok"] = True
    return data


def _e(s) -> str:
    return html.escape("" if s is None else str(s), quote=False)


def build_html(payload: dict) -> str:
    title = (payload.get("title") or "Дневник недели").strip()
    human = _e(payload.get("human_part", "")).strip()
    hamster = _e(payload.get("hamster_part") or "").strip()
    mentor = _e(payload.get("mentor_part", "")).strip()
    lesson = _e(payload.get("lesson", "")).strip()
    question = _e(payload.get("question") or "").strip()

    parts: list[str] = [f"📅 <b>{_e(title)}</b>", ""]
    if human:
        parts.append(human)
    if hamster:
        parts += ["", "🐹 <b>Внутренний хомяк</b>", hamster]
    if mentor:
        parts += ["", "🤖 <b>AI-наставник</b>", mentor]
    if lesson:
        parts += ["", "📌 <b>Урок недели</b>", lesson]
    if question:
        parts += ["", "💬 " + question]
    parts += ["", f"<i>{_e(SHORT_DISCLAIMER)}</i>"]

    raw_tags = payload.get("hashtags") or []
    tags = [t if str(t).startswith("#") else f"#{t}" for t in raw_tags if t]
    system_tags = ["#дневник_недели", "#честный_путь"]
    if hamster and "#не_будь_хомяком" not in system_tags:
        system_tags.append("#не_будь_хомяком")
    all_tags = list(dict.fromkeys(tags + system_tags))
    parts += ["", " ".join(_e(t) for t in all_tags)]

    text = "\n".join(parts).strip()
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text


@dataclass
class WeeklyDiaryDraft:
    draft_id: str
    created_at: str
    status: str               # pending_review / revised / published / rejected
    week_post_count: int
    claude_json: dict
    post_html: str
    revision_count: int = 0
    owner_feedback: list[str] = field(default_factory=list)
    updated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "WeeklyDiaryDraft":
        allowed = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in allowed})


def _make_draft_id() -> str:
    raw = f"weekly|{datetime.now(tz=timezone.utc).isoformat()}|{random.random()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class WeeklyDiaryStore:
    def __init__(self, path: Path):
        self.path = path

    def _load(self) -> list[dict]:
        return load_json(self.path, default=[], expected_type=list)

    def _save(self, records: list[dict]) -> None:
        save_json(self.path, records[-MAX_DRAFTS:])

    def list_all(self) -> list[WeeklyDiaryDraft]:
        return [WeeklyDiaryDraft.from_dict(d) for d in self._load()]

    def list_pending(self) -> list[WeeklyDiaryDraft]:
        return [d for d in self.list_all() if d.status in ("pending_review", "revised")]

    def get(self, draft_id: str) -> Optional[WeeklyDiaryDraft]:
        for d in self._load():
            if d.get("draft_id") == draft_id:
                return WeeklyDiaryDraft.from_dict(d)
        return None

    def add(self, draft: WeeklyDiaryDraft) -> None:
        records = self._load()
        records.append(draft.to_dict())
        self._save(records)

    def update(self, draft: WeeklyDiaryDraft) -> None:
        records = self._load()
        draft.updated_at = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        for i, d in enumerate(records):
            if d.get("draft_id") == draft.draft_id:
                records[i] = draft.to_dict()
                self._save(records)
                return
        records.append(draft.to_dict())
        self._save(records)


def review_keyboard(draft_id: str) -> dict:
    """Минимум: ✅ опубликовать / ❌ отклонить.
    Edit-flow для еженедельного поста избыточен — если не нравится,
    отклоняешь и перезапускаешь `python bot.py --weekly-now`."""
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Опубликовать", "callback_data": f"weekly_publish:{draft_id}"},
                {"text": "❌ Отклонить",   "callback_data": f"weekly_reject:{draft_id}"},
            ],
        ]
    }


PreviewSendFn = Callable[[str, dict], Awaitable[None]]
SendFn = Callable[[str, str], Awaitable[None]]


async def run_weekly_diary_now(
    *,
    config: WeeklyDiaryConfig,
    claude: Anthropic,
    claude_model: str,
    history_path: Path,
    drafts_path: Path,
    owner_chat_id: str,
    channel_id: str,
    send_fn: SendFn,
    preview_send_fn: PreviewSendFn,
) -> dict:
    if not config.enable_weekly_diary:
        return {"ok": False, "reason": "ENABLE_WEEKLY_DIARY=false"}

    week_posts = collect_week_posts(history_path, days=7)
    if not week_posts:
        return {"ok": False, "reason": "за последние 7 дней постов нет — пропускаем"}
    log.info("weekly_diary: собираем по %d постам недели", len(week_posts))

    payload = ask_claude(claude, claude_model, week_posts)
    if not payload.get("ok"):
        return {"ok": False, "reason": payload.get("reason", "claude failed")}

    post_html = build_html(payload)
    draft = WeeklyDiaryDraft(
        draft_id=_make_draft_id(),
        created_at=datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        status="pending_review",
        week_post_count=len(week_posts),
        claude_json=payload,
        post_html=post_html,
    )
    store = WeeklyDiaryStore(drafts_path)
    store.add(draft)

    if not owner_chat_id:
        return {"ok": False, "reason": "OWNER_CHAT_ID не задан, ревью невозможно"}
    preview = _wrap_preview(post_html, draft.draft_id, len(week_posts))
    await preview_send_fn(preview, review_keyboard(draft.draft_id))
    return {"ok": True, "decision": "preview_sent", "draft_id": draft.draft_id,
            "week_post_count": len(week_posts)}


def _wrap_preview(post_html: str, draft_id: str, week_post_count: int,
                  *, header: str = "📅 <b>Weekly diary — нужен ревью</b>") -> str:
    head = (
        f"{header}\n"
        f"draft_id: <code>{html.escape(draft_id, quote=False)}</code> | "
        f"постов за неделю: {week_post_count}\n"
        "──────────────"
    )
    return head + "\n\n" + post_html
