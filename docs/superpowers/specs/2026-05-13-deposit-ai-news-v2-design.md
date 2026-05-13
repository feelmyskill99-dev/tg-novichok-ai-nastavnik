# Stage 14 — News redesign v2 (compact + voiced + diverse)

**Дата:** 2026-05-13
**Автор:** brainstorm с владельцем
**Статус:** approved, готов к writing-plans

---

## 1. Цели и не-цели

### Чиним

1. **Двойное сообщение.** Сейчас при caption > 1000 chars пост уходит двумя сообщениями: photo+короткая подпись («Полный разбор ниже 👇») и отдельным сообщением полный текст. Текст частично дублируется, выглядит как «помойка». Цель — **один пост = photo+caption ≤ 1024 chars**, без второго сообщения.

2. **ИИ-простыня.** Текущий формат имеет 9 секций с заголовками (`Коротко`, `Главные моменты`, `Почему это важно`, `🐹 Мысль новичка`, `🤖 AI-наставник`, `⚠️ Ошибка новичка`, `📌 Вывод`, disclaimer, hashtags). Это выглядит шаблонно. Цель — **компактный пост без заголовков-секций**, с одним голосом новичка в конце.

3. **Однообразие.** Все посты одинакового тона и структуры. Цель — **ротация 4 тональностей × секторы + рандомный inject ошибки** из `mistake_themes.json` каждый 5-й пост.

4. **«Кнопки не кликабельны»** в DM владельцу. Бот `DepositAiDiary` Running, polling запущен, но при нажатии «ничего не происходит». Цель — **диагностика логов + фикс root cause**, не симптомный патч.

### НЕ делаем

- Market posts (10:00 / 19:00) — отдельный pipeline, caption-fit Stage 13 уже работает
- Author notes, weekly_diary, trade posts — не трогаем
- RSS источники, скоринг, дедупликация, quota — не трогаем
- Admin panel (`admin.html` / `admin_panel.py`) — отложено
- Источниковая og:image, AI-картинка через кнопку 🖼 — работают как раньше

---

## 2. Формат поста v2

### Структура (caption photo ≤ 1024 chars HTML)

```
{rubric_hashtag}                       ← 1 строка, маркер сектора
                                        ← пустая
{emoji} <b>{specific_title}</b>        ← 1 строка, ≤ 80 chars без эмодзи
                                        ← пустая
{lead}                                  ← 2-3 предложения, ≤ 200 chars
                                        ← пустая
➤ {fact_1}                             ← 3 буллета, каждый ≤ 110 chars
➤ {fact_2}
➤ {fact_3}
                                        ← пустая
🐹 {newbie_voice}                      ← 1-2 фразы, ≤ 200 chars
                                        ← пустая
<a href="{url}">{source_name}</a>      ← 1 строка
                                        ← пустая
{hashtags}                              ← 3-4 тега в строку
```

### Sample (Renegade hack)

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

<a href="https://cointelegraph.com/...">Cointelegraph</a>

#DeFi #whitehat #безопасность_депозита
```

### Удаляется

- ❌ заголовки `Коротко:` / `Главные моменты:` / `Почему это важно:` / `🤖 AI-наставник:` / `⚠️ Ошибка новичка:` / `📌 Вывод:`
- ❌ disclaimer `Не финсовет. Это дневник обучения и AI-разбор.` — переезжает в pinned message канала и в `/about`
- ❌ `Полный разбор ниже 👇`
- ❌ split-режим в send-функции

### Лимиты

| Поле | Лимит | Доля |
|---|---|---|
| title (с эмодзи и `<b></b>`) | ≤ 100 chars | |
| lead | 80-200 chars | |
| 3 буллета | ≤ 110 каждый | ≤ 330 |
| newbie_voice | 30-200 chars | |
| hashtags + source + rubric | ≈ 150 chars | |
| **итого** | **≤ ~910 chars** | запас 110 на HTML |

### Эмодзи-префиксы по секторам

| Сектор | Эмодзи |
|---|---|
| security_hacks_scams | 🤝 (whitehat) / ⚠️ (hack) |
| scam_radar | 🕵️ |
| regulation_etf_institutional | 🏛️ |
| macro | 🌍 |
| ai_crypto | 🤖 |
| stablecoins | 💵 |
| memecoins_low_priority | 🎪 |
| rwa_tokenization, depin_infrastructure | 🏗️ |
| political_market_noise | 🧨 |
| other | 🗒️ |

### Хэштеги

**Max 4 хэштега**, merge-правило в `merge_hashtags(claude_tags, sector, assets)`:

1. **Sector rubric** из `SECTOR_RUBRIC` — всегда первый (1 слот)
2. **Asset tags** (`#BTC`, `#ETH`) из `item.assets[:2]` — максимум 2 слота
3. **Claude thematic tags** — добивают до total ≤ 4
4. **dedupe** с сохранением порядка (lowercase compare)
5. **Не добавляем** `#новости`, `#крипта` — шумовые

Итого 3-4 строго. Если sector rubric + 2 ассета — для Claude tags остаётся 1 слот.

---

## 3. Claude JSON schema v2

### Поля

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

### Валидация (publish-guard v2)

| Поле | Тип | Лимит | Обязательно |
|---|---|---|---|
| should_publish | bool | — | да |
| specific_title | str | 12-80 chars, не в blacklist | да |
| title_emoji | str | 1 эмодзи, fallback по сектору | нет |
| lead | str | 80-200 chars, 2-3 предложения | да |
| facts | array[str] | ровно 3, каждый 30-110 chars | да |
| newbie_voice | str | 30-200 chars | да |
| tone | enum | harsh / confused / ironic / calm | да |
| hashtags | array[str] | 1-3 тематических | нет |

### Удалённые поля (старые)

`brief_review`, `key_points`, `why_it_matters`, `human_part`, `mentor_part`, `beginner_mistake`, `lesson`, `question`, `image_prompt_hint` (последнее переезжает в orchestrator вычислением из `SECTOR_IMAGE_HINTS`, не нужно от Claude).

### Поведение при `should_publish: false`

Claude может вернуть:

```json
{
  "should_publish": false,
  "skip_reason": "новость слишком технична для аудитории-новичков"
}
```

В этом случае:
- НЕ создаём publishable draft (статус `skipped` в `news_history.json`)
- НЕ инкрементируем `news_post_counter`
- Шлём владельцу короткое DM: `🔕 Скипнул: <skip_reason> — <item.title[:80]>`
- В DM **нет кнопок** — это просто инфо, действий не требуется

Если `skip_reason` отсутствует — DM-сообщение пишет `(без причины от Claude)`.

### Тональности (поле `tone`)

| tone | Голос новичка | Дефолтные секторы |
|---|---|---|
| `harsh` | резко, без жалости к новичку | security_hacks_scams, scam_radar, memecoins_low_priority |
| `confused` | растерянный, перечитывает | macro, regulation_etf_institutional |
| `ironic` | сарказм, отсылки к прошлым циклам | memecoins_low_priority, political_market_noise |
| `calm` | спокойный наблюдатель | rwa_tokenization, depin_infrastructure, stablecoins, ai_crypto |

**Выбор тона:** `pick_tone(item, revision_count)`:
- если сектор имеет один кандидат — он
- если несколько — `tones[news_hash(item) % len(tones)]`
- при `revision_count > 0` — `tones[(news_hash + revision_count) % len(tones)]` (другая тональность при regenerate)

### Inject mistake_theme (каждый 5-й пост)

**Счётчик:** `state.json: news_post_counter`, начинается с 0. Инкрементируется в `publisher.publish` **только** при `decision == "published_channel"` (не при `preview_sent` / `skipped` / `rejected`).

**Решение об инжекте — ПЕРЕД отправкой в Claude:**

```python
next_post_number = state.news_post_counter + 1   # счёт будущего поста
should_inject = (next_post_number % 5 == 0)
```

При `should_inject` Claude получает в user_payload поле `mistake_theme_hint`:

```json
{
  "mistake_theme_hint": {
    "title": "Риск-менеджмент: почему 95% новичков сливают в первые месяцы",
    "instruction": "Если уместно к новости — вплети мысль из этой темы в newbie_voice. Если нерелевантно — игнорируй."
  }
}
```

Тема выбирается случайно из `mistake_themes.json` (15 тем). При `revision_count > 0` инжект сохраняется (та же тема), чтобы не путать Claude между ревизиями.

---

## 4. Pipeline

### 4.0 Полный порядок шагов (от Claude до Telegram)

```
1. Claude payload (raw JSON)
   ↓
2. validate_payload_v2(payload, item)
     → list[str] reasons; пустой = валидно
   ↓
3. normalize_payload_v2(payload, item)
     → нормализованный payload:
       - title_emoji: если пусто → SECTOR_TITLE_EMOJI[sector]
       - tone: если невалидный → pick_tone(item, revision_count)
       - facts: dedupe + cleanup whitespace; если ≠ 3 — оставляем сколько есть
                (валидатор уже отбил bad payload)
       - hashtags: merge_hashtags(claude_tags, sector, assets) → max 4
   ↓
4. RenderModel(normalized, item) — dataclass с готовыми строками
     (отделяет render от Claude format; для тестов и legacy renderer)
   ↓
5. build_html_v2(render_model) → HTML string
   ↓
6. _truncate_post_to_caption_limit(html, render_model) → HTML или None
     каскадно режет если > 1024; None = слишком плотно
   ↓
7. final_caption_guard(html) — проверяет ТОЛЬКО caption safety:
     - len(html) ≤ 1024
     - no broken HTML tags
     - не Claude schema (это уже сделал validate_payload_v2)
   ↓
8. send_post_with_optional_image(bot, chat, html, image_path, reply_markup)
```

`normalize_payload_v2` существует чтобы fallback-логика (emoji, tone, hashtag merge) **не размазалась** между renderer/publisher/handler. Один вход — одна точка fallback'ов.

### 4.1 `send_post_with_optional_image` — без split

```python
async def send_post_with_optional_image(bot, chat_id, post_html, image_path, *,
                                         reply_markup=None, ...):
    if not image_path or not Path(image_path).exists():
        return await bot.send_message(chat_id, post_html, ..., reply_markup=reply_markup)
    return await bot.send_photo(chat_id, FSInputFile(image_path),
                                 caption=post_html, ..., reply_markup=reply_markup)
```

Удаляются: `_build_short_caption`, `PHOTO_CAPTION_SAFE_LIMIT` (становится `PHOTO_CAPTION_HARD_LIMIT = 1024`). `_strip_html_tags` — оставляем, используется в truncate-каскаде.

### 4.2 `_truncate_post_to_caption_limit` (новый)

Если рендер дал > 1024 chars — каскадно режем:
1. `newbie_voice` → 1 фразу (до 100 chars)
2. удаляем 3-й факт
3. `lead` → 1 фразу (до 130 chars)
4. удаляем 2-й факт
5. если всё ещё > 1024 → возвращаем None, `publisher.publish` отдаёт владельцу алерт `"новость слишком плотная для одного поста — посмотри текст"` со статусом `skipped`. Эту новость в канал не публикуем.

**Важно:** после truncate схема `validate_payload_v2` уже **не применяется**. Она запускается ОДИН раз в шаге 2 (см. §4.0) к raw Claude payload, и проверяет инвариант "Claude отработал правильно". `final_caption_guard` (шаг 7) проверяет ТОЛЬКО caption safety: длина ≤ 1024 + не разорванные HTML-теги. Так truncated post с `lead = 1 фраза` (даже если 50 chars) не отвергается — это валидный пост, просто Claude выдал слишком плотную новость и мы её ужали.

### 4.3 Превью владельцу

Сейчас `_wrap_preview` лепит header «🧪 Превью...» внутрь HTML — это съедает место и портит визуал. Делаем так:

```python
# 1) мини-сообщение шапка
await bot.send_message(owner_chat_id,
    f"🧪 Превью #{draft_id[:8]} · sector={sector} · impact={impact} · tone={tone}")

# 2) если есть guard_reasons — ещё одно мини
if guard_reasons:
    await bot.send_message(owner_chat_id, "🚫 " + "\n".join(reasons))

# 3) сам пост — точно так, как пойдёт в канал, с кнопками
await send_post_with_optional_image(bot, owner_chat_id, post_html, image_path,
                                     reply_markup=keyboard)
```

Преимущество — превью в DM **визуально идентично** тому, что пойдёт в канал.

### 4.4 Кнопки — idempotency state guard + логирование

**Расширяем NewsDraft.status:**

```
pending_review → publishing → published_channel
pending_review → rejected
pending_review → revised → (pending_review при ❌ Reset, или publishing при ✅)
```

`publishing` — новое промежуточное состояние, выставляется в `on_news_publish` **до** `send_post_with_optional_image`. Если send упал — статус откатывается на `pending_review`.

**Все 6 news-callback'ов** (`news_publish/edit/regenerate/reject/generate_ai_image/refresh_source_image`):

```python
@dp.callback_query(F.data.startswith("news_publish:"))
async def on_news_publish(cb: CallbackQuery):
    log.info("CB news_publish: from=%s data=%s msg_id=%s",
             cb.from_user.id if cb.from_user else "?",
             cb.data, cb.message.message_id if cb.message else "?")
    await cb.answer()  # НЕМЕДЛЕННО, до тяжёлых операций
    if not await _is_owner_cb(cb):
        log.warning("CB news_publish: not owner (%s vs %s)",
                    cb.from_user.id, OWNER_CHAT_ID)
        return

    draft = store.get(draft_id)
    if not draft:
        await cb.answer("Черновик не найден", show_alert=True)
        return

    # idempotency guard — реальная защита от двойного клика и старых сообщений
    TERMINAL = {"publishing", "published", "published_channel", "rejected"}
    if draft.status in TERMINAL:
        await cb.answer(f"Уже обработано ({draft.status})", show_alert=True)
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    # переводим в publishing СРАЗУ, чтобы второй клик увидел terminal
    draft.status = "publishing"
    store.update(draft)
    try:
        # ... отправка в канал ...
        draft.status = "published"
    except Exception:
        draft.status = "pending_review"   # откат
        store.update(draft)
        raise
    finally:
        store.update(draft)
```

Для `reject` — terminal сразу. Для `edit/regenerate/generate_ai_image/refresh_source_image` — `pending_review` остаётся (это не финальные действия), но локальная idempotency-блокировка на время операции через `state.json: awaiting_<action>_for_draft_id` (уже есть для edit, расширяем на остальные).

### 4.5 Диагностика "кнопки не кликабельны"

**До правки** прогоняем 3 шага:

1. Добавляем логирование (см. 4.4) → деплоим → ждём нажатия владельцем.
2. Читаем `outputs/scheduler.log`:
   - Если строка `CB news_publish` НЕ появляется → polling не получает updates. Проверяем: `polling_task.exception()`, `ENABLE_WEBHOOK`, дублирующий instance бота.
   - Если `CB ... not owner` → `.env OWNER_CHAT_ID` != `cb.from_user.id`.
   - Если CB ловится и owner валидный → exception в handler, стек уже в логе.
3. Фикс по результату.

### 4.6 Где живёт код

```
news/
  publisher.py
    build_html_v2(payload, item)            # NEW, дефолтный
    build_html_legacy(payload, item)        # NEW, обёртка над старым build_html
                                             # (def, не alias — позволяет в будущем
                                             # рефакторить старый renderer независимо)
    validate_payload_v2(payload, item)      # NEW
    normalize_payload_v2(payload, item)     # NEW
    merge_hashtags(claude_tags, sector, assets)  # NEW, max 4
    _truncate_post_to_caption_limit(...)    # NEW
    final_caption_guard(html)                # NEW
    pick_tone(item, revision_count)         # NEW
    inject_mistake_theme(payload, item, next_post_number)  # NEW
    short_caption()                          # УДАЛЯЕТСЯ
  config.py
    news_format_version: str = "v2"         # NEW, env NEWS_FORMAT_VERSION
  drafts.py
    NewsDraft.schema_version: str = "v2"    # NEW, default v2; старые v1
                                            # из json получают v1 при load
bot.py
  send_post_with_optional_image()           # упрощается
  _build_short_caption()                    # УДАЛЯЕТСЯ
  PHOTO_CAPTION_SAFE_LIMIT                  # переименован в PHOTO_CAPTION_HARD_LIMIT = 1024
  _wrap_preview()                            # УДАЛЯЕТСЯ, заменяется на 2 мини + send_post
  _register_news_callbacks()                 # обновляется (логи + cb.answer first)
news_style_guide.md
  переписывается под v2 schema
```

---

## 5. Тестирование и rollout

### 5.1 Smoke-тесты

```bash
# 0. Feature flag загрузился
python -c "from news.config import settings; print('news_format_version =', settings.news_format_version)"
#   ожидаем: v2

# 1. Claude понимает v2 schema
python bot.py --news-debug
#   ожидаем: payload с полями specific_title/title_emoji/lead/facts/newbie_voice/tone/hashtags
#   старые поля (brief_review, key_points, mentor_part) отсутствуют

# 2. Длина caption в build_html_v2
python -c "from news.publisher import build_html_v2; ..."   # 3 sample payload
#   все три должны давать ≤ 1024 chars HTML

# 3. Pipeline без публикации в канал
NEWS_DRY_RUN=true python bot.py --news-now
#   ожидаем: один draft, photo+caption ≤ 1024, кнопки приходят к владельцу

# 4. Кнопки — нажать ✅ → проверить outputs/scheduler.log на 'CB news_publish'
#   также проверить idempotency: повторный клик ✅ → "Уже обработано"

# 5. Ротация тонов
python bot.py --news-debug --tone-distribution-check   # NEW CLI
#   эмулирует 10 новостей разных секторов, печатает выбранную тональность

# 6. 🖼 AI-картинка работает БЕЗ image_prompt_hint от Claude
python bot.py --news-image-test
#   image_prompt берётся из SECTOR_IMAGE_HINTS[sector], OpenAI 200 OK, файл сохранён

# 7. Source-preview (og:image) не сломан
python bot.py --news-source-image-test https://cointelegraph.com/
#   ожидаем: og:image вытянут, файл сохранён

# 8. Старый draft (schema_version=v1) рендерится через legacy
python bot.py --news-drafts   # покажет существующие, в том числе старые
#   при ✅ на v1-draft → build_html_legacy → отправка
```

### 5.2 Rollout

1. Бэкап `news_drafts.json`, `news_style_guide.md` → `*.v1.bak`
2. Изменения кода (publisher, config, bot send + callbacks)
3. Переписать `news_style_guide.md` под v2
4. `.env: NEWS_FORMAT_VERSION=v2`
5. Smoke-тесты 1-5
6. `--news-now` в DM владельцу (DRY_RUN=true)
7. Ручная проверка владельцем: визуал, тон, кнопки
8. `NEWS_DRY_RUN=false` + один реальный пост в канал
9. 24 часа мониторинга

**Откат:** `.env NEWS_FORMAT_VERSION=v1` + рестарт. Старые draft'ы продолжат работать (schema_version=v1 → build_html_legacy).

### 5.3 Риски

| Риск | Митигация |
|---|---|
| Claude игнорирует v2 schema | publish-guard v2 блокирует; владелец видит причину в DM |
| `tone=harsh` → токсичность | в style guide: harsh = «жёстко к НЕдисциплине», не к людям |
| inject_mistake_theme ломает связь с новостью | inject = подсказка, Claude сам решает релевантность |
| caption > 1024 | _truncate_post_to_caption_limit каскад + fallback на skip |
| Кнопки чинились симптомно | Step 2 диагностики — без логов фикс не пишем |
| Старые drafts с v1 schema | DraftStore: при load — `schema_version="v1"` по умолчанию, рендер через build_html_legacy |

### 5.4 Что НЕ ломается

Author notes, weekly diary, market posts, trade posts, NewsDeduplicator, news_history.json, source-image flow, AI-картинка по кнопке 🖼, дедупликация cross-source, review-квота.

---

## 6. Открытые вопросы

- ~~Эмодзи в title — фиксированный по сектору или Claude сам предлагает?~~ → Claude предлагает в `title_emoji`, fallback по сектору если пусто.
- ~~Disclaimer в каждом посте?~~ → нет, только pinned + `/about`.
- ~~mistake_theme в каждом 5-м или случайно?~~ → детерминированно каждый 5-й (`news_post_counter % 5 == 0`).
- ~~Hashtags — Claude или код?~~ → Claude даёт 1-3 тематических, код добавляет sector rubric + assets, итого 3-4.

---

## 7. Следующий шаг

После approval — `superpowers:writing-plans` skill для детального плана имплементации (порядок коммитов, тесты, файлы построчно).
