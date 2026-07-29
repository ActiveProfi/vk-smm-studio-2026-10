# Точка восстановления: блок рубрик VK (полный цикл)

**Дата фиксации:** 29.05.2026  
**Назначение:** приложение к полному снимку — только блок рубрик VK.  
**Полный откат всего проекта:** см. `CHECKPOINT-FULL-PROJECT-2026-05-29.md` и `VK-FULL-PROJECT-CHECKPOINT-2026-05-29.zip`.  
**Статус:** все 9 типов рубрик проработаны, пакет для переноса собран.

---

## 1. Что считается «готово» на этой точке

- Для каждой рубрики есть утверждённые **пост + визуал** (где применимо — **статья + обложка**).
- Все тексты постов — **чистые** (без markdown `#`, без служебных блоков в файлах публикации).
- Единый **HTML для переноса** с кликабельными ссылками на тексты и картинки.
- Промпты и правила проекта обновлены под фирменный стиль, двойную проверку, разделение пост/статья.
- **Supabase** намеренно не трогали (по решению пользователя).

---

## 2. Главный файл для копирования в другой проект

| Файл | Назначение |
|------|------------|
| `output/rubrics-transfer-links.html` | Все рубрики: промпты, нейросети, ссылки на посты и визуалы, тексты внутри HTML |

Открыть в браузере → скопировать или передать файл целиком.

---

## 3. Матрица рубрик (что входит в блок)

| Рубрика | Пост | Визуал поста | Статья | Обложка статьи | Примечание |
|---------|------|--------------|--------|----------------|------------|
| `razbor` | ✓ | ✓ | — | — | ранний эталон |
| `law_review` | ✓ | ✓ | — | — | ранний эталон |
| `case` | ✓ | ✓ | ✓ | ✓ | реальный кейс, без «учебный пример» |
| `expert` | ✓ | ✓ | ✓ | ✓ | advanced-шаблоны |
| `calculation` | ✓ | ✓ | ✓ | ✓ | advanced-шаблон расчёта |
| `serial` (+ `yumor`) | ✓ | ✓ | **нет** | **нет** | сезон 1 серия 1; юмор в комиксе v2 |
| `poll` | ✓ | ✓ | — | — | |
| `checklist` | ✓ | ✓ | **нет** | **нет** | |
| `article_announcement` | ✓ (анонс) | ✓ | ссылка на готовую статью | обложка из calculation | в посте `[ссылка на статью]` |

---

## 4. Ключевые файлы `output/` (исходники)

### 4.1. Пакет и контроль

- `output/rubrics-transfer-links.html` — **главный перенос**
- `output/rubrics-transfer-verified-only.md` — старая md-версия (если есть; HTML приоритетнее)

### 4.2. Индексы утверждённых материалов (серия 2026)

- `output/serial-yumor-s1-ep01-approved-index.txt`
- `output/poll-post-nds-reporting-approved-index.txt`
- `output/checklist-post-vychet-confirmation-approved-index.txt`
- `output/article-announcement-separate-accounting-medical-and-22-approved-index.txt`

### 4.3. Посты (чистые, `*-post-draft.txt`)

- `output/case-post-usn-22-vychet-draft.txt`
- `output/expert-post-zero-rate-nds-v2-by-user-prompt.txt`
- `output/calculation-post-separate-accounting-medical-and-22-draft.txt`
- `output/serial-yumor-s1-ep01-post-draft.txt`
- `output/poll-post-nds-reporting-post-draft.txt`
- `output/checklist-post-vychet-confirmation-post-draft.txt`
- `output/article-announcement-separate-accounting-medical-and-22-post-draft.txt`

### 4.4. Статьи

- `output/case-article-usn-22-vychet-draft.txt`
- `output/expert-article-zero-rate-nds-by-user-prompt.txt`
- `output/calculation-article-separate-accounting-medical-and-22-draft.txt`

### 4.5. Сериал (дополнительно)

- `output/serial-yumor-s1-separate-accounting-season-plan.txt` — план 10 серий
- `output/serial-yumor-s1-ep01-carousel.txt`
- `output/serial-yumor-s1-ep01-video-script.txt`
- `output/serial-yumor-s1-ep01-visual-prompt-v2.txt` — утверждённый промпт комикса

### 4.6. Анонс статьи

- `output/article-announcement-separate-accounting-medical-and-22-source.txt` → статья `calculation-article-...`

---

## 5. Публичные ссылки на визуалы (из HTML)

Сохранены в `rubrics-transfer-links.html`. Дубль для быстрого доступа:

| Рубрика | URL |
|---------|-----|
| razbor | https://tempfile.aiquickdraw.com/p/60cf02877f81da8c77ab64038640e4d6_1_1779023083_9071.png |
| law_review | https://tempfile.aiquickdraw.com/p/eceae48177a529a624ed2d4c4817b448_1_1779024346_7717.png |
| case (пост) | https://tempfile.aiquickdraw.com/workers/nano/image_1780036976648_ql66lx.png |
| case (обложка) | https://tempfile.aiquickdraw.com/images/1780037700013-0oqfz1vm3c4.png |
| expert (пост) | https://tempfile.aiquickdraw.com/images/1780043189971-xukwc0p7f6s.png |
| expert (обложка) | https://tempfile.aiquickdraw.com/images/1780043876869-pbowbmz0o4.png |
| calculation (пост) | https://tempfile.aiquickdraw.com/p/381d7452647407f2406fcdb7b332654f_1_1780045541_5143.png |
| calculation (обложка) | https://tempfile.aiquickdraw.com/images/1780045791525-ora6aiw3ldj.png |
| serial (пост) | https://tempfile.aiquickdraw.com/p/dbece6f983707a84068ac13083e2321c_1_1780048411_7928.png |
| poll | https://tempfile.aiquickdraw.com/images/1780048879929-of8iyactx3c.png |
| checklist | https://tempfile.aiquickdraw.com/p/fbde260ffc37759b5a7042edf4aeebc4_1_1780049275_8246.png |
| article_announcement | https://tempfile.aiquickdraw.com/p/66fcf0ae081e4ba32be0833d6d054b18_1_1780049696_4061.png |

**Важно:** ссылки tempfile — временные. Для долгого хранения скачайте PNG и положите в свой архив/хостинг.

---

## 6. Промпты и правила (не откатывать случайно)

### Промпты рубрик

- `prompts/base-system-kie.md`
- `prompts/razbor.md`, `law_review.md`, `case.md`, `expert.md`, `calculation.md`
- `prompts/expert-advanced-template.md`, `expert-article-advanced-template.md`
- `prompts/calculation-advanced-template.md`
- `prompts/serial.md`, `serial-yumor-advanced-template.md`, `serial-comic-frames.md`
- `prompts/yumor.md` (объединён с serial)
- `prompts/poll.md`, `checklist.md`, `article_announcement.md`

### Workflow

- `docs/workflows/text-double-check.md`
- `docs/workflows/visual-prompt-check.md`
- `docs/workflows/pre-generation-checklist.md`

### Правила Cursor

- `.cursor/rules/vk-kie-agent.mdc`

### Персонаж

- `docs/characters/alina.md`

---

## 7. Как откатиться к этой точке (без Git)

Git-репозиторий в папке проекта **не инициализирован** (на дату фиксации).

### Шаг 1. Сделать резервную копию сейчас

Скопировать целиком папку проекта или минимум:

```
output/
prompts/
docs/checkpoints/
docs/workflows/
docs/characters/
.cursor/rules/
knowledge/nds-2026-facts.md
```

Имя архива: `VK-RUBRICS-CHECKPOINT-2026-05-29.zip` (уже создан в корне проекта, ~18 МБ)

### Шаг 2. Если что-то сломалось позже

1. Закрыть Cursor.
2. Восстановить папки из архива `VK-RUBRICS-CHECKPOINT-2026-05-29.zip` поверх текущих (или в новую папку).
3. Открыть `output/rubrics-transfer-links.html` — проверить, что 9 карточек рубрик на месте.
4. Сверить один файл, например `output/serial-yumor-s1-ep01-post-draft.txt`.

### Шаг 3. (Рекомендация на будущее)

Инициализировать Git и сделать коммит с меткой:

```text
git init
git add output prompts docs .cursor/rules knowledge
git commit -m "checkpoint: VK rubrics block complete 2026-05-29"
git tag checkpoint-vk-rubrics-2026-05-29
```

Тогда откат: `git checkout checkpoint-vk-rubrics-2026-05-29`

---

## 8. Открытые хвосты (не блокируют точку)

- В посте-анонсе: `[ссылка на статью]` — подставить URL перед публикацией.
- Supabase: запись черновиков отложена.
- Сезон serial: готова только **серия 1** из 10 (план сезона сохранён).
- Временные URL картинок — перескачать при переносе в прод.

---

## 9. Контекст чата

Полная переписка по шагам: agent-transcript `1a44b009-0971-43b5-92d5-d36cbf43c6d7` (папка agent-transcripts в Cursor).

---

**Конец точки восстановления.**
