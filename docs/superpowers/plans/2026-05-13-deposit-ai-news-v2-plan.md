# Stage 14 — News redesign v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Привести новостные посты к компактному one-message формату (photo+caption ≤ 1024) с голосом новичка и ротацией тональностей, починить idempotency news-callbacks и диагностировать «кнопки не кликабельны».

**Architecture:** Большая часть v2-логики уже написана в `news/publisher.py` (`build_html_v2`, `validate_payload_v2`, `pick_tone`, `inject_mistake_theme`, `_truncate_post_to_caption_limit`, `news_format_version` flag). Этот план **закрывает gaps** к существующему коду: упрощает send-pipeline (без split), переделывает preview как 3 мини-сообщения, добавляет idempotency state guard, логирует callbacks для диагностики, переписывает `news_style_guide.md` под v2 schema, добавляет вынесенные хелперы (`normalize_payload_v2`, `merge_hashtags`, `final_caption_guard`).

**Tech Stack:** Python 3.14, aiogram 3 (Telegram), anthropic SDK, openai SDK, pytest для smoke. Никаких новых dependencies.

**Spec:** `docs/superpowers/specs/2026-05-13-deposit-ai-news-v2-design.md`

---

## File Structure

**Modify:**
- `news/publisher.py` — добавить `normalize_payload_v2`, `merge_hashtags`, `final_caption_guard`, вынести логику из `build_html_v2` (~630 lines → ~700 lines)
- `news/drafts.py` — добавить `schema_version` поле в NewsDraft если его ещё нет, добавить `publishing` status в перечисление
- `bot.py` — упростить `send_post_with_optional_image` (без split), переписать `_wrap_preview` flow на 3 мини-сообщения, добавить `cb.answer()` first + logging + state guard в news-callbacks (~5295 lines, touch ~150 строк)
- `news_style_guide.md` — переписать под v2 schema (currently 622 lines → ~400 lines, фокус на v2)
- `state.json` — добавить ключ `news_post_counter` (init 0; персистится между запусками)

**Create:**
- `tests/test_news_v2_smoke.py` — smoke-тесты caption length, ротация тонов, normalize_payload_v2, merge_hashtags

**Delete (dead code из v1):**
- `bot.py:_build_short_caption` (заменяется упрощённым send)
- `bot.py:PHOTO_CAPTION_SAFE_LIMIT` (заменяется `PHOTO_CAPTION_HARD_LIMIT = 1024`)
- `bot.py:_wrap_preview` (заменяется 3-message flow)
- `news/publisher.py:short_caption` (не используется в v2)

**Read-only (для контекста):**
- `news/analyzer.py` — Claude system prompt builder (использует style guide)
- `news/orchestrator.py` — news pipeline coordinator
- `style_guides.py` — loader для .md guides
- `mistake_themes.json`, `forbidden_words.json` — справочники

---

## Task 1: Baseline и страховка

**Files:**
- Backup: `news_drafts.json`, `news_style_guide.md`, `state.json`

- [ ] **Step 1.1: Снять backup**

```powershell
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$backupDir = "d:\Вайбкодинг\Тг новичок и ai наставник\backups\$ts"
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
Copy-Item "d:\Вайбкодинг\Тг новичок и ai наставник\news_drafts.json" $backupDir
Copy-Item "d:\Вайбкодинг\Тг новичок и ai наставник\news_style_guide.md" $backupDir
Copy-Item "d:\Вайбкодинг\Тг новичок и ai наставник\state.json" $backupDir
Write-Host "Backup at $backupDir"
```

Expected: 3 файла в backup-папке, путь напечатан.

- [ ] **Step 1.2: Зафиксировать текущее состояние v2 (что уже работает)**

```bash
cd "d:\Вайбкодинг\Тг новичок и ai наставник"
python -c "from news.config import NewsConfig; c = NewsConfig.from_env(); print(f'news_format_version={c.news_format_version}')"
```

Expected: `news_format_version=v2`

- [ ] **Step 1.3: Smoke-импорт всех модулей**

```bash
python -m py_compile bot.py news/publisher.py news/drafts.py news/analyzer.py news/orchestrator.py news/config.py
```

Expected: тишина (нет ошибок).

- [ ] **Step 1.4: Остановить scheduler перед правками**

```powershell
powershell -NoProfile -Command "Stop-ScheduledTask -TaskName DepositAiDiary; Get-ScheduledTask -TaskName DepositAiDiary | Select-Object TaskName,State"
```

Expected: `State : Ready` (не Running).

- [ ] **Step 1.5: Commit baseline (если репо git'овый)**

```bash
cd "d:\Вайбкодинг\Тг новичок и ai наставник"
git status
git add docs/superpowers/specs/2026-05-13-deposit-ai-news-v2-design.md docs/superpowers/plans/2026-05-13-deposit-ai-news-v2-plan.md
git commit -m "docs(news-v2): spec + implementation plan"
```

Если `git status` показывает не-git (no .git дир) — пропускаем коммит, идём дальше.

---

## Task 2: Вынести `merge_hashtags` в отдельную функцию

**Files:**
- Modify: `news/publisher.py` — выделить hashtag-логику из `build_html_v2`
- Test: `tests/test_news_v2_smoke.py` (создаём)

- [ ] **Step 2.1: Создать tests/test_news_v2_smoke.py с failing test для merge_hashtags**

Create file `tests/test_news_v2_smoke.py`:

```python
"""Stage 14 smoke tests for news v2 helpers."""

from news.publisher import merge_hashtags


def test_merge_hashtags_basic():
    """Базовый merge: rubric + claude_tags + assets, max 4."""
    result = merge_hashtags(
        claude_tags=["#DeFi", "#whitehat"],
        sector="security_hacks_scams",
        assets=["BTC"],
    )
    # rubric=#безопасность_депозита, asset=#BTC, claude=#DeFi,#whitehat → max 4
    assert result == ["#безопасность_депозита", "#BTC", "#DeFi", "#whitehat"]


def test_merge_hashtags_caps_at_4():
    """Max 4 даже если входов больше."""
    result = merge_hashtags(
        claude_tags=["#DeFi", "#whitehat", "#hack", "#audit", "#extra"],
        sector="security_hacks_scams",
        assets=["BTC", "ETH"],
    )
    assert len(result) == 4
    assert result[0] == "#безопасность_депозита"
    assert "#BTC" in result and "#ETH" in result


def test_merge_hashtags_dedupe_case_insensitive():
    """Дедупликация регистронезависимая, порядок сохраняется."""
    result = merge_hashtags(
        claude_tags=["#defi", "#DeFi", "#WhiteHat"],
        sector="security_hacks_scams",
        assets=[],
    )
    # rubric + #defi (первая встреченная) + #WhiteHat
    assert result == ["#безопасность_депозита", "#defi", "#WhiteHat"]


def test_merge_hashtags_no_rubric_no_assets():
    """Если sector неизвестен и нет assets — только claude_tags."""
    result = merge_hashtags(
        claude_tags=["#xyz", "#abc"],
        sector="unknown_sector",
        assets=[],
    )
    assert result == ["#xyz", "#abc"]


def test_merge_hashtags_ignores_non_btc_eth_assets():
    """Только BTC/ETH из assets идут в хэштеги."""
    result = merge_hashtags(
        claude_tags=["#meme"],
        sector="memecoins_low_priority",
        assets=["DOGE", "PEPE", "BTC"],
    )
    # rubric + #BTC + #meme
    assert "#BTC" in result
    assert "#DOGE" not in result
    assert "#PEPE" not in result
```

- [ ] **Step 2.2: Run failing test**

Run:
```bash
cd "d:\Вайбкодинг\Тг новичок и ai наставник"
python -m pytest tests/test_news_v2_smoke.py -v
```

Expected: FAIL с `ImportError: cannot import name 'merge_hashtags' from 'news.publisher'`

- [ ] **Step 2.3: Добавить функцию `merge_hashtags` в `news/publisher.py`**

В `news/publisher.py` после функции `image_prompt_for` (примерно строка 312) добавить:

```python
def merge_hashtags(claude_tags: list[str], sector: str, assets: list[str]) -> list[str]:
    """Stage 14 — мерж хэштегов для v2 поста, max 4.

    Порядок:
    1. Sector rubric (из SECTOR_RUBRIC) — всегда первый, 1 слот
    2. Asset tags (#BTC, #ETH) из assets[:2] — макс 2 слота
    3. Claude thematic tags — добивают до total ≤ 4
    4. Дедупликация регистронезависимая с сохранением порядка
    """
    tags: list[str] = []

    rubric = SECTOR_RUBRIC.get(sector, "")
    if rubric:
        tags.append(rubric)

    for a in (assets or [])[:2]:
        if a in ("BTC", "ETH"):
            tags.append(f"#{a}")

    for t in (claude_tags or []):
        t = str(t).strip()
        if not t:
            continue
        if not t.startswith("#"):
            t = f"#{t}"
        tags.append(t)

    # Дедупликация регистронезависимая с сохранением порядка
    seen: set[str] = set()
    unique: list[str] = []
    for t in tags:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            unique.append(t)

    return unique[:4]
```

- [ ] **Step 2.4: Run tests — все 5 должны PASS**

Run:
```bash
python -m pytest tests/test_news_v2_smoke.py::test_merge_hashtags_basic tests/test_news_v2_smoke.py::test_merge_hashtags_caps_at_4 tests/test_news_v2_smoke.py::test_merge_hashtags_dedupe_case_insensitive tests/test_news_v2_smoke.py::test_merge_hashtags_no_rubric_no_assets tests/test_news_v2_smoke.py::test_merge_hashtags_ignores_non_btc_eth_assets -v
```

Expected: 5 passed.

- [ ] **Step 2.5: Заменить inline-логику в `build_html_v2` на вызов `merge_hashtags`**

В `news/publisher.py` найти в `build_html_v2` блок:

```python
    # Хэштеги: секторная рубрика + тематические от Claude + активы. Макс 4.
    raw_tags = payload.get("hashtags") or []
    tags: list[str] = [str(t).strip() for t in raw_tags if t and str(t).strip()]
    tags = [t if t.startswith("#") else f"#{t}" for t in tags]
    if rubric and rubric not in tags:
        tags.insert(0, rubric)
    for a in item.assets[:2]:
        if a in ("BTC", "ETH"):
            tag = f"#{a}"
            if tag not in tags:
                tags.append(tag)
    # Дедупликация с сохранением порядка, макс 4
    seen: set[str] = set()
    unique: list[str] = []
    for t in tags:
        if t.lower() not in seen:
            seen.add(t.lower())
            unique.append(t)
    tags = unique[:4]
```

Заменить на:

```python
    tags = merge_hashtags(
        claude_tags=payload.get("hashtags") or [],
        sector=sector,
        assets=item.assets or [],
    )
```

- [ ] **Step 2.6: Run pytest снова — ничего не должно сломаться**

```bash
python -m pytest tests/test_news_v2_smoke.py -v
```

Expected: 5 passed.

- [ ] **Step 2.7: Commit**

```bash
git add news/publisher.py tests/test_news_v2_smoke.py
git commit -m "refactor(news-v2): extract merge_hashtags helper from build_html_v2"
```

(Если не git — пропускаем.)

---

## Task 3: `normalize_payload_v2` — единая точка fallback'ов

**Files:**
- Modify: `news/publisher.py`
- Test: `tests/test_news_v2_smoke.py`

- [ ] **Step 3.1: Failing test для normalize_payload_v2**

В `tests/test_news_v2_smoke.py` добавить:

```python
from news.publisher import normalize_payload_v2, SECTOR_EMOJI_FALLBACK
from news.models import NewsItem


def _make_item(sector="ai_crypto", title="test", url="https://example.com/x"):
    return NewsItem(
        title=title, url=url, source="src", published_at="",
        summary="", assets=[], category="other", sector=sector,
        impact_score=80.0,
    )


def test_normalize_fills_title_emoji_from_sector():
    """Если Claude не дал title_emoji — берём из SECTOR_EMOJI_FALLBACK."""
    payload = {
        "should_publish": True,
        "specific_title": "Some title",
        "lead": "x" * 100,
        "facts": ["a" * 50, "b" * 50, "c" * 50],
        "newbie_voice": "y" * 50,
        "tone": "calm",
    }
    item = _make_item(sector="ai_crypto")
    normalized = normalize_payload_v2(payload, item)
    assert normalized["title_emoji"] == SECTOR_EMOJI_FALLBACK["ai_crypto"]


def test_normalize_keeps_explicit_emoji():
    """Если title_emoji уже задан Claude — не перезаписываем."""
    payload = {
        "should_publish": True,
        "specific_title": "Some title",
        "title_emoji": "🎯",
        "lead": "x" * 100,
        "facts": ["a" * 50, "b" * 50, "c" * 50],
        "newbie_voice": "y" * 50,
        "tone": "harsh",
    }
    item = _make_item(sector="security_hacks_scams")
    normalized = normalize_payload_v2(payload, item)
    assert normalized["title_emoji"] == "🎯"


def test_normalize_fixes_invalid_tone():
    """Если tone не из enum — заменяем на pick_tone."""
    payload = {
        "should_publish": True,
        "specific_title": "Some title",
        "lead": "x" * 100,
        "facts": ["a" * 50, "b" * 50, "c" * 50],
        "newbie_voice": "y" * 50,
        "tone": "weird_unknown_tone",
    }
    item = _make_item(sector="security_hacks_scams")
    normalized = normalize_payload_v2(payload, item)
    assert normalized["tone"] in ("harsh", "confused", "ironic", "calm")


def test_normalize_does_not_mutate_input():
    """normalize возвращает новый dict, не трогает входной."""
    payload = {"should_publish": True, "tone": "invalid"}
    item = _make_item()
    original = dict(payload)
    normalize_payload_v2(payload, item)
    assert payload == original
```

- [ ] **Step 3.2: Run failing test**

Run:
```bash
python -m pytest tests/test_news_v2_smoke.py -v -k normalize
```

Expected: FAIL с `cannot import name 'normalize_payload_v2'`.

- [ ] **Step 3.3: Добавить `normalize_payload_v2` в `news/publisher.py`**

В `news/publisher.py` после функции `pick_tone` (примерно строка 232) добавить:

```python
def normalize_payload_v2(payload: dict, item: "NewsItem", revision_count: int = 0) -> dict:
    """Stage 14 — единая точка fallback-логики для v2 payload.

    Возвращает новый dict (вход не модифицируется):
    - title_emoji: если пусто → SECTOR_EMOJI_FALLBACK[sector]
    - tone: если не из enum → pick_tone(item, revision_count)
    - facts: cleanup whitespace и фильтр пустых строк
    - hashtags: применяем merge_hashtags (rubric + assets + claude)

    Validate_payload_v2 уже отбил «совсем дырявый» payload, эта функция
    приводит остаток к каноничному виду перед renderer'ом.
    """
    p = dict(payload)
    sector = (item.sector or "other").strip()

    emoji = str(p.get("title_emoji") or "").strip()
    if not emoji:
        p["title_emoji"] = SECTOR_EMOJI_FALLBACK.get(sector, "🗒️")

    tone = str(p.get("tone") or "").strip().lower()
    if tone not in ("harsh", "confused", "ironic", "calm"):
        p["tone"] = pick_tone(item, revision_count)
    else:
        p["tone"] = tone

    facts_raw = _safe_list(p.get("facts"))
    p["facts"] = [str(f).strip() for f in facts_raw if str(f).strip()]

    p["hashtags"] = merge_hashtags(
        claude_tags=p.get("hashtags") or [],
        sector=sector,
        assets=item.assets or [],
    )

    return p
```

- [ ] **Step 3.4: Убедиться, что `SECTOR_EMOJI_FALLBACK` определён**

Проверить (Grep):
```bash
grep -n "SECTOR_EMOJI_FALLBACK" "d:\Вайбкодинг\Тг новичок и ai наставник\news\publisher.py"
```

Если константы нет — добавить около `SECTOR_RUBRIC` в начале файла:

```python
# Stage 14 — fallback эмодзи для title по сектору, если Claude не дал title_emoji
SECTOR_EMOJI_FALLBACK: dict[str, str] = {
    "ai_crypto":                     "🤖",
    "regulation_etf_institutional":  "🏛️",
    "macro":                         "🌍",
    "stablecoins":                   "💵",
    "security_hacks_scams":          "⚠️",
    "scam_radar":                    "🕵️",
    "rwa_tokenization":              "🏗️",
    "depin_infrastructure":          "🏗️",
    "defi_restaking":                "🔁",
    "l2_scaling":                    "🧱",
    "political_market_noise":        "🧨",
    "memecoins_low_priority":        "🎪",
}
```

- [ ] **Step 3.5: Run tests**

```bash
python -m pytest tests/test_news_v2_smoke.py -v
```

Expected: все passed (9+).

- [ ] **Step 3.6: Подключить normalize_payload_v2 в `NewsPublisher.publish`**

В `news/publisher.py` найти в `publish()`:

```python
        if use_v2:
            text = build_html_v2(claude_payload, item)
            guard_reasons = validate_payload_v2(claude_payload, item)
```

Заменить на:

```python
        if use_v2:
            guard_reasons = validate_payload_v2(claude_payload, item)
            normalized_payload = normalize_payload_v2(claude_payload, item)
            text = build_html_v2(normalized_payload, item)
```

И ниже, в truncate-блоке:

```python
        if use_v2:
            truncated = _truncate_post_to_caption_limit(text, claude_payload, item)
```

Заменить на:

```python
        if use_v2:
            truncated = _truncate_post_to_caption_limit(text, normalized_payload, item)
```

- [ ] **Step 3.7: Smoke — компилируется и build_html_v2 даёт ожидаемый emoji-fallback**

```bash
python -c "
from news.publisher import normalize_payload_v2, build_html_v2, SECTOR_EMOJI_FALLBACK
from news.models import NewsItem
item = NewsItem(title='t', url='https://x.com/y', source='X', published_at='', summary='', assets=[], category='other', sector='security_hacks_scams', impact_score=80.0)
payload = {'should_publish': True, 'specific_title': 'Test Title', 'lead': 'lead text here ' * 5, 'facts': ['fact1 '*8, 'fact2 '*8, 'fact3 '*8], 'newbie_voice': 'newbie text ' * 5, 'tone': 'harsh', 'hashtags': ['#DeFi']}
n = normalize_payload_v2(payload, item)
print('title_emoji:', n['title_emoji'])
print('hashtags:', n['hashtags'])
html = build_html_v2(n, item)
print('html len:', len(html))
print('contains rubric:', '#безопасность_депозита' in html)
"
```

Expected:
```
title_emoji: ⚠️
hashtags: ['#безопасность_депозита', '#DeFi']
html len: <число ≤ 1024>
contains rubric: True
```

- [ ] **Step 3.8: Commit**

```bash
git add news/publisher.py tests/test_news_v2_smoke.py
git commit -m "feat(news-v2): normalize_payload_v2 — единая точка fallback-логики"
```

---

## Task 4: `final_caption_guard` и упрощение `send_post_with_optional_image`

**Files:**
- Modify: `news/publisher.py` (add final_caption_guard)
- Modify: `bot.py` — упростить send (без split), удалить `_build_short_caption`
- Test: `tests/test_news_v2_smoke.py`

- [ ] **Step 4.1: Failing test для final_caption_guard**

В `tests/test_news_v2_smoke.py` добавить:

```python
from news.publisher import final_caption_guard


def test_final_caption_guard_passes_valid():
    html = "<b>Title</b>\n\nLead text\n\n➤ fact"
    ok, reason = final_caption_guard(html)
    assert ok is True
    assert reason == ""


def test_final_caption_guard_rejects_over_limit():
    html = "x" * 1100
    ok, reason = final_caption_guard(html)
    assert ok is False
    assert "1024" in reason


def test_final_caption_guard_rejects_broken_html_tag():
    # Незакрытый тег <b>
    html = "<b>Title without closing"
    ok, reason = final_caption_guard(html)
    assert ok is False
    assert "html" in reason.lower() or "tag" in reason.lower()
```

- [ ] **Step 4.2: Run failing test**

```bash
python -m pytest tests/test_news_v2_smoke.py -v -k final_caption
```

Expected: FAIL.

- [ ] **Step 4.3: Добавить final_caption_guard в news/publisher.py**

В `news/publisher.py` после `_truncate_post_to_caption_limit` добавить:

```python
def final_caption_guard(html: str) -> tuple[bool, str]:
    """Stage 14 — финальная проверка caption ПЕРЕД send_photo.

    Проверяет ТОЛЬКО caption safety:
    - len(html) ≤ PHOTO_CAPTION_HARD_LIMIT (1024)
    - простая валидация HTML тегов (открытые/закрытые)

    Не проверяет Claude schema — это уже сделал validate_payload_v2 раньше
    в pipeline. После truncate содержимое может не соответствовать schema
    (например lead = 1 фраза), но это валидный пост.

    Returns (ok, reason). При ok=True reason пустой.
    """
    if not isinstance(html, str):
        return False, "html не строка"
    if len(html) > PHOTO_CAPTION_HARD_LIMIT:
        return False, f"caption {len(html)} > {PHOTO_CAPTION_HARD_LIMIT} chars"

    # Простая проверка балансировки <b>, <i>, <a>
    import re as _re
    for tag in ("b", "i"):
        opens = len(_re.findall(rf"<{tag}>", html))
        closes = len(_re.findall(rf"</{tag}>", html))
        if opens != closes:
            return False, f"broken html: <{tag}> opens={opens} closes={closes}"

    a_opens = len(_re.findall(r"<a\s+href=", html))
    a_closes = len(_re.findall(r"</a>", html))
    if a_opens != a_closes:
        return False, f"broken html: <a> opens={a_opens} closes={a_closes}"

    return True, ""
```

- [ ] **Step 4.4: Run tests — все должны PASS**

```bash
python -m pytest tests/test_news_v2_smoke.py -v
```

Expected: passed.

- [ ] **Step 4.5: Применить final_caption_guard в `NewsPublisher.publish`**

В `news/publisher.py` найти в `publish()` после `text = truncated`:

```python
            text = truncated
```

Добавить сразу после:

```python
            text = truncated
            # final caption guard — проверяем только caption safety
            ok, reason = final_caption_guard(text)
            if not ok:
                log.error("final_caption_guard failed for %r: %s", item.title[:80], reason)
                if self.cfg.news_send_to_owner and self.owner_chat_id:
                    try:
                        await self.send(
                            self.owner_chat_id,
                            f"⚠️ <b>Caption guard заблокировал публикацию</b>\n\n"
                            f"<i>{_e(item.title[:200])}</i>\n\n"
                            f"причина: {_e(reason)}",
                            None,
                        )
                    except Exception:
                        pass
                self.dedup.remember(item, "skipped", short_summary=f"caption guard: {reason}")
                return "skipped"
```

- [ ] **Step 4.6: Упростить `send_post_with_optional_image` в bot.py**

В `bot.py` найти `send_post_with_optional_image` (примерно строка 4201). Заменить тело функции (строки 4222-4270) на:

```python
    """Универсальная отправка post + optional image (Stage 14).

    Использует:
    - send_message — если image_path пустой / файла нет.
    - send_photo с full caption — если image_path есть.

    Stage 14: split-режим (photo + отдельный текст) удалён. Caption
    должен быть ≤ 1024 chars; за это отвечает upstream (truncate cascade
    + final_caption_guard в NewsPublisher.publish или caption-fit в market posts).
    Если caption > 1024 — это баг upstream, упадёт с TelegramBadRequest.
    """
    if not chat_id:
        log.warning("send_post: chat_id пустой, skip")
        return

    img: Optional[Path] = None
    if image_path:
        try:
            cand = Path(image_path)
            if cand.exists():
                img = cand
            else:
                log.warning("post image_path не существует: %s — шлю без фото", image_path)
        except Exception as e:
            log.warning("post image_path bad: %s (%s)", image_path, e)

    if img is None:
        await bot.send_message(
            chat_id, post_html,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
            reply_markup=reply_markup,
        )
        return

    photo = FSInputFile(str(img))
    await bot.send_photo(
        chat_id, photo,
        caption=post_html,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
    )
```

- [ ] **Step 4.7: Удалить `_build_short_caption` и `PHOTO_CAPTION_SAFE_LIMIT` из bot.py**

В `bot.py` найти и удалить:
- константу `PHOTO_CAPTION_SAFE_LIMIT = 1000` (строка ~4139)
- функцию `_build_short_caption` целиком (примерно строки 4149-4198)
- функцию `_strip_html_tags` если она нигде больше не используется (Grep `_strip_html_tags` перед удалением — может быть нужна для legacy)

Проверка перед удалением `_strip_html_tags`:
```bash
grep -n "_strip_html_tags" "d:\Вайбкодинг\Тг новичок и ai наставник\bot.py"
```

Если только в self-определении и `_build_short_caption` — удалить обе. Если используется ещё где-то — оставить.

- [ ] **Step 4.8: Smoke import**

```bash
python -m py_compile bot.py
```

Expected: тишина.

- [ ] **Step 4.9: Commit**

```bash
git add bot.py news/publisher.py tests/test_news_v2_smoke.py
git commit -m "refactor(news-v2): final_caption_guard + simplified single-message send"
```

---

## Task 5: news_post_counter — персистентность в state.json

**Files:**
- Modify: `bot.py` — добавить helpers `_state_get_news_post_counter` / `_state_set_news_post_counter`
- Modify: `news/publisher.py` — `NewsPublisher` принимает counter getter/setter callable вместо int

- [ ] **Step 5.1: Проверить текущее использование `news_post_counter`**

```bash
grep -n "news_post_counter" "d:\Вайбкодинг\Тг новичок и ai наставник\bot.py" "d:\Вайбкодинг\Тг новичок и ai наставник\news\publisher.py"
```

Ожидаем найти: `news/publisher.py` где-то в `NewsPublisher.__init__` и `publish()`.

- [ ] **Step 5.2: Добавить state helpers в bot.py**

В `bot.py` найти `_state_get_awaiting_news_edit` (около строки 3073). Сразу после неё добавить:

```python
def _state_get_news_post_counter() -> int:
    """Stage 14 — счётчик опубликованных в канал news-постов (для mistake_theme inject)."""
    s = _read_state()
    try:
        return int(s.get("news_post_counter") or 0)
    except (TypeError, ValueError):
        return 0


def _state_set_news_post_counter(value: int) -> None:
    """Stage 14 — set news_post_counter в state.json."""
    s = _read_state()
    s["news_post_counter"] = int(value)
    _write_state(s)


def _state_inc_news_post_counter() -> int:
    """Stage 14 — atomic increment (in-process), возвращает новое значение."""
    s = _read_state()
    cur = int(s.get("news_post_counter") or 0)
    s["news_post_counter"] = cur + 1
    _write_state(s)
    return cur + 1
```

Если `_read_state`/`_write_state` имеют другие имена — посмотреть существующие helpers (Grep `_state_get_awaiting`) и использовать ту же сигнатуру.

- [ ] **Step 5.3: Модифицировать `NewsPublisher` чтобы читать counter из callable**

В `news/publisher.py` найти `class NewsPublisher` и `__init__`. Добавить параметры:

```python
        # Stage 14 — counter getter (lambda) вместо int, чтобы персистенция
        # делалась на стороне bot.py через state.json
        counter_get: Optional[Callable[[], int]] = None,
        counter_inc: Optional[Callable[[], int]] = None,
```

Сохранить:
```python
        self._counter_get = counter_get
        self._counter_inc = counter_inc
        # legacy backward-compat: если callable'ы не переданы, fallback на int
        if counter_get is None:
            self._counter_value = news_post_counter
```

В `publish()` заменить:
```python
self.news_post_counter += 1
```
на:
```python
if self._counter_inc:
    new_value = self._counter_inc()
else:
    self._counter_value += 1
    new_value = self._counter_value
```

И при чтении counter (для inject_mistake_theme):
```python
counter = self._counter_get() if self._counter_get else self._counter_value
```

- [ ] **Step 5.4: Подключить counter callable в bot.py при создании NewsPublisher**

Найти в `bot.py` где создаётся `NewsPublisher`. Это, вероятно, в `run_news_now_cmd` или в scheduler-setup. Grep:

```bash
grep -n "NewsPublisher(" "d:\Вайбкодинг\Тг новичок и ai наставник\bot.py"
```

В каждом месте создания добавить параметры:

```python
NewsPublisher(
    ...,
    counter_get=_state_get_news_post_counter,
    counter_inc=_state_inc_news_post_counter,
)
```

- [ ] **Step 5.5: Smoke import**

```bash
python -m py_compile bot.py news/publisher.py
```

Expected: тишина.

- [ ] **Step 5.6: Тест что counter увеличивается между двумя успешными публикациями**

В `tests/test_news_v2_smoke.py` добавить:

```python
def test_state_news_post_counter_helpers(tmp_path, monkeypatch):
    """Smoke: counter persistence через state.json helpers."""
    import sys
    sys.path.insert(0, "d:\\Вайбкодинг\\Тг новичок и ai наставник")
    # Используем tmp state.json
    state_file = tmp_path / "state.json"
    state_file.write_text("{}")
    # Мокаем глобальный путь state.json
    import bot as bot_module
    monkeypatch.setattr(bot_module, "STATE_FILE", state_file)
    # Reset
    assert bot_module._state_get_news_post_counter() == 0
    # Inc 3 раза
    bot_module._state_inc_news_post_counter()
    bot_module._state_inc_news_post_counter()
    bot_module._state_inc_news_post_counter()
    assert bot_module._state_get_news_post_counter() == 3
    # Set
    bot_module._state_set_news_post_counter(10)
    assert bot_module._state_get_news_post_counter() == 10
```

Run:
```bash
python -m pytest tests/test_news_v2_smoke.py::test_state_news_post_counter_helpers -v
```

Expected: passed.

- [ ] **Step 5.7: Commit**

```bash
git add bot.py news/publisher.py tests/test_news_v2_smoke.py
git commit -m "feat(news-v2): persist news_post_counter в state.json"
```

---

## Task 6: Idempotency status `publishing` + state guard в news-callbacks

**Files:**
- Modify: `news/drafts.py` — добавить `publishing` в перечисление статусов (docstring)
- Modify: `bot.py` — обновить все 6 news-callback'ов

- [ ] **Step 6.1: Найти все news-callbacks**

```bash
grep -n "@dp.callback_query.*news_" "d:\Вайбкодинг\Тг новичок и ai наставник\bot.py"
```

Ожидаем 6 callbacks:
- `news_publish:`
- `news_edit:`
- `news_regenerate:`
- `news_reject:`
- `news_generate_ai_image:`
- `news_refresh_source_image:`

- [ ] **Step 6.2: Обновить docstring в news/drafts.py**

В `news/drafts.py` найти класс `NewsDraft` и его docstring (если есть) или комментарий в начале файла. Добавить:

```python
"""Stage 6b — News review / approval drafts.

draft.status:
    pending_review — ждёт решения владельца
    revised        — после правки/регенерации, ждёт решения снова
    publishing     — Stage 14: in-flight публикация в канал (idempotency guard)
    approved       — нажат ✅, но публикация заблокирована флагами
    published      — успешно отправлено в канал
    rejected       — владелец нажал ❌ Отклонить
"""
```

- [ ] **Step 6.3: Обновить `on_news_publish` — `cb.answer()` first + logging + state guard**

В `bot.py` найти `on_news_publish` (около строки 3481). Заменить тело функции с самого начала:

```python
    @dp.callback_query(F.data.startswith("news_publish:"))
    async def on_news_publish(cb: CallbackQuery):
        log.info(
            "CB news_publish: from=%s data=%s msg_id=%s",
            cb.from_user.id if cb.from_user else "?",
            cb.data,
            cb.message.message_id if cb.message else "?",
        )
        await cb.answer()  # Stage 14: ack СРАЗУ, до тяжёлой логики
        if not await _is_owner_cb(cb):
            log.warning(
                "CB news_publish: not owner (from=%s expected=%s)",
                cb.from_user.id if cb.from_user else "?",
                OWNER_CHAT_ID,
            )
            return
        draft_id = cb.data.split(":", 1)[1]
        store = _store()
        draft = store.get(draft_id)
        if not draft:
            await cb.answer("Черновик не найден", show_alert=True)
            return

        # Stage 14 idempotency guard — terminal states + publishing
        TERMINAL = {"published", "rejected", "publishing"}
        if draft.status in TERMINAL:
            await cb.answer(f"Уже обработано ({draft.status})", show_alert=True)
            try:
                await cb.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            return

        # Переводим в publishing СРАЗУ, чтобы второй клик увидел terminal
        draft.status = "publishing"
        store.update(draft)

        reasons = _publish_guard_reasons()
        # ... (остальная логика как была) ...
```

Найти места где `draft.status = "published"` после успешного `send`. После них всё работает (статус уже "publishing", переводим в "published"). А ВОТ в `except Exception` после `send to channel failed` нужно откатить:

```python
        except Exception as e:
            log.exception("news_publish: send to channel failed: %s", e)
            # Откат idempotency — позволяем владельцу повторить
            draft.status = "pending_review"
            store.update(draft)
            try:
                await _send_dm_html(cb.bot, f"❌ Ошибка публикации в канал: {html.escape(str(e), quote=False)}")
            except Exception:
                pass
            return
```

- [ ] **Step 6.4: Аналогичные правки для остальных 5 callbacks**

Для каждого из:
- `on_news_edit`
- `on_news_regenerate`
- `on_news_reject`
- `on_news_generate_ai_image`
- `on_news_refresh_source_image`

Применить шаблон:

```python
    @dp.callback_query(F.data.startswith("news_XXX:"))
    async def on_news_XXX(cb: CallbackQuery):
        log.info(
            "CB news_XXX: from=%s data=%s msg_id=%s",
            cb.from_user.id if cb.from_user else "?",
            cb.data,
            cb.message.message_id if cb.message else "?",
        )
        await cb.answer()   # ack first
        if not await _is_owner_cb(cb):
            log.warning(
                "CB news_XXX: not owner (from=%s expected=%s)",
                cb.from_user.id if cb.from_user else "?",
                OWNER_CHAT_ID,
            )
            return
        # ... остальная логика (но проверка terminal должна оставаться через draft.status)
```

Для `on_news_reject` — после успешного перевода в `rejected`:
```python
        draft.status = "rejected"
        store.update(draft)
```

Для `edit`, `regenerate`, `generate_ai_image`, `refresh_source_image` — статус НЕ меняется на terminal (это не финальные действия), но логирование и `cb.answer()` first обязательны.

- [ ] **Step 6.5: Smoke import**

```bash
python -m py_compile bot.py
```

Expected: тишина.

- [ ] **Step 6.6: Commit**

```bash
git add bot.py news/drafts.py
git commit -m "feat(news-v2): idempotency state guard 'publishing' + structured callback logging"
```

---

## Task 7: `should_publish=false` — info DM без кнопок

**Files:**
- Modify: `news/publisher.py` — `publish()` для случая Claude вернул `should_publish=false`

- [ ] **Step 7.1: Проверить текущее поведение**

В `news/publisher.py` в `publish()` найти:

```python
        if not claude_payload.get("should_publish"):
            self.dedup.remember(item, "claude_rejected", short_summary=short_summary)
            return "claude_rejected"
```

Сейчас публикация скипается тихо. Нужно добавить info DM владельцу.

- [ ] **Step 7.2: Заменить block на info-DM версию**

Заменить на:

```python
        if not claude_payload.get("should_publish"):
            self.dedup.remember(item, "claude_rejected", short_summary=short_summary)
            # Stage 14: info DM владельцу без кнопок (это инфо, действий не требуется)
            if self.cfg.news_send_to_owner and self.owner_chat_id:
                skip_reason = str(claude_payload.get("skip_reason") or "").strip()
                if not skip_reason:
                    skip_reason = "(без причины от Claude)"
                title_short = item.title[:80] if item.title else "(no title)"
                try:
                    await self.send(
                        self.owner_chat_id,
                        f"🔕 <b>Скипнул новость</b>\n\n"
                        f"<i>{_e(title_short)}</i>\n\n"
                        f"причина: {_e(skip_reason)}",
                        None,
                    )
                except Exception as e:
                    log.warning("should_publish=false info DM failed: %s", e)
            return "claude_rejected"
```

- [ ] **Step 7.3: Smoke import + manual test**

```bash
python -m py_compile news/publisher.py
```

Expected: тишина.

- [ ] **Step 7.4: Commit**

```bash
git add news/publisher.py
git commit -m "feat(news-v2): info DM при should_publish=false"
```

---

## Task 8: Preview-сообщение владельцу — 3 мини вместо HTML-header

**Files:**
- Modify: `news/publisher.py` — переписать `_wrap_preview` или удалить
- Modify: `bot.py` — `_news_preview_send` шлёт 3 сообщения

- [ ] **Step 8.1: Прочитать текущий `_wrap_preview` и `_news_preview_send`**

```bash
grep -n "_wrap_preview\|_news_preview_send" "d:\Вайбкодинг\Тг новичок и ai наставник\news\publisher.py" "d:\Вайбкодинг\Тг новичок и ai наставник\bot.py"
```

- [ ] **Step 8.2: Переделать `NewsPublisher.publish()` чтобы шапка шла отдельным сообщением**

В `news/publisher.py` найти блок где создаётся draft и шлётся preview:

```python
            draft = create_draft_from(...)
            self.draft_store.add(draft)
            preview = self._wrap_preview(text, draft.draft_id, item, guard_reasons)
            await self.preview_send(preview, review_keyboard(draft.draft_id), image_path)
            self.dedup.remember(item, "pending_review", short_summary=short_summary)
            return "preview_sent"
```

Заменить на:

```python
            draft = create_draft_from(
                claude_payload, item, text,
                image_path=image_path,
                guard_reasons=guard_reasons,
                image_origin=image_origin,
                image_source_url=image_source_url,
                image_credit=image_credit,
                image_prompt=image_prompt,
                image_model=image_model,
                image_created_at=image_created_at,
            )
            self.draft_store.add(draft)

            # Stage 14: превью = 3 сообщения (шапка + опц.guard + сам пост c кнопками)
            # Шапка идёт через preview_send_header (callable из bot.py)
            sector = item.sector or "-"
            impact = int(item.impact_score)
            tone = str((claude_payload if not use_v2 else normalized_payload).get("tone") or "-")
            header_text = (
                f"🧪 Превью #{html.escape(draft.draft_id[:8])} · "
                f"sector={html.escape(sector)} · impact={impact} · tone={html.escape(tone)}"
            )
            await self.preview_send(
                header_text,
                None,         # no inline keyboard on header
                None,         # no image on header
            )
            if guard_reasons:
                guard_text = "🚫 <b>Publish-guard заблокировал автопубликацию:</b>\n" + "\n".join(
                    f"• {html.escape(r, quote=False)}" for r in guard_reasons[:6]
                )
                await self.preview_send(guard_text, None, None)

            # Сам пост — точно как в канал, с кнопками
            await self.preview_send(text, review_keyboard(draft.draft_id), image_path)

            self.dedup.remember(item, "pending_review", short_summary=short_summary)
            return "preview_sent"
```

- [ ] **Step 8.3: Расширить `_news_preview_send` в bot.py чтобы он принимал None как kb_dict**

В `bot.py` найти `_news_preview_send`. Текущая реализация принимает `kb_dict: dict`. Изменить на:

```python
async def _news_preview_send(
    bot: Bot,
    text: str,
    kb_dict: Optional[dict] = None,
    image_path: Optional[str] = None,
) -> None:
    """Адаптер под NewsPublisher.PreviewSendFn — превью владельцу.

    Stage 14: если kb_dict=None, шлём без кнопок (для мини-сообщений: header / guard).
    Если image_path=None и kb_dict=None — просто send_message.
    """
    if not OWNER_CHAT_ID:
        log.warning("news preview: OWNER_CHAT_ID не задан, skip")
        return
    keyboard = _keyboard_from_dict(kb_dict) if kb_dict else None
    await send_post_with_optional_image(
        bot, OWNER_CHAT_ID, text, image_path,
        reply_markup=keyboard,
    )
```

- [ ] **Step 8.4: Обновить typing в news/publisher.py:`PreviewSendFn`**

В `news/publisher.py` найти:

```python
PreviewSendFn = Callable[[str, dict, Optional[str]], Awaitable[None]]
```

Заменить на:

```python
PreviewSendFn = Callable[[str, Optional[dict], Optional[str]], Awaitable[None]]
# (html_text, optional_inline_keyboard_dict, optional_image_path) -> await
```

- [ ] **Step 8.5: Удалить `_wrap_preview` (если он остался)**

```bash
grep -n "_wrap_preview" "d:\Вайбкодинг\Тг новичок и ai наставник\news\publisher.py"
```

Если найдено — удалить эту функцию.

- [ ] **Step 8.6: Smoke import**

```bash
python -m py_compile bot.py news/publisher.py
```

Expected: тишина.

- [ ] **Step 8.7: Commit**

```bash
git add bot.py news/publisher.py
git commit -m "feat(news-v2): preview = 3 messages (header + opt.guard + post)"
```

---

## Task 9: Переписать `news_style_guide.md` под v2 schema

**Files:**
- Rewrite: `news_style_guide.md` (622 lines → ~400 lines)

- [ ] **Step 9.1: Бэкап существующего guide**

```powershell
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
Copy-Item "d:\Вайбкодинг\Тг новичок и ai наставник\news_style_guide.md" "d:\Вайбкодинг\Тг новичок и ai наставник\news_style_guide.v1.bak.$ts.md"
```

- [ ] **Step 9.2: Прочитать первые 50 строк существующего guide для понимания структуры**

```bash
head -50 "d:\Вайбкодинг\Тг новичок и ai наставник\news_style_guide.md"
```

- [ ] **Step 9.3: Переписать news_style_guide.md полностью под v2**

Перезаписать содержимое файла полностью на новый текст (см. ниже). Файл — это system-prompt suffix для Claude. ВАЖНО: голос, тональности, JSON schema.

Использовать Write tool с этим содержимым (~400 строк markdown):

```markdown
# News style guide v2 — компактный пост одним сообщением

## Концепция канала

«Дневник трейдера-новичка» — единственный голос. Никакого «AI-наставника» в каждом посте: персонаж новичка достаточно живой сам по себе. Канал — про обучение через личный опыт наблюдения, не про экспертные комментарии.

## JSON schema v2 (обязательные поля)

```json
{
  "should_publish": true,
  "specific_title": "Взломал и вернул: Renegade отдали $190K",
  "title_emoji": "🤝",
  "lead": "Whitehat нашёл дыру в DeFi-протоколе Renegade, вывел $190K и через пару часов вернул всё обратно.",
  "facts": [
    "Уязвимость была реальной, не «теоретической».",
    "Деньги вернул один человек, а не сам протокол.",
    "Если придёт blackhat — никто не вернёт."
  ],
  "newbie_voice": "«Всё ок, деньги на месте» — худший вывод из такой новости.",
  "tone": "harsh",
  "hashtags": ["#DeFi", "#whitehat"]
}
```

### Поля

| Поле | Тип | Лимит | Обязательно |
|---|---|---|---|
| should_publish | bool | — | да |
| specific_title | str | 12-80 chars, не из blacklist | да |
| title_emoji | str | 1 эмодзи (fallback по сектору) | нет |
| lead | str | 80-200 chars, 2-3 предложения | да |
| facts | array[str] | ровно 3 элемента, каждый 30-110 chars | да |
| newbie_voice | str | 30-200 chars | да |
| tone | enum | `harsh`/`confused`/`ironic`/`calm` | да |
| hashtags | array[str] | 1-3 тематических | нет |

### Запрещено

- generic-заголовки: «Новость, которая может двигать рынок», «Срочно», «Сегодня в крипте», «Важная новость», «Горячая новость», «Разбор новости»
- лозунги в новостном стиле: «следует обратить внимание», «стоит учитывать», «не за горами»
- слова из forbidden_words.json: «торговый сигнал», «покупай», «продавай», «гарантированная прибыль», «100%», «инвестиционный совет», «мы рекомендуем»
- блок-заголовки: «Коротко:», «Главные моменты:», «Почему важно:», «AI-наставник:», «Ошибка новичка:», «Вывод:» — это маркеры v1, в v2 не используются
- если новость уже в `previous_phrases_to_avoid` — НЕ ОТМЕЧАЕМ её, возвращаем `should_publish: false` с reason

## Тональности (поле `tone`)

### harsh — резко, без жалости к НЕдисциплине

Когда применять: security_hacks_scams, scam_radar, memecoins_low_priority.

«Жёстко к выбору, не к людям». Никаких «вы лохи», только «такая стратегия = слив».

Примеры newbie_voice:
- «"Деньги вернули — значит ок" — худший вывод из этой истории. Один whitehat вернул, второй — точно нет.»
- «Закинуть депозит в meme через час после твита — это не торговля, это лотерея. Без планки риска ушёл бы и я.»
- «Не «надо больше плеча». Надо меньше плеча.»

### confused — растерянный, перечитывает

Когда применять: macro, regulation_etf_institutional.

Голос новичка, который видит макро-новость и не понимает, как она его касается. Без «не за горами» и «эксперты считают». Только «перечитал, попробовал понять, кажется так-то».

Примеры newbie_voice:
- «Перечитал дважды. Ставку держат — крипта вроде не должна реагировать сильно? Или я опять что-то не понимаю.»
- «"Поправка к закону" — звучит как буря в стакане. Но если правда могут запретить — депозит держать в чём?»

### ironic — сарказм, отсылки к прошлым циклам

Когда применять: memecoins_low_priority, political_market_noise.

Если «новый мемкоин +400%» — это видимо тот самый, который через неделю -90%. Без злобы, просто отметить узор.

Примеры newbie_voice:
- «Очередной "новый Шиба", очередные +300%, очередной "до луны". Цирк один и тот же, лохи новые.»
- «Каждый раз обещают "новую эру". В прошлый раз новая эра кончилась через 14 дней.»

### calm — спокойный наблюдатель

Когда применять: rwa_tokenization, depin_infrastructure, stablecoins, ai_crypto.

Спокойно фиксирует факт без эмоций. Чаще про долгосрочное.

Примеры newbie_voice:
- «Запомнил себе: RWA выходит в DeFi через Aave. Через год вспомню — будет интересно сравнить.»
- «Стейблы добавили в L2. Депозит для меня лично проще не станет, но рынок чуть нормальнее.»

## Структура поста (рендер)

Один пост = один photo+caption ≤ 1024 chars HTML. Структура **определяется кодом**, Claude отдаёт ТОЛЬКО payload:

```
{rubric_hashtag}             ← добавляется кодом из SECTOR_RUBRIC
                              ← пустая строка
{emoji} <b>{specific_title}</b>
                              ← пустая
{lead}
                              ← пустая
➤ {fact[0]}
➤ {fact[1]}
➤ {fact[2]}
                              ← пустая
🐹 {newbie_voice}
                              ← пустая
<a href="{url}">{source}</a>
                              ← пустая
{hashtags}                    ← merge: rubric + assets + claude_tags, max 4
```

Никаких заголовков-секций. Никаких disclaimer'ов внутри (живёт в pinned).

## mistake_theme_hint (каждый 5-й пост)

Если в user_payload пришло `mistake_theme_hint`:

```json
{
  "mistake_theme_hint": {
    "title": "Риск-менеджмент: почему 95% новичков сливают в первые месяцы",
    "instruction": "Если уместно к новости — вплети мысль из этой темы в newbie_voice. Если нерелевантно — игнорируй."
  }
}
```

Это **подсказка**, не команда. Если тема релевантна новости — вплети одну фразу в `newbie_voice`. Если новость про макро, а тема про FOMO — игнорируй.

## previous_phrases_to_avoid

Если в user_payload пришло `previous_phrases_to_avoid` — это список уже опубликованных или находящихся на ревью заголовков и фраз. НЕ повторяем:
- титул (даже на другом языке = тот же сюжет)
- characteristic newbie_voice фразы

Если новость **дубликат** по сути — возвращаем `should_publish: false` с reason='cross-source dup'.

## Хэштеги

Возвращай 1-3 тематических (#DeFi, #whitehat, #хак). Код добавит:
- секторную рубрику первым (`#безопасность_депозита`, `#скам_радар`, `#новости_без_паники`, ...)
- `#BTC`/`#ETH` если есть в `item.assets`
- финально дедуплицирует и режет до 4

Не давай: `#новости`, `#крипта` — это шум.

## should_publish: false

Если новость:
- кликбейт без сути
- кросс-источниковый дубликат (`previous_phrases_to_avoid`)
- impact_score слишком низкий (но это решает orchestrator до тебя, обычно не дойдёт)
- не подходит под концепцию канала (про «дневник новичка», не про техническую новость в DeFi protocol upgrade)

→ верни `{"should_publish": false, "skip_reason": "<короткая причина>"}`.

## Примеры финальных постов

### harsh (security)

```
#безопасность_депозита

🤝 <b>Взломал и вернул: Renegade отдали $190K</b>

Whitehat нашёл дыру в DeFi-протоколе Renegade,
вывел $190K и через пару часов вернул всё обратно.

➤ Уязвимость была реальной, не «теоретической».
➤ Деньги вернул один человек, а не сам протокол.
➤ Если придёт blackhat — никто не вернёт.

🐹 «Всё ок, деньги на месте» — худший вывод
из такой новости.

Cointelegraph

#безопасность_депозита #DeFi #whitehat
```

### confused (macro)

```
#новости_без_паники

🌍 <b>ФРС держит ставку 5.25% — рынок не двигается</b>

ФРС оставил ключевую ставку без изменений в третий
раз подряд. Крипта в первые часы практически не отреагировала.

➤ Решение было прайсингом ожидаемого исхода.
➤ Powell намекнул на возможный cut во второй половине года.
➤ Долгосрочные позиции в BTC выросли на 1.2% за час.

🐹 Перечитал дважды. Если ставку держат — крипта вроде не должна
реагировать сильно? Или я опять что-то не понимаю.

CoinDesk

#новости_без_паники #BTC #FED
```

### ironic (meme)

```
#не_будь_хомяком

🎪 <b>Roaring Kitty 2.0 — новый мемкоин на +400%</b>

Анонимный аккаунт с 200K подписчиков запустил мемкоин $KITY,
который за 6 часов вырос на 412%. Volume — $40M.

➤ Контракт без аудита, ликвидность не заблокирована.
➤ Создатель купил 38% supply за 12 SOL до старта.
➤ Аналогичный сценарий повторялся в 2024 минимум 7 раз.

🐹 Очередной «новый Шиба», очередные +400%, очередной
«до луны». Цирк один и тот же, лохи новые.

CryptoSlate

#не_будь_хомяком #мемкоины
```

### calm (rwa)

```
#реальная_крипта

🏗️ <b>Aave добавил поддержку токенизированных T-bills</b>

Aave V4 запустил поддержку токенизированных US Treasury bills
от Ondo Finance — теперь доступны как залог для займов.

➤ Минимальный размер залога — $1000 в эквиваленте.
➤ Yield ≈ 5.2% годовых из реальных T-bills.
➤ Это первый продакшен T-bills в крупном DeFi-протоколе.

🐹 Запомнил себе: RWA выходит в DeFi через Aave. Через год
вспомню — будет интересно сравнить, что работает дальше.

The Defiant

#реальная_крипта #RWA #DeFi
```

## Кратко

- Один пост = одно сообщение photo+caption ≤ 1024 chars.
- Только новичок, AI-наставник убран из новостей.
- 4 тональности, ротация по сектору (`pick_tone` в коде).
- Никаких generic-заголовков и блок-заголовков.
- previous_phrases_to_avoid → `should_publish: false`.
- `mistake_theme_hint` — подсказка, не команда.
- Хэштеги: 1-3 от Claude, остальное добавит код.
```

(Использовать Write tool с указанным содержимым полностью.)

- [ ] **Step 9.4: Smoke — style_guides loader подхватит изменение**

```bash
python -c "
from style_guides import load_guide
guide = load_guide('news')
print('news guide loaded, length:', len(guide))
print('contains v2:', 'JSON schema v2' in guide)
print('contains harsh tone example:', 'harsh' in guide)
"
```

Expected:
```
news guide loaded, length: <число>
contains v2: True
contains harsh tone example: True
```

- [ ] **Step 9.5: Commit**

```bash
git add news_style_guide.md
git commit -m "docs(news-v2): rewrite style guide for v2 schema (compact, voiced, 4 tones)"
```

---

## Task 10: Smoke-тесты end-to-end через CLI

**Files:**
- Run: `python bot.py --news-debug`, `--news-now`, `--news-source-image-test`

- [ ] **Step 10.1: Feature flag check**

```bash
cd "d:\Вайбкодинг\Тг новичок и ai наставник"
python -c "from news.config import NewsConfig; c = NewsConfig.from_env(); print('news_format_version =', c.news_format_version)"
```

Expected: `news_format_version = v2`

- [ ] **Step 10.2: Длина caption — синтетика 3 sample**

```bash
python -c "
from news.publisher import normalize_payload_v2, build_html_v2
from news.models import NewsItem

item = NewsItem(title='t', url='https://example.com', source='Example', published_at='', summary='', assets=['BTC'], category='other', sector='security_hacks_scams', impact_score=85.0)

# Sample 1: короткий
p1 = {'should_publish': True, 'specific_title': 'Test 1', 'lead': 'short lead. ' * 8, 'facts': ['fact one is long enough text', 'fact two is long enough text', 'fact three is long enough text'], 'newbie_voice': 'newbie short voice example here', 'tone': 'harsh', 'hashtags': ['#test']}

# Sample 2: средний
p2 = {'should_publish': True, 'specific_title': 'Medium title example', 'lead': 'medium length lead text. ' * 5, 'facts': ['fact 1 of medium length text data', 'fact 2 of medium length text data', 'fact 3 of medium length text data'], 'newbie_voice': 'medium newbie voice example text. ' * 3, 'tone': 'harsh', 'hashtags': ['#m1','#m2']}

# Sample 3: длинный на грани
p3 = {'should_publish': True, 'specific_title': 'Long title takes up some place', 'lead': 'long lead text close to limit. ' * 6, 'facts': ['fact 1 very long content close to 110 chars limit per item maximum length here', 'fact 2 very long content close to 110 chars limit per item maximum length here', 'fact 3 very long content close to 110 chars limit per item maximum length here'], 'newbie_voice': 'long newbie voice close to limit ' * 6, 'tone': 'harsh', 'hashtags': ['#h1','#h2','#h3']}

for i, p in enumerate([p1, p2, p3], 1):
    n = normalize_payload_v2(p, item)
    html = build_html_v2(n, item)
    print(f'sample {i}: html len = {len(html)} (limit 1024)')
"
```

Expected: все три ≤ 1024.

- [ ] **Step 10.3: Pipeline без публикации в канал**

Убедиться `.env: NEWS_DRY_RUN=true`. Затем:

```bash
python bot.py --news-now
```

Expected:
- В DM владельцу пришло **3 сообщения** (header + (опц.guard) + post) или **2** (header + post) если guard прошёл
- Сам пост = одно сообщение photo+caption ≤ 1024 chars
- Никакого "Полный разбор ниже"
- В `outputs/scheduler.log` (или stderr) — нет ошибок

- [ ] **Step 10.4: Проверить idempotency кнопок**

После Step 10.3 — нажать ✅ Опубликовать на превью **дважды быстро**.

Expected в логе:
```
CB news_publish: from=... data=news_publish:... msg_id=...
CB news_publish: from=... data=news_publish:... msg_id=...
```
Первый клик уводит draft в `publishing` → `published`. Второй клик видит `published`, отвечает `Уже обработано (published)`, кнопки убираются.

В канал ушло **ровно 1 сообщение**.

- [ ] **Step 10.5: Если кнопки НЕ работают — диагностика**

Если строки `CB news_publish` НЕ появляются в логе:
- Polling не получает updates. Проверить `outputs/scheduler.log` на наличие исключений `polling_task`
- `ENABLE_WEBHOOK` в `.env` — если `true`, polling не активен → выключить
- Дублирующий instance бота (например, открыта debug-сессия `python bot.py`) — закрыть

Если строка появляется но `not owner`:
- Сравнить `cb.from_user.id` (видно в логе) с `OWNER_CHAT_ID` в `.env`

Если строка появляется, owner валидный, но send в канал упал — стек уже в логе.

- [ ] **Step 10.6: 🖼 AI-картинка работает БЕЗ image_prompt_hint от Claude**

```bash
python bot.py --news-image-test
```

Expected: файл сохранён в `outputs/news_images/<hash>.png`, image prompt взят из `SECTOR_IMAGE_HINTS`.

- [ ] **Step 10.7: Source-preview (og:image) не сломан**

```bash
python bot.py --news-source-image-test https://cointelegraph.com/
```

Expected: og:image вытянут, файл сохранён.

- [ ] **Step 10.8: Старый v1 draft рендерится через legacy**

Если в `news_drafts.json` есть pending v1 draft (без schema_version или с `schema_version=v1`):

```bash
python bot.py --news-drafts
```

Должен показать список. Нажатие ✅ на v1-draft → `build_html_legacy` → отправка как один длинный пост (нет 1024 ограничения если без image).

Если v1 draft'ов нет — пропустить шаг.

- [ ] **Step 10.9: Все тесты ещё проходят**

```bash
python -m pytest tests/test_news_v2_smoke.py -v
```

Expected: passed.

- [ ] **Step 10.10: Commit smoke verification (если репо git)**

```bash
git status   # должно быть clean
echo "Smoke tests passed at $(Get-Date)" > .stage14-smoke-passed
git add .stage14-smoke-passed
git commit -m "test(news-v2): smoke verified end-to-end"
```

---

## Task 11: Перезапустить scheduler и финальная боевая проверка

**Files:**
- runtime: `DepositAiDiary` task

- [ ] **Step 11.1: Снова включить scheduler**

```powershell
powershell -NoProfile -Command "Start-ScheduledTask -TaskName DepositAiDiary; Start-Sleep -Seconds 5; Get-ScheduledTask -TaskName DepositAiDiary | Select-Object TaskName,State"
```

Expected: `State : Running`

- [ ] **Step 11.2: Проверить что polling реально работает**

В DM боту написать `/start` (или любое сообщение). Через несколько секунд проверить лог:

```bash
type "d:\Вайбкодинг\Тг новичок и ai наставник\outputs\scheduler.log" | findstr /C:"CB " /C:"polling"
```

Expected: видны записи активности polling.

- [ ] **Step 11.3: Триггер реальной новости через CLI**

```bash
cd "d:\Вайбкодинг\Тг новичок и ai наставник"
python bot.py --news-now
```

(Этот запуск НЕ через scheduler — может ловить collision; делать только когда scheduler-instance не вызывает свой news-job.)

Альтернатива: дождаться natural cycle scheduler'а (обычно `NEWS_SCAN_INTERVAL_MINUTES=60`).

- [ ] **Step 11.4: Получить превью в DM**

Ожидаем:
- 1 сообщение-шапка `🧪 Превью #<id> · sector=... · impact=... · tone=...`
- (опц.) 1 сообщение `🚫 Publish-guard заблокировал...` если payload не идеальный
- 1 сообщение photo+caption с самим постом, **3 кнопки в 4 рядах** (Опубликовать/Исправить, Перегенерировать/Отклонить, AI-картинка, Превью источника)

- [ ] **Step 11.5: Нажать ✅ Опубликовать**

Expected:
- Telegram показывает "loading" в момент нажатия (быстрый ack — должно быть мгновенно)
- В канале появляется пост, **одно сообщение** photo+caption ≤ 1024
- В DM — кнопки исчезают
- В `outputs/scheduler.log` — `CB news_publish: from=..., status: publishing → published`

- [ ] **Step 11.6: Проверить counter инкрементировался**

```bash
python -c "
import json
from pathlib import Path
s = json.loads(Path('state.json').read_text(encoding='utf-8'))
print('news_post_counter:', s.get('news_post_counter', 0))
"
```

Expected: число > 0 (на 1 больше чем до публикации).

- [ ] **Step 11.7: Если что-то пошло не так — rollback**

В `.env` поставить:
```
NEWS_FORMAT_VERSION=v1
```

Перезапустить scheduler:
```powershell
powershell -NoProfile -Command "Restart-ScheduledTask -TaskName DepositAiDiary"
```

Старые v1 draft'ы продолжат работать.

---

## Self-Review

После завершения всех 11 tasks свериться со spec'ом по разделам.

**Spec coverage:**
- §1 Цели — проблемы 1 (split), 2 (формат), 3 (разнообразие), 4 (кнопки) — все закрыты: Task 4 (без split), Task 9 (style guide v2), Task 5+6 (tone+counter+inject), Task 6+10 (callback logging+idempotency)
- §2 Формат — Task 4 (send), Task 2 (merge_hashtags), Task 9 (style guide примеры)
- §3 Schema — частично уже было, Task 3 (normalize), Task 7 (should_publish=false)
- §4 Pipeline — Task 3 (normalize), Task 4 (final guard + send), Task 8 (preview 3-msg), Task 6 (callbacks)
- §5 Тесты+rollout — Task 1 (baseline), Task 10 (smoke), Task 11 (production)

**Placeholder scan:** ни одного TODO/TBD в шагах, все код-блоки заполнены.

**Type consistency:**
- `merge_hashtags(claude_tags, sector, assets)` сигнатура одинакова в Task 2 и Task 3
- `normalize_payload_v2(payload, item, revision_count=0)` — три аргумента, последний default
- `final_caption_guard(html) -> tuple[bool, str]` — везде одинаково
- `PreviewSendFn = Callable[[str, Optional[dict], Optional[str]], Awaitable[None]]` — kb_dict теперь Optional
- `NewsPublisher.__init__` принимает `counter_get`/`counter_inc` callables

Всё консистентно.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-13-deposit-ai-news-v2-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** — я диспатчу свежего subagent на каждый task, ревью между tasks, быстрая итерация.

**2. Inline Execution** — Выполняю tasks в этой сессии через `superpowers:executing-plans`, batch execution с checkpoint'ами для ревью.

Какой подход?
