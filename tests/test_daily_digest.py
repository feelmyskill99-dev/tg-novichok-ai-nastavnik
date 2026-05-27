from datetime import datetime, timezone, timedelta
from core.daily_digest import build_digest_html

NOW = datetime(2026, 5, 27, 18, 0, tzinfo=timezone.utc)

def _ts(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat(timespec="seconds")


def test_returns_none_when_below_min_posts():
    log_list = [
        {
            "timestamp": _ts(0),
            "published_to": "channel",
            "title": "Post 1",
        },
        {
            "timestamp": _ts(2),
            "published_to": "channel",
            "title": "Post 2",
        },
    ]
    result = build_digest_html(log_list, now=NOW, min_posts=3)
    assert result is None


def test_returns_html_when_min_posts_reached():
    log_list = [
        {"timestamp": _ts(0), "published_to": "channel", "title": "Post 1"},
        {"timestamp": _ts(1), "published_to": "channel", "title": "Post 2"},
        {"timestamp": _ts(2), "published_to": "channel", "title": "Post 3"},
    ]
    result = build_digest_html(log_list, now=NOW, min_posts=3)
    assert result is not None and result.startswith("🎯")


def test_filters_out_yesterday_posts():
    log_list = [
        {"timestamp": _ts(0), "published_to": "channel", "title": "Today 1"},
        {"timestamp": _ts(1), "published_to": "channel", "title": "Today 2"},
    ]
    for i in range(5):
        log_list.append({
            "timestamp": _ts(24 + i),
            "published_to": "channel",
            "title": f"Yesterday {i}",
        })
    result = build_digest_html(log_list, now=NOW, min_posts=3)
    assert result is None


def test_filters_out_owner_posts():
    log_list = [
        {"timestamp": _ts(0), "published_to": "channel", "title": "Channel 1"},
        {"timestamp": _ts(1), "published_to": "channel", "title": "Channel 2"},
    ]
    for i in range(5):
        log_list.append({
            "timestamp": _ts(2 + i),
            "published_to": "owner",
            "title": f"Owner {i}",
        })
    result = build_digest_html(log_list, now=NOW, min_posts=3)
    assert result is None


def test_sorts_by_timestamp_ascending():
    # _ts(6) — это 6 часов назад (раньше), _ts(0) — текущий момент (позже).
    # ASC сортировка: ранний идёт первым.
    log_list = [
        {"timestamp": _ts(0), "published_to": "channel", "title": "Late"},   # самый свежий
        {"timestamp": _ts(3), "published_to": "channel", "title": "Mid"},
        {"timestamp": _ts(6), "published_to": "channel", "title": "Early"},  # самый ранний
    ]
    result = build_digest_html(log_list, now=NOW, min_posts=3)
    assert result is not None
    idx_early = result.index("Early")
    idx_mid = result.index("Mid")
    idx_late = result.index("Late")
    assert idx_early < idx_mid < idx_late


def test_caps_at_max_posts():
    log_list = [
        {"timestamp": _ts(i), "published_to": "channel", "title": f"Post {i}"}
        for i in range(20)
    ]
    result = build_digest_html(log_list, now=NOW, min_posts=3, max_posts=5)
    assert result is not None
    assert result.count("❕") == 1
    assert result.count("▫️") == 4


def test_message_id_renders_as_anchor():
    log_list = [
        {
            "timestamp": _ts(1),
            "published_to": "channel",
            "title": "Test post with link",
            "message_id": 108,
        },
        {
            "timestamp": _ts(0),
            "published_to": "channel",
            "title": "Second post",
        },
    ]
    result = build_digest_html(
        log_list, channel_id_for_links="@ai_deposit_diary", now=NOW, min_posts=1,
    )
    assert result is not None
    expected_link = '<a href="https://t.me/ai_deposit_diary/108">'
    assert expected_link in result


def test_numeric_channel_link():
    log_list = [
        {
            "timestamp": _ts(0),
            "published_to": "channel",
            "title": "Numeric channel",
            "message_id": 42,
        }
    ]
    result = build_digest_html(
        log_list, channel_id_for_links="-1001234567890", now=NOW, min_posts=1,
    )
    assert result is not None
    expected_link = "https://t.me/c/1234567890/42"
    assert expected_link in result


def test_no_message_id_renders_as_plain():
    log_list = [
        {
            "timestamp": _ts(0),
            "published_to": "channel",
            "title": "Plain post",
        }
    ]
    result = build_digest_html(
        log_list, channel_id_for_links="@some_channel", now=NOW, min_posts=1,
    )
    assert result is not None
    assert '<a href' not in result
    assert "Plain post" in result


def test_html_escapes_title():
    log_list = [
        {
            "timestamp": _ts(0),
            "published_to": "channel",
            "title": "Hack <script>alert(1)</script>",
        }
    ]
    result = build_digest_html(log_list, now=NOW, min_posts=1)
    assert result is not None
    assert "&lt;script&gt;" in result
    assert "<script>" not in result