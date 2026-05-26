"""Этап 3.2: health-check для Task Scheduler watchdog.

Запуск:
    python scripts/health_check.py             # человекочитаемый
    python scripts/health_check.py --json      # один-в-строке JSON для парсинга

Exit code:
    0 — ok
    1 — что-то не так (см. поле scheduler_hint)

Что проверяем (без внешних API):
- последняя запись в history.json (когда был последний пост)
- последняя запись в outputs/scheduler.log (когда scheduler last alive)
- pending review-drafts: news, author_notes, weekly_diary
- открытые confirm-сделки

Не дёргает Telegram/Claude/Gate.io — read-only, безопасно для cron.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.json_store import load_json


STATE_FILE = ROOT / "state.json"
HISTORY_FILE = ROOT / "history.json"
NEWS_DRAFTS_FILE = ROOT / "news_drafts.json"
AUTHOR_DRAFTS_FILE = ROOT / "author_notes_drafts.json"
WEEKLY_DRAFTS_FILE = ROOT / "weekly_diary_drafts.json"
CONFIRM_TRADES_FILE = ROOT / "confirm_trades.json"
SCHEDULER_LOG = ROOT / "outputs" / "scheduler.log"

SCHEDULER_ALIVE_SECS = 600
POST_STALE_HOURS = 24


def _last_post_iso() -> str | None:
    history = load_json(HISTORY_FILE, default=[], expected_type=list)
    if not history:
        return None
    last = history[-1] if isinstance(history[-1], dict) else None
    if not last:
        return None
    return last.get("datetime")


def _scheduler_status() -> tuple[str, int]:
    if not SCHEDULER_LOG.exists():
        return "no_log", -1
    try:
        mtime = datetime.fromtimestamp(SCHEDULER_LOG.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return "stat_failed", -1
    age = int((datetime.now(tz=timezone.utc) - mtime).total_seconds())
    status = "alive" if age <= SCHEDULER_ALIVE_SECS else "stale"
    return status, age


def _count_pending(path: Path) -> int:
    items = load_json(path, default=[], expected_type=list)
    return sum(
        1 for d in items
        if isinstance(d, dict) and d.get("status") in ("pending_review", "revised")
    )


def _count_open_confirm_trades() -> int:
    items = load_json(CONFIRM_TRADES_FILE, default=[], expected_type=list)
    NON_TERMINAL = {
        "created", "awaiting_confirmation", "approved",
        "entry_order_submitted", "entry_filled",
        "protection_orders_submitted", "active",
    }
    return sum(
        1 for t in items
        if isinstance(t, dict) and t.get("status") in NON_TERMINAL
    )


def _hours_since(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None
    delta = datetime.now(tz=timezone.utc) - dt
    return round(delta.total_seconds() / 3600, 2)


def build_health_report() -> dict:
    last_post_iso = _last_post_iso()
    last_post_age_h = _hours_since(last_post_iso)
    sched_status, sched_age_s = _scheduler_status()

    post_stale = (last_post_age_h is None) or (last_post_age_h > POST_STALE_HOURS)
    scheduler_ok = sched_status == "alive"
    ok = scheduler_ok and not post_stale

    return {
        "ok": ok,
        "last_post_iso": last_post_iso,
        "last_post_age_hours": last_post_age_h,
        "post_stale": post_stale,
        "scheduler_hint": sched_status,
        "scheduler_log_age_seconds": sched_age_s,
        "pending_news_drafts": _count_pending(NEWS_DRAFTS_FILE),
        "pending_author_notes": _count_pending(AUTHOR_DRAFTS_FILE),
        "pending_weekly_diary": _count_pending(WEEKLY_DRAFTS_FILE),
        "active_confirm_trades": _count_open_confirm_trades(),
        "checked_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
    }


def _human_print(report: dict) -> None:
    print("=" * 60)
    print("HEALTH CHECK — deposit_ai")
    print(f"checked: {report['checked_at']}")
    print("=" * 60)
    status = "OK" if report["ok"] else "WARN"
    print(f"\nOverall: [{status}]")
    print(f"\nScheduler: {report['scheduler_hint']}  "
          f"(log age={report['scheduler_log_age_seconds']}s)")
    print(f"Last post: {report['last_post_iso'] or '—'}  "
          f"(age={report['last_post_age_hours']}h, stale={report['post_stale']})")
    print(f"\nPending drafts:")
    print(f"  news:         {report['pending_news_drafts']}")
    print(f"  author_notes: {report['pending_author_notes']}")
    print(f"  weekly_diary: {report['pending_weekly_diary']}")
    print(f"\nActive confirm trades: {report['active_confirm_trades']}")
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="JSON one-liner вывод")
    args = parser.parse_args()

    report = build_health_report()

    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        _human_print(report)

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
