# Задача: пакетная генерация 4 вариантов эмблемы канала

## Контекст

Канал @ai_deposit_diary («Депозит под надзором ИИ») меняет визуальный стиль.
Текущий аватар (парень + AI-голограмма + свечной фон) выглядит как стоковый AI-арт.

Новое направление — **эмблема, а не сцена**:
- ОДИН фирменный знак, без людей, без хомяков, без свечного графика на фоне.
- Главный символ — стилизованная диафрагма/глаз/прицел, в центре которого японская свеча.
  Метафора: «под надзором». Диафрагма = «AI наблюдает», свеча = «рынок под наблюдением».
- Палитра: тёмно-серый или почти-чёрный фон + ОДИН тёплый акцент (охра, amber или приглушённое золото).
  НЕ неон, НЕ синий, НЕ cyberpunk. Чтобы перестало выглядеть как AI-сток.
- Композиция читается в круглом аватаре Telegram на 40px.

## Что переписать в scripts/generate_avatar.py

1. **PROMPT** — заменить на промпт для эмблемы. Английский, ~6-10 строк. Жёстко прописать:
   - "geometric emblem", "single symbol", "no people", "no humanoid figures",
     "no hamsters", "no animals", "no chart background", "no text", "no letters",
     "no cyberpunk", "no neon"
   - "stylized aperture / iris diaphragm with a single japanese candlestick at the center"
   - "warm amber or ochre accent on dark charcoal background, two colors only"
   - "minimal vector-style geometric design, flat, readable at 40px"
   - "centered composition for a circular Telegram avatar"

2. **Пакетная генерация**: вместо одного файла `channel_avatar.png` — сохранять 4 варианта
   в `outputs/images/avatar_candidates/`:
   - `emblem_01.png`, `emblem_02.png`, `emblem_03.png`, `emblem_04.png`
   - Перед записью — очистить папку (удалить старые `emblem_*.png`).
   - Цикл из 4 отдельных вызовов `client.images.generate(...)` — НЕ `n=4`, потому что
     gpt-image-2 на это может ругаться, а fallback gpt-image-1 поддерживает только n=1.
   - Если хотя бы один вызов упал — продолжать, не падать на первой ошибке.
     В конце вернуть список успешных файлов.

3. **Отправка владельцу**: вместо одного `send_photo` — отправить **media group**
   (aiogram `send_media_group` + `InputMediaPhoto`) с подписью только у первой картинки:
   ```
   🖼 [AVATAR CANDIDATES — EMBLEM]
   Модель: <code>{model_used}</code>
   Файлы: outputs/images/avatar_candidates/emblem_*.png

   Выбери номер (1–4), и я поставлю через setChatPhoto.
   ```
   Если успешно сгенерировался только 1 файл — отправить как обычное `send_photo`.

4. **Сигнатура `main()`**: остаётся `int`. Возвращать 0 если ≥1 файл сгенерирован,
   1 если все 4 упали.

5. **Не трогать**:
   - `_ThreadedResolverSession` (для aiodns на Windows — память подтверждает, что нужен).
   - Fallback `gpt-image-2 → gpt-image-1`.
   - `OWNER_CHAT_ID` / `TELEGRAM_TOKEN` из `.env`.
   - Загрузку `dotenv`.

6. **Не добавлять**:
   - Никакого argparse. Запуск без аргументов.
   - Никаких новых зависимостей.
   - Никаких docstring длиннее одной строки.

## Контекстный файл

`scripts/generate_avatar.py` — приложен. Перепиши его целиком в одном Python-блоке.

## Тесты не нужны

Это разовый скрипт генерации картинки, не часть продакшен-пайплайна. Запускается вручную.
