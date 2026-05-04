"""External style guides loader.

Загружает markdown-файлы из корня проекта и отдаёт их как авторитетный
style-context для Claude system prompts. Сами .md НЕ переписываются.

Использование:
    from style_guides import load_guide, compose_style_context, load_prompt_file
    sys_prompt = base_prompt + "\\n" + compose_style_context("news")

Кэш — in-memory; проверяется mtime, при изменении файла перечитываем.
Если файл отсутствует — возвращаем короткий fallback и пишем warning.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable, Union


log = logging.getLogger("style_guides")


ROOT = Path(__file__).resolve().parent
GUIDE_FILES: dict[str, str] = {
    "base":         "base_channel_style.md",
    "instructions": "instructions.md",
    "news":         "news_style_guide.md",
    "trade":        "trade_style_guide.md",
    "author_note":  "author_note_style.md",
}

# Короткие fallback'и на случай отсутствия .md — чтобы pipeline не падал
# и Claude всё равно получил минимальный ориентир по стилю.
_DEFAULT_FALLBACKS: dict[str, str] = {
    "base":         "Стиль канала «Депозит под надзором ИИ»: новичок-трейдер + AI-наставник. Не сигналы, не гуру, не мемы. Без токсичности.",
    "instructions": "Канал — обучающий дневник. Не выдумывай факты. Не давай торговых советов. Telegram-формат: короткие абзацы.",
    "news":         "Новости: не выдумывай, отделяй факт от предположения. Запрещены «сигнал», «точно вырастет», «заходим». Указывай источник.",
    "trade":        "Сделки — учебные paper. Никаких «сигналов», «повторяйте», «заработали». Объясняй риск, дисциплину, ошибку новичка.",
    "author_note":  "Личная заметка: честный голос новичка, без выдуманных биографических фактов. Без сигналов и обещаний.",
}

# Кэш по абсолютному пути файла → (mtime, content)
_CACHE: dict[str, tuple[float, str]] = {}

# Чтобы не спамить warning'ами в каждом запросе — помним пути,
# про которые уже сказали «отсутствует».
_WARNED_MISSING: set[str] = set()


def _enabled() -> bool:
    """Глобальный outlet: STYLE_GUIDES_ENABLED=false полностью отключает loader."""
    return os.getenv("STYLE_GUIDES_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")


def load_prompt_file(path: Union[str, Path], fallback: str = "") -> str:
    """Прочитать prompt/style .md с диска. mtime-cached, не падает.

    - path: абсолютный или относительный (от корня проекта) путь.
    - fallback: что вернуть, если файла нет / не читается / loader выключен.

    При первом отсутствии файла пишем warning в лог; повторные обращения
    к тому же отсутствующему пути молчат (чтобы не засорять логи).
    """
    if not _enabled():
        return fallback

    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    key = str(p)

    if not p.exists():
        if key not in _WARNED_MISSING:
            log.warning("style guide missing: %s — using fallback (%d chars)", p, len(fallback))
            _WARNED_MISSING.add(key)
        return fallback

    # файл появился после предыдущего «missing» — забываем warning, чтобы
    # при следующем удалении он снова сработал.
    _WARNED_MISSING.discard(key)

    try:
        mtime = p.stat().st_mtime
    except OSError as e:
        log.warning("cannot stat %s: %s — using fallback", p, e)
        return fallback

    cached = _CACHE.get(key)
    if cached and cached[0] == mtime:
        return cached[1]

    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        log.warning("cannot read %s: %s — using fallback", p, e)
        return fallback

    _CACHE[key] = (mtime, text)
    return text


def load_guide(name: str) -> str:
    """Вернуть содержимое именованного style guide.

    Если файла нет — короткий fallback из _DEFAULT_FALLBACKS (или "").
    Если loader выключен — пустая строка.
    """
    if not _enabled():
        return ""
    rel = GUIDE_FILES.get(name)
    if not rel:
        log.warning("unknown style guide: %s", name)
        return ""
    fallback = _DEFAULT_FALLBACKS.get(name, "")
    return load_prompt_file(rel, fallback)


def compose_style_context(
    *names: str,
    header: str = "СТИЛЬ-ГАЙД (обязательный, имеет приоритет над дефолтами):",
) -> str:
    """Склеить несколько guides в один блок для system prompt.

    Пример:
        compose_style_context("base", "news")
    """
    if not _enabled():
        return ""
    parts: list[str] = []
    for name in names:
        body = load_guide(name).strip()
        if not body:
            continue
        parts.append(f"=== STYLE GUIDE: {name} ({GUIDE_FILES.get(name, '?')}) ===\n{body}")
    if not parts:
        return ""
    sep = "\n\n" + ("─" * 70) + "\n\n"
    return f"\n\n{header}\n\n" + sep.join(parts) + sep


def list_available() -> Iterable[tuple[str, bool, int]]:
    """(name, exists, size_bytes) — для CLI/диагностики."""
    for name, rel in GUIDE_FILES.items():
        path = ROOT / rel
        if path.exists():
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            yield (name, True, size)
        else:
            yield (name, False, 0)
