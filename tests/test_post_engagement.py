"""core.post_engagement — учёт реакций под постами."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.post_engagement import (
    apply_reaction_update,
    evict_old_entries,
    top_posts_by_engagement,
    total_reaction_count,
)


# ============================================================
# apply_reaction_update
# ============================================================


def test_first_reaction_adds_entry_and_count():
    eng = {}
    out = apply_reaction_update(
        eng, chat_id=-100123, message_id=42,
        old_emojis=[], new_emojis=["👍"], now="2026-05-26T20:00:00+00:00",
    )
    key = "-100123:42"
    assert key in out
    assert out[key]["chat_id"] == -100123
    assert out[key]["message_id"] == 42
    assert out[key]["reactions"] == {"👍": 1}
    assert out[key]["first_seen_at"] == "2026-05-26T20:00:00+00:00"
    assert out[key]["last_updated_at"] == "2026-05-26T20:00:00+00:00"


def test_second_reaction_increments_existing_count():
    eng = {}
    apply_reaction_update(eng, chat_id=1, message_id=1, old_emojis=[], new_emojis=["🔥"],
                          now="2026-05-26T10:00:00+00:00")
    apply_reaction_update(eng, chat_id=1, message_id=1, old_emojis=[], new_emojis=["🔥"],
                          now="2026-05-26T10:05:00+00:00")
    entry = eng["1:1"]
    assert entry["reactions"] == {"🔥": 2}
    assert entry["last_updated_at"] == "2026-05-26T10:05:00+00:00"
    # first_seen_at не меняется
    assert entry["first_seen_at"] == "2026-05-26T10:00:00+00:00"


def test_user_changes_reaction_decrements_old_increments_new():
    """Пользователь сменил 👍 на 🔥 — total count прежний, но distribution другая."""
    eng = {}
    apply_reaction_update(eng, chat_id=1, message_id=1, old_emojis=[], new_emojis=["👍"])
    apply_reaction_update(eng, chat_id=1, message_id=1, old_emojis=[], new_emojis=["👍"])
    apply_reaction_update(eng, chat_id=1, message_id=1, old_emojis=[], new_emojis=["👍"])
    # 3 user'а с 👍
    assert eng["1:1"]["reactions"] == {"👍": 3}
    # один из них меняет на 🔥
    apply_reaction_update(eng, chat_id=1, message_id=1, old_emojis=["👍"], new_emojis=["🔥"])
    assert eng["1:1"]["reactions"] == {"👍": 2, "🔥": 1}


def test_user_removes_reaction():
    eng = {}
    apply_reaction_update(eng, chat_id=1, message_id=1, old_emojis=[], new_emojis=["🐹"])
    assert eng["1:1"]["reactions"] == {"🐹": 1}
    apply_reaction_update(eng, chat_id=1, message_id=1, old_emojis=["🐹"], new_emojis=[])
    # Реакция полностью удалена — ключ исчезает из dict
    assert eng["1:1"]["reactions"] == {}


def test_removing_below_zero_clamped():
    """Если по какой-то причине old > current count — не падаем, не уходим в минус."""
    eng = {}
    apply_reaction_update(eng, chat_id=1, message_id=1, old_emojis=["👍"], new_emojis=[])
    assert eng["1:1"]["reactions"] == {}


def test_same_emoji_in_old_and_new_no_change():
    """edge: TG присылает событие где old == new (рандомный re-fire) — total не меняется."""
    eng = {}
    apply_reaction_update(eng, chat_id=1, message_id=1, old_emojis=[], new_emojis=["👍"])
    apply_reaction_update(eng, chat_id=1, message_id=1, old_emojis=[], new_emojis=["👍"])
    # 2 пользователя ставили
    apply_reaction_update(eng, chat_id=1, message_id=1, old_emojis=["👍"], new_emojis=["👍"])
    # один из них поставил тот же эмодзи (TG может выдать такой update)
    # Итого: -1 +1 = 2, без изменений
    assert eng["1:1"]["reactions"] == {"👍": 2}


def test_ignores_non_string_emojis():
    eng = {}
    apply_reaction_update(eng, chat_id=1, message_id=1,
                          old_emojis=[None, ""], new_emojis=["👍", "", None, 42])
    # 👍 учтён, остальные проигнорированы
    assert eng["1:1"]["reactions"] == {"👍": 1}


def test_handles_non_dict_engagement_input():
    out = apply_reaction_update(
        None, chat_id=1, message_id=1, old_emojis=[], new_emojis=["👍"],
    )
    assert "1:1" in out
    assert out["1:1"]["reactions"] == {"👍": 1}


# ============================================================
# evict_old_entries
# ============================================================


def test_evict_keeps_most_recent_by_last_updated_at():
    eng = {
        "1:1": {"chat_id": 1, "message_id": 1, "last_updated_at": "2026-05-26T10:00:00+00:00", "reactions": {"👍": 1}},
        "1:2": {"chat_id": 1, "message_id": 2, "last_updated_at": "2026-05-26T12:00:00+00:00", "reactions": {"🔥": 1}},
        "1:3": {"chat_id": 1, "message_id": 3, "last_updated_at": "2026-05-26T11:00:00+00:00", "reactions": {"🐹": 1}},
    }
    out = evict_old_entries(eng, max_tracked=2)
    assert set(out.keys()) == {"1:2", "1:3"}   # самые свежие


def test_evict_noop_when_under_limit():
    eng = {"1:1": {"last_updated_at": "2026-05-26T10:00:00+00:00"}}
    assert evict_old_entries(eng, max_tracked=10) is eng


# ============================================================
# top_posts_by_engagement
# ============================================================


def test_top_posts_sorted_by_total_reactions():
    eng = {
        "1:1": {"reactions": {"👍": 5}},
        "1:2": {"reactions": {"🔥": 2, "👍": 1}},
        "1:3": {"reactions": {"🐹": 10, "👍": 3}},
    }
    top = top_posts_by_engagement(eng, limit=3)
    assert [t[0] for t in top] == ["1:3", "1:1", "1:2"]   # 13 > 5 > 3
    assert top[0][2] == 13


def test_top_posts_unique_metric():
    eng = {
        "1:1": {"reactions": {"👍": 100}},                  # 1 уникальная
        "1:2": {"reactions": {"🔥": 1, "👍": 1, "🐹": 1}},  # 3 уникальных
    }
    top = top_posts_by_engagement(eng, limit=2, metric="unique")
    assert top[0][0] == "1:2"


def test_top_posts_respects_limit():
    eng = {f"1:{i}": {"reactions": {"👍": i}} for i in range(1, 11)}
    top = top_posts_by_engagement(eng, limit=3)
    assert len(top) == 3
    assert top[0][2] == 10   # пост с max count


def test_top_posts_empty_returns_empty_list():
    assert top_posts_by_engagement({}, limit=5) == []
    assert top_posts_by_engagement(None, limit=5) == []


# ============================================================
# total_reaction_count
# ============================================================


def test_total_reaction_count_sums_across_posts():
    eng = {
        "1:1": {"reactions": {"👍": 3, "🔥": 1}},
        "1:2": {"reactions": {"🐹": 5}},
    }
    assert total_reaction_count(eng) == 9


def test_total_reaction_count_handles_empty():
    assert total_reaction_count({}) == 0
    assert total_reaction_count(None) == 0
