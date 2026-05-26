"""
Mistake Tracker — следит, о каких ошибках новичков мы писали,
и предлагает наименее освещённую тему для следующего поста.
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

class MistakeTracker:
    def __init__(self, themes_file: str = "mistake_themes.json", state_file: str = "mistake_tracker_state.json"):
        self.themes_file = Path(themes_file)
        self.state_file = Path(state_file)
        self.themes = self._load_themes()
        self.state = self._load_state()

    def _load_themes(self) -> dict:
        with open(self.themes_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _load_state(self) -> dict:
        if self.state_file.exists():
            with open(self.state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"log": []}   # log: [{"theme_id": "...", "ts": "..."}]

    def _save_state(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def get_next_topic(self) -> str:
        """Возвращает тему (title), которую использовали раньше всего (или никогда)."""
        usage = {}
        for entry in self.state["log"]:
            tid = entry["theme_id"]
            ts = datetime.fromisoformat(entry["ts"])
            if tid not in usage or ts > usage[tid]:
                usage[tid] = ts

        now = datetime.now(tz=timezone.utc)
        # Кандидаты: все темы, сортируем по давности использования (None = никогда)
        candidates = []
        for theme_id, theme_info in self.themes.items():
            last_used = usage.get(theme_id)
            if last_used is None:
                # никогда не использовалась — высший приоритет
                age = timedelta.max
            else:
                age = now - last_used
            candidates.append((age, theme_info["title"]))

        # Самая старая тема побеждает
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    def record_usage(self, theme_id: str):
        """Отметить, что тема была использована в посте."""
        self.state["log"].append({
            "theme_id": theme_id,
            "ts": datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        })
        # Оставляем только последние 200 записей
        if len(self.state["log"]) > 200:
            self.state["log"] = self.state["log"][-200:]
        self._save_state()

    def weekly_report(self) -> str:
        """Генерирует отчёт за последние 7 дней."""
        now = datetime.now(tz=timezone.utc)
        cutoff = now - timedelta(days=7)

        # Подсчёт тем за неделю
        recent = [e for e in self.state["log"] if datetime.fromisoformat(e["ts"]) >= cutoff]
        counts = {}
        for e in recent:
            tid = e["theme_id"]
            counts[tid] = counts.get(tid, 0) + 1

        sorted_weekly = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        top_topics = sorted_weekly[:3]

        # Самые забытые темы (нет использований за всё время или очень давно)
        usage_all = {}
        for e in self.state["log"]:
            tid = e["theme_id"]
            ts = datetime.fromisoformat(e["ts"])
            if tid not in usage_all or ts > usage_all[tid]:
                usage_all[tid] = ts

        forgotten = []
        for tid, info in self.themes.items():
            last = usage_all.get(tid)
            if last is None:
                forgotten.append((timedelta.max, info["title"]))
            else:
                age = now - last
                if age > timedelta(days=14):   # не писали больше двух недель
                    forgotten.append((age, info["title"]))

        forgotten.sort(key=lambda x: x[0], reverse=True)
        forgotten_topics = forgotten[:5]

        # Формируем текст
        lines = ["🧠 <b>Mistake Tracker — еженедельный отчёт</b>", ""]
        if top_topics:
            lines.append("<b>Топ ошибок на этой неделе:</b>")
            for tid, count in top_topics:
                title = self.themes[tid]["title"]
                lines.append(f"• {title} — {count} раз(а)")
        else:
            lines.append("На этой неделе не разбирали ошибок.")

        lines.append("")
        if forgotten_topics:
            lines.append("<b>Темы, которые давно не поднимались:</b>")
            for age, title in forgotten_topics:
                days = age.days if age != timedelta.max else "никогда"
                lines.append(f"• {title} (последний раз: {days} дн. назад)")
        else:
            lines.append("Все темы актуальны.")

        return "\n".join(lines)