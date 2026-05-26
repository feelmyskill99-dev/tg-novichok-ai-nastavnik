#!/usr/bin/env python3
"""distribution_outreach.py — печатает топ-N целевых каналов для outreach.

Читает docs/distribution/target_channels.md (YAML-секции, разделённые `---`),
фильтрует по status, сортирует по приоритету, подставляет шаблон сообщения
из docs/distribution/outreach_templates.md.

Запуск:
  python scripts/distribution_outreach.py                   # топ-5 todo
  python scripts/distribution_outreach.py --top 10          # топ-10
  python scripts/distribution_outreach.py --status all      # включить уже contacted/done
  python scripts/distribution_outreach.py --template-only X # только текст шаблона X
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHANNELS_FILE = ROOT / "docs" / "distribution" / "target_channels.md"
TEMPLATES_FILE = ROOT / "docs" / "distribution" / "outreach_templates.md"


@dataclass
class Channel:
    username: str = ""
    title: str = ""
    subscribers_estimate: int = 0
    relevance_score: int = 0
    last_post_age_days: int = 999
    overlap_topics: list[str] = field(default_factory=list)
    owner_contact: str = ""
    contact_method: str = ""
    outreach_template: str = ""
    notes: str = ""
    status: str = "todo"
    last_contacted_at: str = ""

    @property
    def is_valid(self) -> bool:
        return bool(self.username and self.title)

    @property
    def priority_key(self) -> tuple:
        """Меньше=раньше. Сортируем: todo впереди, потом большой relevance,
        потом свежесть канала (меньше last_post_age_days)."""
        status_rank = {"todo": 0, "contacted": 1, "responded": 2, "accepted": 3,
                       "declined": 4, "done": 5}.get(self.status, 9)
        return (status_rank, -self.relevance_score, self.last_post_age_days)


def _parse_yaml_value(raw: str):
    """Очень узкий парсер: int, list (на отдельных строках с '-'), плоский str."""
    raw = raw.strip()
    if not raw:
        return ""
    # int
    if re.fullmatch(r"-?\d+", raw):
        try:
            return int(raw)
        except ValueError:
            pass
    # quoted string
    m = re.fullmatch(r'"(.*)"', raw)
    if m:
        return m.group(1)
    return raw


def parse_channels_md(text: str) -> list[Channel]:
    """Парсит блоки YAML-like, разделённые `---` внутри markdown.

    Игнорирует блоки внутри HTML-комментариев (`<!--` ... `-->`),
    и блоки внутри code-fence (` ``` `).
    """
    # Убираем HTML-комментарии (пример-блоки)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    # Убираем code-блоки
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)

    # Делим по `---` на строке (только)
    blocks = re.split(r"\n---\s*\n", "\n" + text + "\n")

    channels: list[Channel] = []
    for block in blocks:
        block = block.strip()
        if not block or not re.search(r"^username\s*:", block, re.MULTILINE):
            continue
        ch = _parse_block(block)
        if ch.is_valid:
            channels.append(ch)
    return channels


def _parse_block(block: str) -> Channel:
    ch = Channel()
    lines = block.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        m = re.match(r"^(\w+)\s*:\s*(.*)$", line)
        if not m:
            i += 1
            continue
        key, value = m.group(1), m.group(2)
        if key == "overlap_topics" and not value.strip():
            # next lines starting with -
            items = []
            j = i + 1
            while j < len(lines) and re.match(r"^\s*-\s+", lines[j]):
                items.append(re.sub(r'^\s*-\s+"?(.*?)"?$', r"\1", lines[j]).strip())
                j += 1
            ch.overlap_topics = items
            i = j
            continue
        parsed = _parse_yaml_value(value)
        if hasattr(ch, key):
            setattr(ch, key, parsed)
        i += 1
    return ch


def parse_templates_md(text: str) -> dict[str, str]:
    """Извлекает code-блоки из секций ## Template: `name`."""
    out: dict[str, str] = {}
    # ищем "## Template: `name`" затем первый ```...```
    pattern = re.compile(
        r"##\s*Template:\s*`(\w+)`.*?```\n(.*?)```",
        re.DOTALL,
    )
    for m in pattern.finditer(text):
        name, body = m.group(1), m.group(2).strip()
        out[name] = body
    return out


def format_channel_card(ch: Channel, template_text: str = "") -> str:
    """Печатает карточку канала + шаблон outreach."""
    topics = ", ".join(ch.overlap_topics) if ch.overlap_topics else "—"
    lines = [
        f"╔══ {ch.title or '—'}",
        f"║   {ch.username}  ·  ~{ch.subscribers_estimate} subs  ·  relevance {ch.relevance_score}/10",
        f"║   last post: {ch.last_post_age_days}d ago  ·  status: {ch.status}",
        f"║   topics: {topics}",
    ]
    if ch.owner_contact:
        lines.append(f"║   contact: {ch.owner_contact} ({ch.contact_method or 'unspecified'})")
    if ch.notes:
        lines.append(f"║   notes: {ch.notes}")
    lines.append(f"║   template: {ch.outreach_template or '—'}")
    if template_text:
        lines.append("║")
        for tl in template_text.split("\n"):
            lines.append(f"║   {tl}")
    lines.append("╚════════════════════════════════════════════════════════════════")
    return "\n".join(lines)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Outreach helper для @ai_deposit_diary")
    parser.add_argument("--top", type=int, default=5,
                        help="Сколько каналов показать (default 5)")
    parser.add_argument("--status", default="todo",
                        choices=["todo", "contacted", "responded", "all"],
                        help="Фильтр по status (default todo)")
    parser.add_argument("--template-only",
                        help="Только текст шаблона по имени (exchange / guest_post / ...)")
    args = parser.parse_args()

    if not CHANNELS_FILE.exists():
        print(f"Нет файла {CHANNELS_FILE} — заполни target_channels.md", file=sys.stderr)
        return 1
    if not TEMPLATES_FILE.exists():
        print(f"Нет файла {TEMPLATES_FILE}", file=sys.stderr)
        return 1

    templates = parse_templates_md(TEMPLATES_FILE.read_text(encoding="utf-8"))

    if args.template_only:
        body = templates.get(args.template_only)
        if not body:
            print(f"Шаблон '{args.template_only}' не найден. Доступные: {', '.join(templates.keys()) or '(пусто)'}",
                  file=sys.stderr)
            return 1
        print(body)
        return 0

    channels = parse_channels_md(CHANNELS_FILE.read_text(encoding="utf-8"))

    if args.status != "all":
        channels = [c for c in channels if c.status == args.status]

    channels.sort(key=lambda c: c.priority_key)
    top = channels[: args.top]

    if not top:
        print()
        print(f"Нечего показать — статус '{args.status}' пуст.")
        print(f"Заполни {CHANNELS_FILE} (см. примеры в комментариях файла).")
        print("Минимум 5-10 каналов нужно чтобы скрипт стал полезным.")
        return 0

    print()
    print(f"=== TOP {len(top)} CHANNELS (status={args.status}) ===")
    print()
    for ch in top:
        tpl = templates.get(ch.outreach_template, "")
        print(format_channel_card(ch, tpl))
        print()

    print(f"Всего каналов в файле: {len(parse_channels_md(CHANNELS_FILE.read_text(encoding='utf-8')))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
