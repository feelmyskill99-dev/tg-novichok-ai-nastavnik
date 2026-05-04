"""Stage 6b — News review / approval drafts.

Каждый сгенерированный новостной пост (когда канал-публикация заблокирована флагами)
сохраняется как черновик в news_drafts.json и уходит владельцу как превью с кнопками.

draft.status:
    pending_review — ждёт решения владельца (по умолчанию)
    revised        — владелец дал feedback или попросил перегенерировать; ждёт решения снова
    approved       — владелец нажал ✅ Опубликовать, но публикация заблокирована флагами
    published      — успешно отправлено в канал
    rejected       — владелец нажал ❌ Отклонить
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from anthropic import Anthropic

from .analyzer import build_system_prompt
from .config import NewsConfig
from .models import NewsItem


log = logging.getLogger("news.drafts")

MAX_DRAFTS = 200


@dataclass
class NewsDraft:
    draft_id: str
    created_at: str
    status: str
    source_news: dict
    post_html: str
    claude_json: dict
    revision_count: int = 0
    owner_feedback: list[str] = field(default_factory=list)
    updated_at: str = ""
    # Stage 12b — генерация картинок
    image_path: str = ""                 # абсолютный путь к сохранённой картинке (или "")
    guard_reasons: list[str] = field(default_factory=list)  # причины блокировки автопубликации
    # Stage 12e — source image strategy + audit
    image_origin: str = "none"           # source_preview | generated_ai | manual_upload | none
    image_source_url: str = ""           # URL og:image/twitter:image, если origin=source_preview
    image_credit: str = ""               # имя источника (Cointelegraph / Decrypt / ...)
    image_prompt: str = ""               # для generated_ai — финальный prompt OpenAI
    image_model: str = ""                # gpt-image-2 / gpt-image-1
    image_created_at: str = ""           # ISO8601, когда image_path был создан

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "NewsDraft":
        allowed = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in allowed})


def _make_draft_id(item: NewsItem) -> str:
    raw = f"{item.id}|{datetime.now(tz=timezone.utc).isoformat()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class DraftStore:
    def __init__(self, path: Path):
        self.path = path

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, list) else []
        except Exception as e:
            log.warning("news_drafts.json повреждён: %s", e)
            return []

    def _save(self, records: list[dict]) -> None:
        records = records[-MAX_DRAFTS:]
        self.path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_all(self) -> list[NewsDraft]:
        return [NewsDraft.from_dict(d) for d in self._load()]

    def list_pending(self) -> list[NewsDraft]:
        return [d for d in self.list_all() if d.status in ("pending_review", "revised")]

    def get(self, draft_id: str) -> Optional[NewsDraft]:
        for d in self._load():
            if d.get("draft_id") == draft_id:
                return NewsDraft.from_dict(d)
        return None

    def add(self, draft: NewsDraft) -> None:
        records = self._load()
        records.append(draft.to_dict())
        self._save(records)

    def update(self, draft: NewsDraft) -> None:
        records = self._load()
        draft.updated_at = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        for i, d in enumerate(records):
            if d.get("draft_id") == draft.draft_id:
                records[i] = draft.to_dict()
                self._save(records)
                return
        records.append(draft.to_dict())
        self._save(records)


def get_recent_published_phrases(store: "DraftStore", limit: int = 8) -> list[str]:
    """Stage 12f/12g anti-repetition: список «уже использованных» фраз и заголовков
    из недавних published И pending_review драфтов.

    Возвращает плоский список строк, который потом передаётся Claude как
    `previous_phrases_to_avoid` (через user_payload). Включаем pending_review,
    чтобы Claude не пропускал кросс-источниковые дубли (тот же сюжет другим
    выпуском), пока первая версия ещё ждёт ревью владельца.
    """
    out: list[str] = []
    try:
        all_drafts = store.list_all()
    except Exception as e:
        log.warning("get_recent_published_phrases: list_all failed: %s", e)
        return out
    relevant = [d for d in all_drafts if d.status in ("published", "pending_review")]
    if not relevant:
        return out
    relevant = relevant[-limit:]
    for d in relevant:
        cj = d.claude_json or {}
        title = (cj.get("specific_title") or "").strip()
        prefix = "уже на ревью" if d.status == "pending_review" else "уже опубликовано"
        if title:
            out.append(f"• [{prefix}] title: {title[:160]}")
        # Источниковый title — иногда отличается от specific_title (Claude-перевод).
        src_title = ""
        try:
            src_title = (d.source_news.get("title") if isinstance(d.source_news, dict) else "") or ""
        except Exception:
            src_title = ""
        if src_title and src_title != title:
            out.append(f"• [{prefix}] source title: {src_title[:160]}")
        if d.status == "published":
            h = (cj.get("human_part") or "").strip()
            if h:
                out.append(f"• мысль новичка: {h[:200]}")
            m = (cj.get("mentor_part") or "").strip()
            if m:
                out.append(f"• AI-наставник: {m[:200]}")
    return out


def create_draft_from(
    claude_payload: dict,
    item: NewsItem,
    post_html: str,
    *,
    image_path: str = "",
    guard_reasons: Optional[list[str]] = None,
    image_origin: str = "none",
    image_source_url: str = "",
    image_credit: str = "",
    image_prompt: str = "",
    image_model: str = "",
    image_created_at: str = "",
) -> NewsDraft:
    return NewsDraft(
        draft_id=_make_draft_id(item),
        created_at=datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        status="pending_review",
        source_news={
            "id": item.id,
            "title": item.title,
            "url": item.url,
            "source": item.source,
            "published_at": item.published_at,
            "sector": item.sector,
            "impact_score": item.impact_score,
            "category": item.category,
            "assets": item.assets,
            "summary": item.summary,
        },
        post_html=post_html,
        claude_json=claude_payload,
        revision_count=0,
        owner_feedback=[],
        image_path=image_path or "",
        guard_reasons=list(guard_reasons or []),
        image_origin=image_origin or ("source_preview" if image_path and image_source_url else
                                      "generated_ai" if image_path and image_prompt else
                                      "manual_upload" if image_path else "none"),
        image_source_url=image_source_url or "",
        image_credit=image_credit or (item.source or ""),
        image_prompt=image_prompt or "",
        image_model=image_model or "",
        image_created_at=image_created_at or "",
    )


def review_keyboard(draft_id: str) -> dict:
    """dict-описание InlineKeyboardMarkup. bot.py обернёт через _keyboard_from_dict.

    Stage 12e — два отдельных image-action:
    - 🖼 Сгенерировать AI-картинку (OpenAI, single explicit consent)
    - 🔄 Обновить превью источника (og:image/twitter:image, без OpenAI)
    """
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Опубликовать", "callback_data": f"news_publish:{draft_id}"},
                {"text": "✏️ Исправить",   "callback_data": f"news_edit:{draft_id}"},
            ],
            [
                {"text": "🔁 Перегенерировать текст", "callback_data": f"news_regenerate:{draft_id}"},
                {"text": "❌ Отклонить",              "callback_data": f"news_reject:{draft_id}"},
            ],
            [
                {"text": "🖼 Сгенерировать AI-картинку",   "callback_data": f"news_generate_ai_image:{draft_id}"},
            ],
            [
                {"text": "🔄 Обновить превью источника",   "callback_data": f"news_refresh_source_image:{draft_id}"},
            ],
        ]
    }


# ----- Claude regenerate / revise -----------------------------------------

REGENERATE_INSTRUCTION = (
    "Перегенерируй пост в стиле канала, сохрани факты, не добавляй новых источников. "
    "Не меняй URL и не выдумывай цифр. Структура полей JSON та же. "
    "Верни валидный JSON без markdown-обёртки."
)

REVISE_INSTRUCTION = (
    "Исправь пост по комментарию владельца. Сохрани факты, не добавляй новых "
    "источников и цифр. Не давай сигналов и обещаний прибыли. "
    "Верни валидный JSON без markdown-обёртки."
)


def _source_news_for_claude(draft: NewsDraft) -> dict:
    sn = draft.source_news
    return {
        "id": sn.get("id"),
        "title": sn.get("title"),
        "url": sn.get("url"),
        "source": sn.get("source"),
        "published_at": sn.get("published_at"),
        "summary": (sn.get("summary") or "")[:400],
        "assets": sn.get("assets") or [],
        "category": sn.get("category"),
        "sector": sn.get("sector"),
        "impact_score": sn.get("impact_score") or 0,
    }


def regenerate_payload(
    draft: NewsDraft,
    cfg: NewsConfig,
    claude: Anthropic,
    model: str,
) -> dict:
    """Просим Claude переписать пост по тем же фактам, но иначе."""
    system = build_system_prompt(cfg)
    user_payload = {
        "news_batch": [_source_news_for_claude(draft)],
        "min_impact_score": cfg.news_min_impact_score,
        "humor_level": cfg.news_humor_level,
        "sarcasm_level": cfg.news_sarcasm_level,
        "instruction": REGENERATE_INSTRUCTION,
        "previous_post_html": draft.post_html,
        "revision_count": draft.revision_count,
        "previous_phrases_to_avoid": [
            f"• мысль новичка: {(draft.claude_json or {}).get('human_part','')[:200]}",
            f"• AI-наставник: {(draft.claude_json or {}).get('mentor_part','')[:200]}",
        ],
    }
    return _ask_claude(claude, model, system, user_payload)


def revise_payload(
    draft: NewsDraft,
    feedback: str,
    cfg: NewsConfig,
    claude: Anthropic,
    model: str,
) -> dict:
    """Просим Claude переписать пост с учётом feedback владельца."""
    system = build_system_prompt(cfg)
    user_payload = {
        "news_batch": [_source_news_for_claude(draft)],
        "min_impact_score": cfg.news_min_impact_score,
        "humor_level": cfg.news_humor_level,
        "sarcasm_level": cfg.news_sarcasm_level,
        "instruction": REVISE_INSTRUCTION,
        "owner_feedback": feedback,
        "previous_post_html": draft.post_html,
        "revision_count": draft.revision_count,
        "previous_phrases_to_avoid": [
            f"• мысль новичка: {(draft.claude_json or {}).get('human_part','')[:200]}",
            f"• AI-наставник: {(draft.claude_json or {}).get('mentor_part','')[:200]}",
        ],
    }
    return _ask_claude(claude, model, system, user_payload)


def _ask_claude(claude: Anthropic, model: str, system: str, user_payload: dict) -> dict:
    resp = claude.messages.create(
        model=model,
        max_tokens=1400,
        system=system,
        messages=[{"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}],
    )
    raw = (resp.content[0].text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        log.error("Claude вернул не-JSON при ревизии: %s\n%s", e, raw[:500])
        return {"should_publish": False, "reason": f"claude invalid JSON: {e}"}
