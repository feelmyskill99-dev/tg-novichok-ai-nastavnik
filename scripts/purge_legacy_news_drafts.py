#!/usr/bin/env python3
"""purge_legacy_news_drafts.py — массово отвергает legacy v1 драфты.

Признаки legacy v1 (отвергаются автоматически):
- claude_json не содержит обязательных v2-полей (specific_title или lead/facts/newbie_voice),
  ИЛИ schema_version != "v2"
- status в {pending_review, revised}

Для каждого:
- status → "rejected"
- owner_feedback → добавляется аудит-запись "legacy purge YYYY-MM-DD"
- updated_at → текущий UTC

Запуск:
  python scripts/purge_legacy_news_drafts.py            # dry-run, показывает что бы отвергло
  python scripts/purge_legacy_news_drafts.py --apply    # реально применить
  python scripts/purge_legacy_news_drafts.py --older-than-days 14   # дополнительный фильтр
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from news.drafts import DraftStore, NewsDraft   # noqa: E402

DRAFTS_PATH = ROOT / "news_drafts.json"


def is_legacy(draft: NewsDraft) -> tuple[bool, str]:
    """Returns (is_legacy, reason)."""
    cj = draft.claude_json or {}
    if draft.schema_version and draft.schema_version != "v2":
        return True, f"schema_version={draft.schema_version!r}"
    has_specific_title = bool((cj.get("specific_title") or "").strip())
    has_lead = bool((cj.get("lead") or "").strip())
    has_facts = isinstance(cj.get("facts"), list) and len(cj.get("facts") or []) == 3
    has_newbie_voice = bool((cj.get("newbie_voice") or "").strip())
    missing = []
    if not has_specific_title:
        missing.append("specific_title")
    if not has_lead:
        missing.append("lead")
    if not has_facts:
        missing.append("facts(=3)")
    if not has_newbie_voice:
        missing.append("newbie_voice")
    if missing:
        return True, f"missing v2 fields: {','.join(missing)}"
    return False, ""


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Purge legacy v1 news drafts")
    parser.add_argument("--apply", action="store_true",
                        help="реально применить изменения (по умолчанию dry-run)")
    parser.add_argument("--older-than-days", type=int, default=0,
                        help="дополнительный фильтр: пропускать драфты моложе N дней")
    args = parser.parse_args()

    store = DraftStore(DRAFTS_PATH)
    all_drafts = store.list_all()
    pending = [d for d in all_drafts if d.status in ("pending_review", "revised")]
    now = datetime.now(tz=timezone.utc)
    cutoff = now - timedelta(days=args.older_than_days) if args.older_than_days else now

    print(f"Загружено: {len(all_drafts)} драфтов всего, {len(pending)} pending/revised")

    candidates: list[tuple[NewsDraft, str]] = []
    for d in pending:
        legacy, reason = is_legacy(d)
        if not legacy:
            continue
        if args.older_than_days:
            try:
                created = datetime.fromisoformat(d.created_at)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if created > cutoff:
                    continue
            except Exception:
                pass
        candidates.append((d, reason))

    print(f"Кандидатов на purge: {len(candidates)}")
    print()
    for d, reason in candidates:
        src_title = (d.source_news.get("title") if isinstance(d.source_news, dict) else "") or ""
        print(f"  [{d.created_at[:10]}] {d.draft_id[:8]}  {reason}")
        print(f"    src: {src_title[:80]}")

    if not candidates:
        print("Нечего purge.")
        return 0

    if not args.apply:
        print()
        print("DRY-RUN — ничего не изменено. Запусти с --apply для применения.")
        return 0

    audit_note = f"legacy purge {now.date().isoformat()}"
    for draft, reason in candidates:
        draft.status = "rejected"
        draft.owner_feedback = list(draft.owner_feedback or [])
        draft.owner_feedback.append(f"{audit_note}: {reason}")
        store.update(draft)

    print()
    print(f"OK — отклонено {len(candidates)} legacy драфтов с пометкой '{audit_note}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
