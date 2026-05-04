# NEWS STYLE GUIDE — Депозит под надзором ИИ

## ЦЕЛЬ

Сделать новостные посты визуально сильными, понятными и живыми.

Новость в канале — это не сухая сводка и не сигнал. Это:

> новость → краткое ревью → факты → почему важно → мысль новичка → AI-наставник → ошибка → вывод.

---

## ОБЯЗАТЕЛЬНЫЙ ПОРЯДОК НОВОСТНОГО ПОСТА

1. Тематическое изображение по теме новости.
2. Конкретный заголовок.
3. Блок “Коротко”.
4. Блок “Главные моменты”.
5. Блок “Почему это важно”.
6. Мысль новичка.
7. AI-наставник.
8. Ошибка новичка.
9. Вывод.
10. Дисклеймер.
11. Хэштеги.

---

## ЗАПРЕЩЁННЫЕ НАЧАЛА

Не использовать:

- “Новость, которая может двигать рынок”;
- “Новость, за которой стоит следить”;
- “Важная новость”;
- “Крипто-новость дня”;
- “Срочно”;
- “Сегодня в крипте”.

Вместо этого писать конкретно по сути:

- “⚠️ Litecoin пережил атаку: паниковать или выдохнуть?”
- “🤖 AI снова пришёл в крипту: технология или хайп?”
- “🕵️ Скам-радар: прибыль обещают, риски прячут”
- “🏛 Регуляторы снова лезут в игру”
- “🐋 Киты шевелятся: рынок готовит движение?”

---

## NEWS JSON SCHEMA

Claude должен возвращать строго JSON без markdown fences:

```json
{
  "should_publish": true,
  "specific_title": "...",
  "brief_review": "...",
  "key_points": ["...", "...", "..."],
  "why_it_matters": ["...", "..."],
  "sector": "ai_crypto / security_hacks_scams / scam_radar / political_market_noise / regulation_etf_institutional / stablecoins / rwa_tokenization / depin_infrastructure / macro / whales / other",
  "risk_type": "market_noise / scam_risk / security_risk / regulation_risk / macro_risk / ai_hype / none",
  "reader_action": "observe / verify_source / avoid_clicking / improve_security / no_trade / learn",
  "market_impact": "bullish / bearish / mixed / neutral / uncertain",
  "affected_assets": ["BTC", "ETH"],
  "image_prompt_hint": "...",
  "human_part": "...",
  "mentor_part": "...",
  "beginner_mistake": "...",
  "lesson": "...",
  "question": "... или null",
  "hashtags": ["..."],
  "short_summary": "..."
}
```

Если новость слабая:

```json
{
  "should_publish": false,
  "reason": "..."
}
```

---

## ПРАВИЛА ДЛЯ ПОЛЕЙ

### specific_title

- конкретный;
- суть новости в одной строке;
- можно использовать эмодзи;
- нельзя использовать generic-заголовки.

### brief_review

2–4 предложения простым языком:

- что произошло;
- с кем;
- почему важно;
- чем закончилось или что дальше.

### key_points

3–5 фактов без воды.

### why_it_matters

2–4 пункта:

- влияние на рынок;
- влияние на доверие;
- влияние на сектор;
- урок для новичка.

### human_part

Живая реакция наблюдателя. Не выдумывать сделку.

Можно:

- “Когда вижу такое, первая мысль — всё, проект умер.”
- “На таких заголовках легко дёрнуться раньше времени.”
- “Тут хочется срочно что-то сделать, хотя плана нет.”

Нельзя:

- “я купил”;
- “я продал”;
- “я заработал”;
- “я потерял”.

### mentor_part

Спокойный разбор:

- где факт;
- где шум;
- где риск;
- что должен понять новичок.

### beginner_mistake

Коротко: какую ошибку новичка предотвращаем.

### lesson

1–3 предложения, практический вывод.

---

## SAFE HTML TEMPLATE

```html
<b>{specific_title}</b>

<b>Коротко:</b>
{brief_review}

<b>Главные моменты:</b>
• {key_point_1}
• {key_point_2}
• {key_point_3}

<b>Почему это важно:</b>
• {impact_1}
• {impact_2}

🐹 <b>Мысль новичка:</b>
{human_part}

🤖 <b>AI-наставник:</b>
{mentor_part}

⚠️ <b>Ошибка новичка:</b>
{beginner_mistake}

📌 <b>Вывод:</b>
{lesson}

<i>Не финсовет. Это дневник обучения и AI-разбор.</i>

{hashtags}
```

Если есть `question`, можно добавить перед дисклеймером:

```html
💬 {question}
```

---

## IMAGE FIRST POLICY

Если есть `image_path`, сначала отправлять картинку с caption.

Если caption длиннее лимита Telegram:

1. sendPhoto с коротким caption: title + brief_review.
2. sendMessage с полным текстом.

Если image generation failed:

- не падать;
- отправить post без картинки;
- показать владельцу warning.

---

## NEWS IMAGE GENERATION

Если:

- `ENABLE_NEWS_IMAGES=true`;
- `OPENAI_API_KEY` задан;
- `impact_score >= NEWS_IMAGE_MIN_IMPACT_SCORE`;
- draft не имеет `image_path`,

нужно генерировать тематическое изображение через OpenAI GPT Image API.

Сохранять:

```text
outputs/news_images/{news_hash}.png
```

Сохранять в draft:

- image_path;
- image_prompt;
- image_model;
- image_created_at.

---

## NEWS IMAGE STYLE

Общий стиль:

- dark cinematic crypto diary;
- blue-gray / neon accents;
- serious;
- intelligent;
- not luxury;
- no rockets;
- no bulls;
- no Lambos;
- no money rain;
- no guru vibe;
- no fake UI;
- no text on image by default.

Negative prompt:

```text
No text, no letters, no logos, no rockets, no luxury cars, no money rain, no influencer posing, no exaggerated crypto guru style, no meme clutter, no fake UI screenshots, no brand impersonation.
```

---

## IMAGE PROMPTS BY SECTOR

### security_hacks_scams / scam_radar

```text
Dark cinematic crypto security scene. A glowing blockchain network under cyber attack, red warning lights, a broken digital shield, suspicious phishing trap elements, subtle crypto chart in the background. Mood: caution, investigation, beginner safety. Style: dark blue-gray cyberpunk, realistic, clean composition, no text, no logos.
```

### ai_crypto

```text
A calm AI mentor hologram analyzing a crypto network and market chart, neural network patterns merging with blockchain nodes, a beginner trader silhouette watching carefully. Mood: intelligent, futuristic, cautious optimism. Dark blue and violet tones, cinematic lighting, no text, no logos, no hype.
```

### political_market_noise / regulation_etf_institutional

```text
A serious financial regulation scene: courthouse columns, documents, digital crypto chart reflections, institutional atmosphere, subtle red and blue market lights. Mood: political pressure, market uncertainty, no panic. Dark cinematic style, no text, no logos.
```

### whales / funding / open_interest / liquidation

```text
A dramatic dark ocean-like market scene with a huge shadow of a whale beneath a glowing candlestick chart, liquidity waves, order book depth visualized as light trails. Mood: hidden large players, market tension. No text, no logos, no cartoon whale.
```

### stablecoins

```text
A digital dollar stablecoin concept, transparent coin-like tokens floating over a blockchain payment rail, liquidity streams, calm but cautious financial atmosphere. Dark blue-gray style, clean, institutional, no text, no logos.
```

### rwa_tokenization

```text
Real-world assets becoming digital tokens: a building, bonds, and financial documents transforming into blockchain nodes. Institutional, clean, dark cinematic finance style, no text, no logos.
```

### depin_infrastructure

```text
Decentralized physical infrastructure network: servers, antennas, GPU units, and city lights connected by blockchain nodes. Futuristic but realistic, dark blue tones, no text, no logos.
```

### macro

```text
Global macro market pressure: abstract central bank building, dollar liquidity waves, candlestick chart reflections, risk-on/risk-off atmosphere. Dark cinematic financial style, no text, no logos.
```

### generic fallback

```text
A dark cinematic crypto market news illustration: blockchain nodes, subtle candlestick chart, a beginner trader silhouette, AI mentor glow in the background. Serious and educational mood, no text, no logos.
```

---

## SECTOR: AI X CRYPTO

Хорошие темы:

- AI agents;
- AI wallets;
- decentralized compute;
- AI trading automation risks;
- AI x DePIN;
- AI security;
- AI-generated scams;
- AI-token hype;
- on-chain data for AI.

Пример заголовков:

- “🤖 AI снова пришёл в крипту: технология или хайп?”
- “🧠 AI-токены ожили: где польза, а где маркетинг в худи?”
- “🤖 AI-агенты в блокчейне: будущее или ловушка для хомяков?”

Главная мысль:

> AI x Crypto — интересный сектор, но хайп не равен торговому плану.

---

## SECTOR: POLITICAL MARKET NOISE

Использовать для:

- выборов;
- заявлений политиков;
- санкций;
- SEC / CFTC / MiCA;
- ETF;
- судов;
- ставок ФРС;
- инфляции;
- доллара;
- геополитики;
- ограничений бирж;
- стейблкоинов;
- AI regulation.

Публиковать только если есть связь с рынком.

Не публиковать:

- партийные споры;
- политические мемы;
- скандалы без рыночного смысла;
- эмоциональные заголовки без последствий.

Главная мысль:

> Громкий заголовок — это не торговый план.

Хэштег: #шум_рынка

---

## POLITICAL MARKET NOISE SCORING

- base_score = 65;
- +20 если касается крипторегулирования;
- +20 если касается ETF / SEC / CFTC / MiCA;
- +15 если влияет на доллар / ставки / инфляцию;
- +15 если может повлиять на биржи / стейблкоины;
- +10 если уже есть реакция BTC/ETH;
- +10 если источник высокого доверия;
- -30 если нет связи с рынком;
- -40 если источник сомнительный;
- -30 если это просто политический скандал без последствий.

---

## SECTOR: SCAM RADAR

Использовать для:

- fake AI trading bots;
- guaranteed yield;
- fake airdrops;
- phishing;
- wallet drainers;
- fake exchange support;
- VIP-signals;
- fake profit screenshots;
- Ponzi;
- malicious extensions;
- deepfake crypto promotions;
- “пополни ещё, чтобы вывести”;
- фейковых комиссий на вывод.

Главная мысль:

> Самая прибыльная сделка дня — не нажать на левую ссылку.

Хэштеги:

- #скам_радар
- #безопасность_депозита

---

## SCAM RADAR SCORING

- base_score = 80;
- +20 если скам направлен на новичков;
- +20 если связан с AI / trading bot / guaranteed yield;
- +15 если есть риск фишинга / wallet drain;
- +15 если есть реальный пример схемы;
- +10 если можно дать чеклист защиты;
- +10 если источник высокого доверия;
- -30 если нельзя объяснить без непроверенных обвинений;
- -40 если источник сомнительный.

Скам-новости можно публиковать даже без прямого влияния на BTC, если они дают сильный урок новичку.

---

## SCAM LEGAL SAFETY

Запрещено без доказательств:

- “это точно мошенники”;
- “они украли деньги”;
- “100% скам”;
- “проект преступный”;
- “создатели воры”.

Разрешено:

- “есть признаки скама”;
- “похоже на мошенническую схему”;
- “красные флаги”;
- “обещание гарантированной прибыли — опасный признак”;
- “новичку лучше не подключать кошелёк”;
- “без официального источника доверять нельзя”;
- “это выглядит как схема с высоким риском”.

Если есть официальный источник: regulator warning, exchange warning, security report или расследование известной security-команды — можно писать жёстче, но аккуратно.

---

## SCAM HUMOR GUARD

Нельзя:

- шутить про выгоду преступлений;
- романтизировать мошенников;
- писать “неплохая математика” про украденные деньги;
- высмеивать жертв.

Лучший hamster_part для scam/security:

- “А вдруг меня это не касается? Я же не крупный инвестор.”
- “Ну я-то точно не попадусь.”
- “Сайт красивый, значит можно доверять?”

---

## EXAMPLE: AI X CRYPTO

```html
<b>🤖 AI снова пришёл в крипту: технология или хайп?</b>

<b>Коротко:</b>
CEO инфраструктурной компании говорит, что крипта лучше подходит AI-агентам, чем людям: программируемые платежи, смарт-контракты и операции без банковских посредников. Идея звучит сильно, но пока это скорее долгосрочный нарратив, чем повод нажимать Buy.

<b>Главные моменты:</b>
• AI-агенты могут использовать крипту для автономных платежей;
• инфраструктурные компании активно продвигают этот сценарий;
• рынок любит такие нарративы, но часто перегревает их раньше реального adoption.

<b>Почему это важно:</b>
• AI x Crypto остаётся сильной темой;
• интересная технология не равна сделке;
• новичкам легко купить красивую историю вместо понятного плана.

🐹 <b>Мысль новичка:</b>
AI + crypto звучит так, будто надо срочно искать кнопку Buy.

🤖 <b>AI-наставник:</b>
Сложные слова не делают идею безопасной. Сначала проверяй: есть ли продукт, пользователи, понятная экономика и реальная польза токена.

⚠️ <b>Ошибка новичка:</b>
Покупать слово “AI”, а не разбирать проект.

📌 <b>Вывод:</b>
AI-сектор интересен, но хайп — это не торговый план.

<i>Не финсовет. Это дневник обучения и AI-разбор.</i>

#AI_и_крипта #криптоновости #обучение
```

---

## EXAMPLE: SECURITY / HACK

```html
<b>⚠️ Litecoin пережил атаку: паниковать или выдохнуть?</b>

<b>Коротко:</b>
В сети Litecoin нашли уязвимость, которой воспользовались злоумышленники. Проблема затронула необновлённые ноды и часть MWEB-транзакций. Разработчики быстро выпустили патч, а сеть вернулась к нормальной работе.

<b>Главные моменты:</b>
• атакующие использовали уязвимость;
• часть нод принимала некорректные транзакции;
• сеть пережила реорганизацию;
• патч уже выпущен.

<b>Почему это важно:</b>
• такие новости бьют по доверию к инфраструктуре;
• рынок не любит слова “bug”, “attack”, “reorg”;
• если команда быстро реагирует, долгий ущерб может быть ограничен.

🐹 <b>Мысль новичка:</b>
Когда вижу такие заголовки, первая мысль — “всё, монете конец”.

🤖 <b>AI-наставник:</b>
Не каждая техническая проблема означает смерть проекта. Смотри на масштаб ущерба, скорость реакции команды и последствия для пользователей.

⚠️ <b>Ошибка новичка:</b>
Путать громкий заголовок с полной катастрофой и принимать решение на панике.

📌 <b>Вывод:</b>
Новость важная, но это повод разобраться, а не нажимать кнопки на эмоциях.

<i>Не финсовет. Это дневник обучения и AI-разбор.</i>

#Litecoin #LTC #криптоновости #безопасность
```

---

## EXAMPLE: SCAM RADAR

```html
<b>🕵️ Скам-радар: прибыль обещают, риски прячут</b>

<b>Коротко:</b>
В крипте снова всплыла схема с обещанием стабильной доходности через “AI-бота”. Такие истории часто выглядят технологично, но давят на одну и ту же кнопку: желание новичка быстро заработать без понимания риска.

<b>Главные моменты:</b>
• обещают доходность;
• нет прозрачной статистики;
• требуют срочно пополнить баланс;
• риски объясняют размыто.

<b>Почему это важно:</b>
• такие схемы часто бьют именно по новичкам;
• красивые слова вроде “AI” и “бот” не отменяют риск;
• обещание гарантированной прибыли — красный флаг.

🐹 <b>Мысль новичка:</b>
“А вдруг правда? Там же график красивый.”

🤖 <b>AI-наставник:</b>
Красивый интерфейс не делает схему безопасной. Если тебе обещают доходность без риска — риск, скорее всего, просто спрятали от тебя.

⚠️ <b>Ошибка новичка:</b>
Верить скриншоту прибыли больше, чем проверке источника.

📌 <b>Вывод:</b>
Самая прибыльная сделка дня — не нажать на левую ссылку.

<i>Не финсовет. Это дневник обучения и AI-разбор.</i>

#скам_радар #безопасность_депозита #не_будь_хомяком
```

---

## REVIEW FLOW RULES FOR NEWS

Под preview должны быть кнопки:

- ✅ Опубликовать
- ✏️ Исправить
- 🔁 Перегенерировать
- 🖼 Сгенерировать картинку
- ❌ Отклонить

Если владелец пишет:

- “сгенерируй изображение”;
- “сгенерируй тематическое изображение”;
- “добавь картинку”;
- “generate image”,

это image action, не text edit.

Если Claude вернул invalid JSON при edit/regenerate:

- НЕ публиковать;
- status draft остаётся pending_review или revision_failed;
- показать владельцу ошибку;
- предложить повторить правку или опубликовать старую версию отдельной кнопкой.
