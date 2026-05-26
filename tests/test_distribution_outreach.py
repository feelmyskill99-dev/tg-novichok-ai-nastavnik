"""Тесты distribution_outreach: парсер каналов + шаблоны + сортировка."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.distribution_outreach import (
    Channel,
    parse_channels_md,
    parse_templates_md,
)


# ============================================================
# parse_channels_md
# ============================================================


def test_parse_single_channel():
    md = """
# header

---
username: "@example"
title: "Test Channel"
subscribers_estimate: 4500
relevance_score: 9
last_post_age_days: 2
overlap_topics:
  - "обучение"
  - "риск_менеджмент"
owner_contact: "@admin"
contact_method: "tg_dm"
outreach_template: "exchange"
notes: "test note"
status: "todo"
last_contacted_at: ""
"""
    channels = parse_channels_md(md)
    assert len(channels) == 1
    c = channels[0]
    assert c.username == "@example"
    assert c.title == "Test Channel"
    assert c.subscribers_estimate == 4500
    assert c.relevance_score == 9
    assert c.last_post_age_days == 2
    assert c.overlap_topics == ["обучение", "риск_менеджмент"]
    assert c.owner_contact == "@admin"
    assert c.contact_method == "tg_dm"
    assert c.outreach_template == "exchange"
    assert c.notes == "test note"
    assert c.status == "todo"


def test_parse_multiple_channels():
    md = """
---
username: "@first"
title: "First"
subscribers_estimate: 1000
relevance_score: 5

---
username: "@second"
title: "Second"
subscribers_estimate: 2000
relevance_score: 8
"""
    channels = parse_channels_md(md)
    assert len(channels) == 2
    assert channels[0].username == "@first"
    assert channels[1].username == "@second"


def test_parse_ignores_commented_blocks():
    """Блоки внутри <!-- --> не парсятся (они для примера в шаблоне)."""
    md = """
# Header

<!--
---
username: "@commented_example"
title: "Example In Comment"
-->

---
username: "@real"
title: "Real Channel"
"""
    channels = parse_channels_md(md)
    assert len(channels) == 1
    assert channels[0].username == "@real"


def test_parse_ignores_code_blocks():
    """Блоки внутри ``` не парсятся (документация формата)."""
    md = """
Format example:

```yaml
---
username: "@docs_example"
title: "Docs Example"
```

---
username: "@real_one"
title: "Real One"
"""
    channels = parse_channels_md(md)
    assert len(channels) == 1
    assert channels[0].username == "@real_one"


def test_parse_skips_invalid_blocks():
    """Блок без username или title — пропустить."""
    md = """
---
title: "Без username"
relevance_score: 5

---
username: "@ok"
title: "OK Channel"
"""
    channels = parse_channels_md(md)
    assert len(channels) == 1
    assert channels[0].username == "@ok"


def test_parse_empty_overlap_topics():
    md = """
---
username: "@x"
title: "X"
overlap_topics:
"""
    channels = parse_channels_md(md)
    assert len(channels) == 1
    assert channels[0].overlap_topics == []


def test_parse_empty_string_returns_no_channels():
    assert parse_channels_md("") == []
    assert parse_channels_md("# Just header\n\nNo channels.") == []


# ============================================================
# parse_templates_md
# ============================================================


def test_parse_templates_extracts_code_blocks():
    md = """
# Templates

## Template: `exchange`

Some description.

```
Hi from exchange template.
Multi-line body.
```

More text.

## Template: `guest_post`

```
Guest post body.
```
"""
    templates = parse_templates_md(md)
    assert "exchange" in templates
    assert "guest_post" in templates
    assert "Hi from exchange template." in templates["exchange"]
    assert "Multi-line body." in templates["exchange"]
    assert templates["guest_post"] == "Guest post body."


def test_parse_templates_empty():
    assert parse_templates_md("") == {}
    assert parse_templates_md("Just text, no templates.") == {}


# ============================================================
# Channel.priority_key — сортировка
# ============================================================


def test_priority_todo_before_contacted():
    todo = Channel(username="@a", title="A", status="todo", relevance_score=5)
    contacted = Channel(username="@b", title="B", status="contacted", relevance_score=10)
    items = sorted([contacted, todo], key=lambda c: c.priority_key)
    # todo (с relevance=5) идёт раньше contacted (с relevance=10) благодаря статусу
    assert items[0].username == "@a"


def test_priority_higher_relevance_first_within_same_status():
    low = Channel(username="@low", title="L", status="todo", relevance_score=3)
    high = Channel(username="@high", title="H", status="todo", relevance_score=9)
    items = sorted([low, high], key=lambda c: c.priority_key)
    assert items[0].username == "@high"
    assert items[1].username == "@low"


def test_priority_fresher_channel_first_when_tied():
    """При равных status+relevance — раньше тот, у кого пост свежее."""
    old = Channel(username="@old", title="O", status="todo", relevance_score=7,
                  last_post_age_days=20)
    fresh = Channel(username="@fresh", title="F", status="todo", relevance_score=7,
                    last_post_age_days=2)
    items = sorted([old, fresh], key=lambda c: c.priority_key)
    assert items[0].username == "@fresh"


# ============================================================
# Channel.is_valid
# ============================================================


def test_channel_is_valid_requires_username_and_title():
    assert Channel(username="@x", title="X").is_valid
    assert not Channel(username="@x").is_valid
    assert not Channel(title="X").is_valid
    assert not Channel().is_valid
