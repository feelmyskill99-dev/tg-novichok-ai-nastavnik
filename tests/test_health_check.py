"""Этап 3.2: tests для scripts/health_check.py."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import health_check as hc


@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Перенаправляем health_check на изолированную tmp директорию."""
    monkeypatch.setattr(hc, "ROOT", tmp_path)
    monkeypatch.setattr(hc, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(hc, "HISTORY_FILE", tmp_path / "history.json")
    monkeypatch.setattr(hc, "NEWS_DRAFTS_FILE", tmp_path / "news_drafts.json")
    monkeypatch.setattr(hc, "AUTHOR_DRAFTS_FILE", tmp_path / "author_notes_drafts.json")
    monkeypatch.setattr(hc, "WEEKLY_DRAFTS_FILE", tmp_path / "weekly_diary_drafts.json")
    monkeypatch.setattr(hc, "CONFIRM_TRADES_FILE", tmp_path / "confirm_trades.json")
    monkeypatch.setattr(hc, "SCHEDULER_LOG", tmp_path / "outputs" / "scheduler.log")
    yield tmp_path


def _now_minus(hours: float) -> str:
    return (datetime.now(tz=timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")


def test_empty_state_reports_not_ok(_isolate_paths):
    """Свежая папка → нет постов, нет scheduler.log → ok=False."""
    report = hc.build_health_report()

    assert report["ok"] is False
    assert report["scheduler_hint"] == "no_log"
    assert report["last_post_iso"] is None
    assert report["post_stale"] is True


def test_fresh_post_and_scheduler_ok(_isolate_paths, tmp_path):
    """Свежий пост + свежий scheduler.log → ok=True."""
    (tmp_path / "history.json").write_text(json.dumps([
        {"datetime": _now_minus(1.0), "post_type": "market"},
    ]), encoding="utf-8")
    log_path = tmp_path / "outputs" / "scheduler.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("alive", encoding="utf-8")

    report = hc.build_health_report()

    assert report["ok"] is True
    assert report["scheduler_hint"] == "alive"
    assert report["post_stale"] is False
    assert report["last_post_age_hours"] is not None
    assert report["last_post_age_hours"] <= 2.0


def test_stale_post_warns(_isolate_paths, tmp_path):
    """Пост старше 24h → stale → ok=False даже при живом scheduler."""
    (tmp_path / "history.json").write_text(json.dumps([
        {"datetime": _now_minus(48.0), "post_type": "market"},
    ]), encoding="utf-8")
    log_path = tmp_path / "outputs" / "scheduler.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("alive", encoding="utf-8")

    report = hc.build_health_report()

    assert report["post_stale"] is True
    assert report["ok"] is False


def test_stale_scheduler_log(_isolate_paths, tmp_path):
    """scheduler.log старше 10 мин → status=stale."""
    log_path = tmp_path / "outputs" / "scheduler.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("old", encoding="utf-8")
    # сделаем mtime час назад
    import os
    old_ts = (datetime.now(tz=timezone.utc) - timedelta(hours=1)).timestamp()
    os.utime(log_path, (old_ts, old_ts))

    report = hc.build_health_report()

    assert report["scheduler_hint"] == "stale"
    assert report["scheduler_log_age_seconds"] > 600


def test_pending_drafts_counted(_isolate_paths, tmp_path):
    (tmp_path / "news_drafts.json").write_text(json.dumps([
        {"draft_id": "n1", "status": "pending_review"},
        {"draft_id": "n2", "status": "published"},  # не считается
        {"draft_id": "n3", "status": "revised"},
    ]), encoding="utf-8")
    (tmp_path / "author_notes_drafts.json").write_text(json.dumps([
        {"draft_id": "a1", "status": "pending_review"},
    ]), encoding="utf-8")
    (tmp_path / "weekly_diary_drafts.json").write_text(json.dumps([]), encoding="utf-8")

    report = hc.build_health_report()

    assert report["pending_news_drafts"] == 2
    assert report["pending_author_notes"] == 1
    assert report["pending_weekly_diary"] == 0


def test_active_confirm_trades_counted(_isolate_paths, tmp_path):
    (tmp_path / "confirm_trades.json").write_text(json.dumps([
        {"id": "t1", "status": "awaiting_confirmation"},
        {"id": "t2", "status": "active"},
        {"id": "t3", "status": "closed_take_profit"},  # terminal, не считается
        {"id": "t4", "status": "rejected"},  # terminal
    ]), encoding="utf-8")

    report = hc.build_health_report()

    assert report["active_confirm_trades"] == 2


def test_corrupt_json_does_not_crash(_isolate_paths, tmp_path):
    (tmp_path / "history.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "news_drafts.json").write_text("[not json", encoding="utf-8")

    report = hc.build_health_report()

    assert report["last_post_iso"] is None
    assert report["pending_news_drafts"] == 0


def test_history_with_invalid_datetime(_isolate_paths, tmp_path):
    (tmp_path / "history.json").write_text(json.dumps([
        {"datetime": "not-an-iso", "post_type": "market"},
    ]), encoding="utf-8")

    report = hc.build_health_report()

    # last_post_iso вернётся (он есть), но last_post_age_hours = None
    assert report["last_post_iso"] == "not-an-iso"
    assert report["last_post_age_hours"] is None
    assert report["post_stale"] is True  # invalid date → stale


def test_report_includes_checked_at_iso(_isolate_paths):
    report = hc.build_health_report()

    assert "checked_at" in report
    # должно парситься как ISO
    datetime.fromisoformat(report["checked_at"].replace("Z", "+00:00"))


def test_report_keys_contract(_isolate_paths):
    """Контракт: фиксируем ключи отчёта, чтобы watchdog мог надёжно парсить."""
    report = hc.build_health_report()

    expected_keys = {
        "ok", "last_post_iso", "last_post_age_hours", "post_stale",
        "scheduler_hint", "scheduler_log_age_seconds",
        "pending_news_drafts", "pending_author_notes", "pending_weekly_diary",
        "active_confirm_trades", "checked_at",
    }
    assert expected_keys.issubset(report.keys())
