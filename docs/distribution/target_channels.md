# Целевые каналы для outreach @ai_deposit_diary

Список русскоязычных TG-каналов, чьи аудитории пересекаются с нашей целевой
(новички в крипте, обучение, риск-менеджмент). Используется скриптом
`scripts/distribution_outreach.py` для печати топа кандидатов на следующую
неделю outreach.

## Формат записи

Каждый канал — отдельная YAML-секция (одна запись = `---` разделитель).

```yaml
---
username: "@example_channel"
title: "Название канала"
subscribers_estimate: 5000          # приблизительно, владелец проверяет вручную
relevance_score: 8                  # 1-10, как близко тематика к нашей
last_post_age_days: 3               # давность последнего поста; >30 = мёртвый
overlap_topics:                     # пересечения с нашими рубриками
  - "обучение"
  - "новости_крипты"
owner_contact: "@username_owner"    # ник владельца канала / админа
contact_method: "tg_dm"             # tg_dm | comment | guest_post_form
outreach_template: "exchange"       # см. outreach_templates.md
notes: "Текстовые заметки"
status: "todo"                      # todo | contacted | responded | declined | accepted | done
last_contacted_at: ""               # ISO date или ""
```

## Стратегия (читай перед заполнением)

**Цель:** довести канал с 3 до 100 подписчиков за 4-6 недель через 3 механики:

1. **Обмен аудиториями** (`exchange`) — пишешь админу другого канала
   аналогичного размера, договариваешься о взаимном анонсе.
2. **Гостевой пост** (`guest_post`) — пишешь длинный полезный пост
   под чужим брендом, в конце ссылка на наш канал.
3. **Активный комментинг** (`comments`) — пишешь содержательные комментарии
   под чужими постами с подписью «@ai_deposit_diary» (не спам — реально
   разбираешь чужой пост).

**Какие каналы НЕ брать в список:**
- Сигнальщики, инфоцыгане, «гарантированные иксы» — ауд. не наша.
- Мёртвые (>30 дней без постов).
- Слишком крупные (>50k) — не ответят. Целимся в 1-15k.
- Слишком мелкие (<500) — overhead на коммуникацию не оправдан.

## Список

<!-- НАЧИНАЙ ЗАПОЛНЯТЬ ОТСЮДА. Удали примеры ниже когда добавишь хотя бы 5 реальных. -->

<!--

---
username: "@example_crypto_school"
title: "Крипто-школа для новичков"
subscribers_estimate: 4500
relevance_score: 9
last_post_age_days: 2
overlap_topics:
  - "обучение"
  - "риск_менеджмент"
owner_contact: "@example_admin"
contact_method: "tg_dm"
outreach_template: "exchange"
notes: "Регулярный обр. контент, ауд. совпадает на 80%"
status: "todo"
last_contacted_at: ""

---
username: "@example_news_neyt"
title: "Крипто без хайпа"
subscribers_estimate: 8200
relevance_score: 7
last_post_age_days: 1
overlap_topics:
  - "новости_крипты"
  - "макро"
owner_contact: "@example_owner2"
contact_method: "tg_dm"
outreach_template: "exchange"
notes: "Нейтральный тон, без сигналов — близко по духу"
status: "todo"
last_contacted_at: ""

-->

## История outreach

После каждой выполненной коммуникации меняй `status` и проставляй
`last_contacted_at` в формате `YYYY-MM-DD`. Лог тут — для рефлексии:
кто ответил, кто слил, что сработало.
