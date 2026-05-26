"""Stage 10 — Author Voice Layer.

Генерирует короткие личные заметки от лица автора-новичка, проходящие через
владельческий ревью (как новости в Stage 6b). Цель — добавить ощущение живого
человека, который учится трейдингу, а не «AI-ленты на автопилоте».

Что МОЖНО:
    Мысли, сомнения, FOMO, желание войти, страх пропустить, усталость,
    осторожность, признание непонимания, маленькие победы дисциплины.

Что НЕЛЬЗЯ без user_action:
    Реальные сделки, фейковые убытки/прибыли, фейковая личная жизнь.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import random
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Optional

from anthropic import Anthropic

from core.json_store import load_json, save_json

try:
    from style_guides import compose_style_context as _compose_style
except Exception:   # pragma: no cover
    def _compose_style(*_args, **_kwargs) -> str:
        return ""


log = logging.getLogger("author_notes")

MAX_DRAFTS = 200
SHORT_DISCLAIMER = "Не финсовет. Это дневник обучения и AI-разбор."


# =============================================================================
# CONFIG
# =============================================================================

from core.env_helpers import env_bool as _env_bool, env_int as _env_int


# Этап 2.3: алиасы; реальная логика в core/env_helpers.
def _bool(name: str, default: bool) -> bool:
    return _env_bool(name, default=default)


def _int(name: str, default: int) -> int:
    return _env_int(name, default=default)


@dataclass(frozen=True)
class AuthorNoteConfig:
    enable_author_notes: bool = True
    author_notes_per_week: int = 2
    author_note_dry_run: bool = True
    author_note_review_required: bool = True

    @classmethod
    def from_env(cls) -> "AuthorNoteConfig":
        return cls(
            enable_author_notes=_bool("ENABLE_AUTHOR_NOTES", True),
            author_notes_per_week=_int("AUTHOR_NOTES_PER_WEEK", 2),
            author_note_dry_run=_bool("AUTHOR_NOTE_DRY_RUN", True),
            author_note_review_required=_bool("AUTHOR_NOTE_REVIEW_REQUIRED", True),
        )


# =============================================================================
# RUBRICS
# =============================================================================

@dataclass(frozen=True)
class Rubric:
    key: str
    emoji: str
    title: str
    tags: tuple[str, ...]
    hint: str  # короткая подсказка Claude, чтобы держать тон рубрики


RUBRICS: dict[str, Rubric] = {
    "what_i_understood": Rubric(
        key="what_i_understood",
        emoji="🧠",
        title="Что я понял сегодня",
        tags=("#что_я_понял", "#честный_путь"),
        hint="инсайт, который пришёл новичку из наблюдения за собой или рынком; короткий, без пафоса",
    ),
    "embarrassing_thought": Rubric(
        key="embarrassing_thought",
        emoji="😬",
        title="Стыдная мысль новичка",
        tags=("#ошибки_новичка", "#честный_путь"),
        hint="признаётся в плохом импульсе, который чуть не превратился в действие; AI-наставник аккуратно ловит за руку",
    ),
    "bad_idea_of_day": Rubric(
        key="bad_idea_of_day",
        emoji="💀",
        title="Плохая идея дня",
        tags=("#ошибки_новичка", "#честный_путь"),
        hint="самокритично разбирает идею, которая казалась умной 5 минут назад",
    ),
    "small_victory": Rubric(
        key="small_victory",
        emoji="✅",
        title="Маленькая победа",
        tags=("#дисциплина", "#честный_путь"),
        hint="победа — это что-то НЕ сделанное (не нажал, не залез без стопа); без хвастовства",
    ),
    "missed_move": Rubric(
        key="missed_move",
        emoji="🐢",
        title="Пропустил движение",
        tags=("#FOMO", "#честный_путь"),
        hint="как переживается момент «рынок ушёл без меня», без нытья и без «надо было войти»",
    ),
    "almost_believed": Rubric(
        key="almost_believed",
        emoji="🤔",
        title="Чему я почти поверил",
        tags=("#скам_радар", "#не_будь_хомяком"),
        hint="скептический разбор красивой обёртки (AI-бот, инсайдер, «гарантированный доход») — почти повёлся",
    ),
    "hamster_dialog": Rubric(
        key="hamster_dialog",
        emoji="🐹",
        title="Диалог с хомяком",
        tags=("#не_будь_хомяком", "#честный_путь"),
        hint="прямой формат «хомяк говорит → AI-наставник отвечает», без действий, только реплики",
    ),
}


def random_rubric() -> Rubric:
    return random.choice(list(RUBRICS.values()))


def get_rubric(key: str) -> Rubric:
    return RUBRICS.get(key) or random_rubric()


# =============================================================================
# CLAUDE PROMPT
# =============================================================================

BRAND = "Депозит под надзором ИИ"


def build_system_prompt(rubric: Rubric) -> str:
    return _build_core_author_prompt(rubric) + (_compose_style("base", "author_note") or "")


def _build_core_author_prompt(rubric: Rubric) -> str:
    return f"""
Ты пишешь author_note для Telegram-канала «{BRAND}» — короткую ЛИЧНУЮ заметку
от лица автора-новичка, который учится трейдингу.

ТЕКУЩАЯ РУБРИКА: {rubric.title}
Подсказка по тону: {rubric.hint}

ЦЕЛЬ Stage 10:
Добавить ощущение живого человека рядом с AI-наставником. Канал — НЕ автомат
по новостям, а дневник новичка с честными мыслями.

ЧТО МОЖНО (живые мысли, не события):
- сомнение, FOMO, желание войти, страх пропустить, усталость от графика
- осторожность, радость от дисциплины, признание непонимания
- наблюдение за собой: «поймал себя на мысли...», «мне пока сложно...»
- «кажется, я начинаю понимать...», «самое трудное — не нажимать кнопку»

ЧЕГО НЕЛЬЗЯ (без user_action):
- «я открыл сделку», «я купил», «я продал», «меня ликвиднуло»
- «я заработал X», «я потерял X», «я ночью торговал», «я вложил»
- любые конкретные цифры PnL и реальные действия
- драматизация, исповедь, «я профессионал»
- торговые советы, обещания прибыли, сигналы
- штампы «Сегодня рассмотрим», «Важно понимать», «В данной заметке»

ДЛИНА: 700–1200 символов всего поста. Абзац 1–3 строки. Telegram читают с телефона.

ТОН:
- честно, коротко, по-человечески
- немного самоиронии
- лёгкий сарказм AI-наставника, без токсичности
- обязательно с маленьким уроком в конце

СТРУКТУРА (Stage 10):
1) human_part — живая мысль автора (3–6 коротких фраз, начни с эмоции/наблюдения)
2) hamster_part — реплика «внутреннего хомяка» в кавычках; null если рубрика не зовёт
   (например, в «Маленькая победа» хомяк часто молчит — он проиграл)
3) mentor_part — AI-наставник: спокойно, строго, простыми словами; 2–4 короткие фразы
4) lesson — короткий урок 1–2 предложения; без призыва к действию
5) question — опционально, 1 короткий вопрос аудитории

JSON-ПОЛЯ:
- mood: fomo / doubt / discipline / fear / curiosity / frustration / patience
- trigger: market / news / trade / no_trade / learning / scam
- title: 2–4 слова, под рубрику; можно повторить заголовок рубрики

Верни СТРОГО валидный JSON без markdown-обёртки и без комментариев:
{{
  "post_type": "author_note",
  "rubric": "{rubric.key}",
  "title": "...",
  "mood": "fomo|doubt|discipline|fear|curiosity|frustration|patience",
  "trigger": "market|news|trade|no_trade|learning|scam",
  "human_part": "...",
  "hamster_part": "... или null",
  "mentor_part": "...",
  "lesson": "...",
  "question": "... или null",
  "hashtags": ["#личная_заметка", "#честный_путь"],
  "short_summary": "8–14 слов для памяти"
}}
""".strip()


def ask_claude(
    claude: Anthropic,
    model: str,
    rubric: Rubric,
    *,
    context: Optional[dict] = None,
    revise_feedback: Optional[str] = None,
    previous_post_html: Optional[str] = None,
) -> dict:
    """Один запрос к Claude. context — опциональный market/news/trade snapshot,
    revise_feedback — текст owner'а (если используется в edit-флоу).
    """
    system = build_system_prompt(rubric)
    user_payload: dict = {
        "rubric": rubric.key,
        "rubric_title": rubric.title,
        "rubric_hint": rubric.hint,
        "context": context or {},
    }
    if revise_feedback:
        user_payload["instruction"] = (
            "Исправь заметку по комментарию владельца. Сохрани личный стиль, "
            "не выдумывай реальных событий и сделок. Верни тот же JSON-формат."
        )
        user_payload["owner_feedback"] = revise_feedback
        if previous_post_html:
            user_payload["previous_post_html"] = previous_post_html
    resp = claude.messages.create(
        model=model,
        max_tokens=1200,
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
        log.error("author_note: Claude вернул не-JSON: %s\n%s", e, raw[:500])
        return {"ok": False, "reason": f"claude invalid JSON: {e}"}
    data.setdefault("post_type", "author_note")
    data.setdefault("rubric", rubric.key)
    data.setdefault("title", rubric.title)
    data.setdefault("mood", "doubt")
    data.setdefault("trigger", "learning")
    data.setdefault("human_part", "")
    data.setdefault("hamster_part", None)
    data.setdefault("mentor_part", "")
    data.setdefault("lesson", "")
    data.setdefault("question", None)
    data.setdefault("hashtags", [])
    data.setdefault("short_summary", "")
    data["ok"] = True
    return data


# =============================================================================
# HTML BUILDER
# =============================================================================

def _e(s) -> str:
    return html.escape("" if s is None else str(s), quote=False)


def build_html(payload: dict) -> str:
    rubric_key = payload.get("rubric") or "what_i_understood"
    rubric = get_rubric(rubric_key)
    title = (payload.get("title") or rubric.title).strip()

    human = _e(payload.get("human_part", "")).strip()
    hamster = _e(payload.get("hamster_part") or "").strip()
    mentor = _e(payload.get("mentor_part", "")).strip()
    lesson = _e(payload.get("lesson", "")).strip()
    question = _e(payload.get("question") or "").strip()

    parts: list[str] = []
    parts.append(f"{rubric.emoji} <b>{_e(title)}</b>")
    parts.append("")

    if human:
        parts.append(human)

    if hamster:
        parts.append("")
        parts.append("🐹 <b>Внутренний хомяк</b>")
        parts.append(hamster)

    if mentor:
        parts.append("")
        parts.append("🤖 <b>AI-наставник</b>")
        parts.append(mentor)

    if lesson:
        parts.append("")
        parts.append("📌 <b>Урок</b>")
        parts.append(lesson)

    if question:
        parts.append("")
        parts.append("💬 " + question)

    parts.append("")
    parts.append(f"<i>{_e(SHORT_DISCLAIMER)}</i>")

    raw_tags = payload.get("hashtags") or []
    tags = [t if str(t).startswith("#") else f"#{t}" for t in raw_tags if t]
    system_tags = ["#личная_заметка"]
    system_tags.extend(rubric.tags)
    if hamster and "#не_будь_хомяком" not in system_tags:
        system_tags.append("#не_будь_хомяком")
    all_tags = list(dict.fromkeys(tags + system_tags))
    parts.append("")
    parts.append(" ".join(_e(t) for t in all_tags))

    text = "\n".join(parts).strip()
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text


# =============================================================================
# DRAFTS STORE
# =============================================================================

@dataclass
class AuthorNoteDraft:
    draft_id: str
    created_at: str
    status: str               # pending_review / revised / published / rejected
    rubric: str
    claude_json: dict
    post_html: str
    revision_count: int = 0
    owner_feedback: list[str] = field(default_factory=list)
    updated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AuthorNoteDraft":
        allowed = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in allowed})


def _make_draft_id(rubric_key: str) -> str:
    raw = f"author|{rubric_key}|{datetime.now(tz=timezone.utc).isoformat()}|{random.random()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class AuthorNoteStore:
    def __init__(self, path: Path):
        self.path = path

    def _load(self) -> list[dict]:
        return load_json(self.path, default=[], expected_type=list)

    def _save(self, records: list[dict]) -> None:
        save_json(self.path, records[-MAX_DRAFTS:])

    def list_all(self) -> list[AuthorNoteDraft]:
        return [AuthorNoteDraft.from_dict(d) for d in self._load()]

    def list_pending(self) -> list[AuthorNoteDraft]:
        return [d for d in self.list_all() if d.status in ("pending_review", "revised")]

    def get(self, draft_id: str) -> Optional[AuthorNoteDraft]:
        for d in self._load():
            if d.get("draft_id") == draft_id:
                return AuthorNoteDraft.from_dict(d)
        return None

    def add(self, draft: AuthorNoteDraft) -> None:
        records = self._load()
        records.append(draft.to_dict())
        self._save(records)

    def update(self, draft: AuthorNoteDraft) -> None:
        records = self._load()
        draft.updated_at = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        for i, d in enumerate(records):
            if d.get("draft_id") == draft.draft_id:
                records[i] = draft.to_dict()
                self._save(records)
                return
        records.append(draft.to_dict())
        self._save(records)


# =============================================================================
# REVIEW KEYBOARD
# =============================================================================

def review_keyboard(draft_id: str) -> dict:
    """Stage 10: ровно три кнопки — без regenerate (см. ТЗ §9)."""
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Опубликовать", "callback_data": f"author_publish:{draft_id}"},
                {"text": "✏️ Исправить",   "callback_data": f"author_edit:{draft_id}"},
            ],
            [
                {"text": "❌ Отклонить",   "callback_data": f"author_reject:{draft_id}"},
            ],
        ]
    }


# =============================================================================
# RUNNER
# =============================================================================

PreviewSendFn = Callable[[str, dict], Awaitable[None]]
SendFn = Callable[[str, str], Awaitable[None]]


async def run_author_note_now(
    *,
    config: AuthorNoteConfig,
    claude: Anthropic,
    claude_model: str,
    drafts_path: Path,
    owner_chat_id: str,
    channel_id: str,
    send_fn: SendFn,
    preview_send_fn: PreviewSendFn,
    rubric_key: Optional[str] = None,
    context: Optional[dict] = None,
) -> dict:
    """Полный цикл: выбрать рубрику → ask Claude → build_html →
    либо preview владельцу (review_required), либо публикация в канал
    (если review_required=false и dry_run=false).
    """
    if not config.enable_author_notes:
        return {"ok": False, "reason": "ENABLE_AUTHOR_NOTES=false"}

    rubric = get_rubric(rubric_key) if rubric_key else random_rubric()
    log.info("author_note: rubric=%s", rubric.key)

    payload = ask_claude(claude, claude_model, rubric, context=context)
    if not payload.get("ok"):
        return {"ok": False, "reason": payload.get("reason", "claude failed")}

    post_html = build_html(payload)
    draft = AuthorNoteDraft(
        draft_id=_make_draft_id(rubric.key),
        created_at=datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        status="pending_review",
        rubric=rubric.key,
        claude_json=payload,
        post_html=post_html,
        revision_count=0,
        owner_feedback=[],
    )
    store = AuthorNoteStore(drafts_path)
    store.add(draft)

    if config.author_note_review_required:
        if not owner_chat_id:
            return {"ok": False, "reason": "OWNER_CHAT_ID не задан, ревью невозможно"}
        preview = _wrap_preview(post_html, draft.draft_id, rubric)
        await preview_send_fn(preview, review_keyboard(draft.draft_id))
        return {"ok": True, "decision": "preview_sent", "draft_id": draft.draft_id, "rubric": rubric.key}

    # Если ревью не требуется — публикация:
    if config.author_note_dry_run or not channel_id:
        if owner_chat_id:
            preview = _wrap_preview(post_html, draft.draft_id, rubric, header="🧪 author_note (DRY_RUN)")
            await preview_send_fn(preview, review_keyboard(draft.draft_id))
        return {"ok": True, "decision": "dry_run", "draft_id": draft.draft_id}

    await send_fn(channel_id, post_html)
    draft.status = "published"
    store.update(draft)
    return {"ok": True, "decision": "published", "draft_id": draft.draft_id}


def _wrap_preview(post_html: str, draft_id: str, rubric: Rubric, *, header: str = "📝 <b>Author note — нужен ревью</b>") -> str:
    head = (
        f"{header}\n"
        f"draft_id: <code>{html.escape(draft_id, quote=False)}</code> | "
        f"рубрика: {html.escape(rubric.title, quote=False)}\n"
        "──────────────"
    )
    return head + "\n\n" + post_html
