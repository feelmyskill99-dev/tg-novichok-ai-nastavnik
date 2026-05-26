# Deposit AI Rebranding — Stage 1 (Text Templates) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Устранить визуальное однообразие постов канала @ai_deposit_diary через ротацию дисклеймера, ротацию системных хэштегов и инструкцию Claude по сдержанности RSI/EMA — БЕЗ нарушения голоса и StyleGuard.

**Architecture:** Минимальные точечные правки. Дисклеймер становится списком из 4 вариантов с детерминированной ротацией по дню; системные хэштеги — расширенный пул с выбором 1-2 случайных + 1 темо-специфичный из payload; Claude system-prompt для market получает одну новую строку про метрики.

**Tech Stack:** Python 3.13, pytest, существующий проект deposit_ai. Без новых зависимостей.

**Spec:** `docs/superpowers/specs/2026-05-26-deposit-ai-rebranding-design.md`

---

## File Structure

**Modify:**
- `bot.py:204-209` — заменить `DISCLAIMER_SHORT` (str) на `DISCLAIMER_VARIANTS` (list[str]).
- `bot.py:943, 1022` — вызов ротации вместо прямой константы.
- `core/post_tags.py:27-38` — расширить `system_tags_for` пулом + ротацией.
- bot.py Claude market system-prompt — добавить инструкцию про RSI/EMA.

**Create:**
- `core/disclaimer.py` — `pick_disclaimer(post_type, *, day_seed)` — детерминированный выбор.
- `tests/test_disclaimer.py` — ротация по seed, fallback для education.
- `tests/test_post_tags_rotation.py` — расширение к существующему test_post_tags.

**Не трогать:**
- `DISCLAIMER` (длинная форма) — оставить как есть, она для закрепа/гайдов.
- `_build_post_html_raw` — она дубликат `build_post_html` (вне scope, см. memory project_deposit_ai_refactor этап 2.4-step9+). Фикс применяется к обеим точкам синхронно.
- StyleGuard, post pipeline, content_mix, Task Scheduler.

---

### Task 1: Disclaimer rotation module

**Files:**
- Create: `core/disclaimer.py`
- Test: `tests/test_disclaimer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_disclaimer.py
from datetime import date
from core.disclaimer import pick_disclaimer, DISCLAIMER_VARIANTS, DISCLAIMER_LONG


def test_education_post_uses_long_disclaimer():
    text = pick_disclaimer("fallback_education", day_seed=date(2026, 5, 26))
    assert text == DISCLAIMER_LONG


def test_market_post_picks_from_variants():
    text = pick_disclaimer("market", day_seed=date(2026, 5, 26))
    assert text in DISCLAIMER_VARIANTS


def test_rotation_is_deterministic_per_day():
    a = pick_disclaimer("market", day_seed=date(2026, 5, 26))
    b = pick_disclaimer("market", day_seed=date(2026, 5, 26))
    assert a == b


def test_rotation_changes_across_days():
    seen = {pick_disclaimer("market", day_seed=date(2026, 5, 26 + i)) for i in range(7)}
    assert len(seen) >= 3, "across 7 days should hit at least 3 different variants"


def test_variants_count_is_four():
    assert len(DISCLAIMER_VARIANTS) == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_disclaimer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.disclaimer'`

- [ ] **Step 3: Write minimal implementation**

```python
# core/disclaimer.py
"""Disclaimer rotation. Stage 1 anti-AI-slop fix."""
from __future__ import annotations

from datetime import date

DISCLAIMER_LONG = (
    "Не является финансовым советом. Это личный дневник обучения, "
    "а AI-анализ носит ознакомительный характер."
)

DISCLAIMER_VARIANTS = (
    "Не финсовет. Это дневник обучения и AI-разбор.",
    "Это не сигнал и не совет. Это дневник — для меня и для тех, кто учится рядом.",
    "Я учусь публично. Не повторяй — анализируй.",
    "Дневник, не рекомендация. Любая сделка — твоя ответственность.",
)


def pick_disclaimer(post_type: str, *, day_seed: date) -> str:
    """Deterministic disclaimer selection.

    fallback_education always gets the long form (it goes into educational gaides).
    All other posts rotate through DISCLAIMER_VARIANTS by day-of-year mod 4.
    """
    if post_type == "fallback_education":
        return DISCLAIMER_LONG
    idx = day_seed.toordinal() % len(DISCLAIMER_VARIANTS)
    return DISCLAIMER_VARIANTS[idx]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_disclaimer.py -v`
Expected: PASS — all 5 tests green.

- [ ] **Step 5: Commit**

```bash
git add core/disclaimer.py tests/test_disclaimer.py
git commit -m "feat(rebranding-1.1): disclaimer rotation module with 4 variants"
```

---

### Task 2: Wire disclaimer rotation into bot.py

**Files:**
- Modify: `bot.py:204-209` (replace constants), `bot.py:943` (build_post_html), `bot.py:1022` (build_post_html_raw)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_disclaimer_integration.py
import datetime
from unittest.mock import patch

import bot
from core.disclaimer import DISCLAIMER_VARIANTS


def test_build_post_html_uses_rotated_disclaimer(monkeypatch):
    payload = {"human_part": "test post", "hashtags": ["#test"]}
    # freeze "today" so test is deterministic
    fake_today = datetime.date(2026, 5, 27)

    class _FakeDate(datetime.date):
        @classmethod
        def today(cls):
            return fake_today

    monkeypatch.setattr("bot.date", _FakeDate)
    html = bot.build_post_html(payload, post_type="market", include_partner=False, post_num=1)
    assert any(v in html for v in DISCLAIMER_VARIANTS)


def test_education_post_still_uses_long_disclaimer():
    payload = {"human_part": "edu post", "hashtags": ["#edu"]}
    html = bot.build_post_html(payload, post_type="fallback_education", include_partner=False, post_num=1)
    assert "Не является финансовым советом" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_disclaimer_integration.py -v`
Expected: FAIL — `assert any(v in html for v in DISCLAIMER_VARIANTS)` fails because old `DISCLAIMER_SHORT` is hardcoded.

- [ ] **Step 3: Modify bot.py**

Replace `bot.py:204-209`:

```python
# OLD:
DISCLAIMER = (
    "Не является финансовым советом. Это личный дневник обучения, "
    "а AI-анализ носит ознакомительный характер."
)
DISCLAIMER_SHORT = "Не финсовет. Это дневник обучения и AI-разбор."
```

With:

```python
from datetime import date
from core.disclaimer import (
    DISCLAIMER_LONG as DISCLAIMER,
    pick_disclaimer,
)
```

Replace `bot.py:943` (`disclaimer_text = DISCLAIMER if post_type == ...`):

```python
disclaimer_text = pick_disclaimer(post_type, day_seed=date.today())
```

Replace `bot.py:1022` (same line in `_build_post_html_raw`):

```python
disclaimer_text = pick_disclaimer(post_type, day_seed=date.today())
```

- [ ] **Step 4: Run all bot tests to check no regression**

Run: `pytest tests/ -v -k "disclaimer or build_post_html or post_html"`
Expected: PASS — all tests including new ones.

- [ ] **Step 5: Commit**

```bash
git add bot.py tests/test_disclaimer_integration.py
git commit -m "feat(rebranding-1.2): wire disclaimer rotation into build_post_html"
```

---

### Task 3: Hashtag pool + rotation in core/post_tags.py

**Files:**
- Modify: `core/post_tags.py:27-38`
- Modify: `tests/test_post_tags.py` (existing tests must still pass; add new ones)

- [ ] **Step 1: Read existing tests to understand contract**

Run: `cat tests/test_post_tags.py`
Expected output: shows existing `test_system_tags_*` tests we must not break.

- [ ] **Step 2: Write failing test for new rotation**

Add to `tests/test_post_tags.py`:

```python
from datetime import date
from core.post_tags import system_tags_for


def test_canal_anchor_tag_always_present():
    """#честный_путь — единственный маркер канала, всегда есть."""
    for d in range(1, 30):
        tags = system_tags_for("market", has_hamster=True, day_seed=date(2026, 5, d))
        assert "#честный_путь" in tags


def test_secondary_tag_rotates_across_week():
    """Вторичный тег должен покрыть ≥3 разных значения за 7 дней."""
    seen = set()
    for d in range(1, 8):
        tags = system_tags_for("market", has_hamster=True, day_seed=date(2026, 5, d))
        # secondary = первый тег после #честный_путь
        secondary = [t for t in tags if t != "#честный_путь"][:1]
        seen.update(secondary)
    assert len(seen) >= 3, f"expected variety across 7 days, got {seen}"


def test_education_keeps_termin_tag():
    tags = system_tags_for("fallback_education", has_hamster=False, day_seed=date(2026, 5, 26))
    assert "#термин_без_боли" in tags


def test_flash_keeps_flash_tag():
    tags = system_tags_for("flash", has_hamster=True, day_seed=date(2026, 5, 26))
    assert "#flash" in tags
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_post_tags.py::test_secondary_tag_rotates_across_week -v`
Expected: FAIL — `system_tags_for() got unexpected keyword argument 'day_seed'`.

- [ ] **Step 4: Modify `core/post_tags.py:27-38`**

Replace `system_tags_for`:

```python
from datetime import date as _date

_ROTATING_TAGS = (
    "#не_будь_хомяком",
    "#ошибки_новичка",
    "#риск_менеджмент",
    "#дисциплина",
    "#термин_без_боли",
    "#психология_трейдинга",
)


def system_tags_for(
    post_type: str,
    *,
    has_hamster: bool,
    day_seed: _date | None = None,
) -> list[str]:
    """Системные теги: '#честный_путь' (всегда) + 1 ротируемый + type-specific.

    Ротация по day_seed.toordinal() % len(_ROTATING_TAGS). По умолчанию — today().
    has_hamster подсказывает, какой тег предпочтителен в этот день, но не диктует.
    """
    seed = day_seed or _date.today()
    tags = ["#честный_путь"]

    # Ротируемый тег. Если has_hamster — сдвигаем приоритет на хомяк-теги.
    rotation_pool = list(_ROTATING_TAGS)
    if not has_hamster:
        # убираем #не_будь_хомяком из ротации в постах без хомяка
        rotation_pool = [t for t in rotation_pool if t != "#не_будь_хомяком"]
    idx = seed.toordinal() % len(rotation_pool)
    tags.append(rotation_pool[idx])

    if post_type == "flash":
        tags.append("#flash")
    elif post_type == "fallback_education" and "#термин_без_боли" not in tags:
        tags.append("#термин_без_боли")

    return tags
```

- [ ] **Step 5: Update `merge_tags` to pass day_seed through**

In `core/post_tags.py:41-48`:

```python
def merge_tags(
    claude_tags: Iterable[str],
    *,
    post_type: str,
    has_hamster: bool,
    day_seed: _date | None = None,
) -> list[str]:
    """Финальный список тегов: claude_tags + system_tags (с ротацией)."""
    normalized = normalize_tags(claude_tags)
    system = system_tags_for(post_type, has_hamster=has_hamster, day_seed=day_seed)
    return list(dict.fromkeys(normalized + system))
```

- [ ] **Step 6: Run all post_tags tests**

Run: `pytest tests/test_post_tags.py -v`
Expected: PASS — both legacy and new tests green.

- [ ] **Step 7: Commit**

```bash
git add core/post_tags.py tests/test_post_tags.py
git commit -m "feat(rebranding-1.3): hashtag rotation pool, anchor=#честный_путь"
```

---

### Task 4: Claude prompt — sparingly use RSI/EMA in market posts

**Files:**
- Modify: bot.py — Claude system/user prompt for `market` flow

- [ ] **Step 1: Locate the market prompt**

Run: `grep -n "market_snapshot\|RSI\|EMA" bot.py | head -20`
Expected: shows where market snapshot is injected into Claude prompt. Read 30 lines around the match.

- [ ] **Step 2: Add the new instruction**

In the Claude system or user prompt for market posts (the block that says «You are AI mentor...» or «Вот market_snapshot...»), add this line as a separate paragraph:

```
ИСПОЛЬЗУЙ МЕТРИКИ СДЕРЖАННО: RSI, EMA, фандинг упоминай в тексте только если они существенны
для сегодняшнего наблюдения. Если рынок ровный — пиши про наблюдение и решение, а не про цифры.
Можно вообще обойтись без чисел, если они не двигают вывод.
```

(Точная формулировка — на русском, чтобы Claude в русскоязычном промпте её корректно подхватил.)

- [ ] **Step 3: Smoke test — generate one market post in DRY_RUN**

Run: `DRY_RUN=1 python bot.py --once --type market` (или эквивалентный smoke-runner проекта)

Expected: пост публикуется в DRY_RUN, текст лога не содержит ошибок. Глазом проверить — RSI/EMA НЕ в каждом абзаце.

- [ ] **Step 4: Commit**

```bash
git add bot.py
git commit -m "feat(rebranding-1.4): instruct Claude to use RSI/EMA sparingly in market posts"
```

---

### Task 5: Verify 3 consecutive posts have ≥2 different patterns (manual gate)

**Files:**
- Read-only check.

- [ ] **Step 1: Run health check**

Run: `python scripts/health_check.py --json`
Expected: exit 0, status ok.

- [ ] **Step 2: Trigger 3 DRY_RUN posts back-to-back**

Run: `DRY_RUN=1 python bot.py --once --type market` × 3, изменяя дату (через monkeypatch или env var, если поддерживается; иначе — 3 запуска подряд с искусственным сдвигом `date.today()`).

Если такой возможности нет — пропустить этот шаг и положиться на unit-тесты ротации; реальная проверка случится после первого реального дня публикаций.

- [ ] **Step 3: Manual visual diff**

Открой 3 сгенерированных текста рядом. Подтверди:
- Дисклеймеры разные ИЛИ дата прокручена так, что они должны быть разные.
- Хэштеги после `#честный_путь` отличаются.
- RSI/EMA НЕ во всех трёх в одинаковой форме.

- [ ] **Step 4: Tag the milestone**

```bash
git tag rebranding-stage1-complete
```

---

## Self-Review

**Spec coverage:**
- ✅ Pattern 2 (одинаковый дисклеймер) → Task 1+2.
- ✅ Pattern 5 (одинаковые хэштеги) → Task 3.
- ✅ Pattern 3 (RSI/EMA в каждом посте) → Task 4.
- ⚠️ Pattern 1 (жёсткая 4-секционная структура) → не в этом плане. Причина:
  структура C («короткая заметка») технически уже работает — `build_post_html` уже
  условно склеивает блоки. Достаточно инструкции Claude, чтобы он иногда возвращал
  payload без `mentor_part`/`mistake`. Это добавлено в Task 4 как часть промпта (см. ниже).
- ⚠️ Pattern 4 (хомяк всегда первым) → не в этом плане. Структура B (AI→хомяк) требует
  переставлять блоки в `build_post_html`, а это правка `_build_post_html_raw`+`build_post_html`
  одновременно (дубликат), что трогает поверхность 2.4-step9+ декомпозиции. Отложено.

**Дополнение к Task 4 для покрытия Pattern 1:**

В Step 2 Task 4 добавить ещё один параграф в промпт:

```
ВАРИАЦИЯ СТРУКТУРЫ: не каждый пост должен иметь все 4 блока (human → hamster → mentor → mistake → lesson).
Иногда возвращай только human_part (короткая заметка-наблюдение, 200-400 символов). Иногда —
human + lesson без хомяка. Цель — рынок не каждый день требует разбора эмоции; иногда хватает
наблюдения и вывода.
```

**Placeholder scan:** ни одного TBD/TODO/«similar to». Все шаги имеют либо точный код,
либо точные команды. ✅

**Type consistency:** `pick_disclaimer(post_type, *, day_seed)` — сигнатура одна и та же
в Task 1 и Task 2. `system_tags_for(post_type, *, has_hamster, day_seed=None)` — Task 3.
Везде `date | None`, kw-only после `*`. ✅

---

## Blockers Out of Scope

**Stage 2** (avatar generation + setChatPhoto + setChatDescription) — отдельный план,
будет написан после разблокировки image-API. Сейчас нет смысла планировать без
работающей генерации.

---

## Execution Handoff

**Plan complete and saved to** `docs/superpowers/plans/2026-05-26-deposit-ai-rebranding-stage1-plan.md`.

Выбираю **Inline Execution** — задачи маленькие (5 шт.), checkpoints естественные
(коммит после каждой). Subagent-driven избыточен для такого scope и
помешает быстро править если что-то не сработает.
