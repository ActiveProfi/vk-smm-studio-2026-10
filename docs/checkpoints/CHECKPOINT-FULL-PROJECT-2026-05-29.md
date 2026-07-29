# Точка восстановления: ВЕСЬ проект VK KIE (полный снимок)

**Дата:** 29.05.2026  
**Имя снимка:** `CHECKPOINT-FULL-PROJECT-2026-05-29`  
**Заменяет по смыслу:** узкий снимок только блока рубрик (см. также `CHECKPOINT-VK-RUBRICS-BLOCK-2026-05-29.md` как приложение).

---

## 1. Что это за проект

Полуавтоматический **контент-завод для ВКонтакте** по теме НДС (ООО «АктивПрофи», автоинтенсив nds04ka.online).

Связка: **Cursor + Python + KIE AI (Claude, Nano Banana Pro, Veo/Hailuo/Kling) + Supabase + VK API**.

Это не только «9 рубрик постов». В проекте есть:

- мультиагентная логика (`run_agent.py` по `post_type`);
- месячное планирование контента;
- генерация текста, картинок, видео;
- черновики и публикация в VK;
- база фактов, workflow-проверки, SQL-схемы Supabase;
- итоговые материалы по темам, архив предыдущей версии агента.

---

## 2. Архитектура (мультиагенты и оркестраторы)

```
Тема / план
    ↓
build_vk_month_plan.py  →  vk_month_plan.json, vk_topics.json
    ↓
run_vk_month_generation.py  →  contracts/*.json на каждый день
    ↓
run_agent.py  →  промпт по post_type + base-system + knowledge
    ↓         →  KIE Claude (текст)
    ↓         →  KIE image / video (визуал)
    ↓
output/*.txt, *.json  +  Supabase vk_drafts (опционально)
    ↓
publish_vk_*.py  →  публикация / отложка в VK
```

### Центральные скрипты (корень проекта)

| Файл | Роль |
|------|------|
| `run_agent.py` | Главный агент: JSON → текст → визуал → Supabase |
| `publish_vk_scheduled.py` | Публикация по расписанию (Supabase) |
| `publish_vk_browser_scheduled.py` | Публикация через браузер |
| `publish_vk_playwright_strict.py` | Строгая публикация статей (Playwright) |
| `requirements.txt` | Зависимости Python |

### Инструменты (`tools/`)

| Файл | Роль |
|------|------|
| `build_vk_month_plan.py` | Месячный план из тем + `configs/vk_schedule_month.json` |
| `run_vk_month_generation.py` | Пакетный запуск агента по плану |
| `generate_kie_image_from_prompt.py` | Картинка Nano Banana Pro по prompt-файлу |
| `audit_vk_plan_facts.py` | Аудит фактов в плане |
| `prepare_vk_article_editor.py` | Подготовка редактора статей VK |
| `publish_vk_article_strict.py` | Публикация статьи |
| `create_vk_test_draft_from_result.py` | Тестовые черновики |
| `mark_vk_test_draft_ready_local_image.py` | Локальная отметка ready |
| `test_vk_wall_post_text.py` | Тест поста на стену |

### Контракты входа (`contracts/`)

Шаблоны JSON для `run_agent.py`: `test-expert.json`, `test-case.json`, `agent-video-test.json`, `agent-input-template.json` и др.

### Конфиги (`configs/`)

- `vk_schedule_month.json` — расписание рубрик по дням
- `vk_fact_audit_rules.json` — правила аудита фактов

---

## 3. Карта папок проекта

| Папка / зона | Содержание |
|--------------|------------|
| `prompts/` | Промпты всех рубрик + base-system + advanced-шаблоны |
| `knowledge/` | `nds-2026-facts.md` — единственный источник цифр |
| `docs/workflows/` | text-double-check, visual-prompt-check, pre-generation-checklist, vk-article-publish, visual-decision |
| `docs/models/` | kie-text-model, kie-visual-rules |
| `docs/characters/` | alina.md (сериал) |
| `docs/checkpoints/` | точки восстановления |
| `.cursor/rules/` | `vk-kie-agent.mdc` — глобальные правила агента в Cursor |
| `output/` | **Все черновики, промпты визуала, ссылки KIE, планы, rubrics-transfer-links.html** |
| `Итоговые результаты/` | Опубликованные/утверждённые материалы по темам (структура папок по темам) |
| `Входящие материалы/` | Исходники и `vk_topics.json` |
| `АРХИВ_ТЕКУЩЕГО_АГЕНТА_VK_2026-04-23/` | Снимок агента до крупной доработки (126 файлов) |
| `Дизайн для VK/` | Планы и материалы по дизайну |
| `contracts/` | JSON-входы агента |
| `configs/` | Расписание и аудит |
| Корень `*.md` | Планы, чек-листы, инструкции запуска (см. раздел 4) |

---

## 4. Ключевая документация (корень и docs)

**Сборка и запуск агента**

- `ШАГИ_СБОРКИ_АГЕНТА.md`
- `КАК_ЗАПУСКАТЬ_АГЕНТА.md`
- `ЧЕК_ЛИСТ_АГЕНТОВ_И_ОРКЕСТРАТОРОВ_VK.md` — карта всех типов постов и статусов
- `ЧЕК_ЛИСТ_ДОСТУПОВ_КОНТЕНТ_ЗАВОД.md`
- `БЫСТРЫЕ_ДОСТУПЫ_ПРОЕКТА.md`
- `БАЗА_МАТЕРИАЛОВ_И_РЕЗУЛЬТАТОВ.md`

**Планирование контента**

- `ПЛАН_VK_НДС_автоинтенсив.md`
- `30 тем Базовые изменения НДС 2026.md`
- `РЕЗЮМЕ_ТЕКУЩЕГО_ЭТАПА_VK.md`

**API и интеграции (документация)**

- `Nano Banana Pro Api documentation.md`
- `Generate Veo3.1 Video.md`
- `VK mini app.md`
- `О сервисе Yandex Search API  Wordstat.md`

**Supabase (SQL в корне)**

- `supabase_vk_drafts.sql`
- `supabase_vk_content_intake.sql`
- `supabase_agent_runs.sql`
- миграции: `supabase_*_add_*.sql`

---

## 5. Промпты рубрик (`run_agent.py` → `PROMPT_BY_TYPE`)

| post_type | Файл промпта |
|-----------|----------------|
| expert | `prompts/expert.md` + `expert-advanced-template.md` |
| razbor | `prompts/razbor.md` |
| yumor | `prompts/yumor.md` (→ serial) |
| serial | `prompts/serial.md` + `serial-yumor-advanced-template.md` + `serial-comic-frames.md` |
| checklist | `prompts/checklist.md` |
| case | `prompts/case.md` |
| calculation | `prompts/calculation.md` + `calculation-advanced-template.md` |
| law_review | `prompts/law_review.md` |
| poll | `prompts/poll.md` |
| article_announcement | `prompts/article_announcement.md` |

Общий: `prompts/base-system-kie.md`

---

## 6. Блок VK-рубрик (проработан полностью на эту дату)

**Перенос:** `output/rubrics-transfer-links.html`

**Детали:** `docs/checkpoints/CHECKPOINT-VK-RUBRICS-BLOCK-2026-05-29.md`

9 рубрик с утверждёнными постами и визуалами; где нужно — статья + обложка. Без статьи: serial, poll, checklist.

---

## 7. Итоговые результаты (отдельно от output)

Папка `Итоговые результаты/` — материалы по темам, в т.ч.:

- `НДС - базовые понятия/`
- `НДС - коды видов операций/`
- шаблоны `ШАБЛОН ТЕМЫ/`, `ПРИМЕР ТЕМЫ/`

Имена файлов визуала с суффиксом нейросети (` - Nano Banana Pro` и т.д.) по правилам проекта.

---

## 8. Секреты и окружение (отдельное внимание при откате)

| Файл | Важность |
|------|----------|
| `.env` | KIE_API_KEY, Supabase, VK — **обязателен для работы скриптов** |
| `.env.example` | Шаблон без секретов |
| `*Api key*.txt`, `*token*.txt` в корне | Резервные записи ключей (не публиковать архив) |

В полном ZIP-архиве `.env` **включён** для личного отката на вашем ПК. **Не отправляйте архив посторонним.**

---

## 9. Что НЕ входит в полный ZIP (намеренно)

| Исключено | Причина |
|-----------|---------|
| `__pycache__/` | Кэш Python, восстанавливается сам |
| `.vk-browser-profile/` | Профиль браузера, очень большой, не код |
| `VK-RUBRICS-CHECKPOINT-2026-05-29.zip` | Старый частичный архив (вложенный дубликат) |
| `VK-FULL-PROJECT-CHECKPOINT-2026-05-29.zip` | Сам архив (если пересоздаёте) |

---

## 10. Файлы отката

| Артефакт | Путь |
|----------|------|
| Этот документ | `docs/checkpoints/CHECKPOINT-FULL-PROJECT-2026-05-29.md` |
| Краткая метка | `output/CHECKPOINT-RESTORE-POINT.txt` |
| **Полный ZIP** | `VK-FULL-PROJECT-CHECKPOINT-2026-05-29.zip` (корень проекта) |
| Узкий ZIP рубрик (устарел как «полный») | `VK-RUBRICS-CHECKPOINT-2026-05-29.zip` |

---

## 11. Как откатиться к этой точке

### Шаг 1

Скопировать `VK-FULL-PROJECT-CHECKPOINT-2026-05-29.zip` в безопасное место (облако / второй диск).

### Шаг 2

При поломке: переименовать текущую папку проекта (например, в `VK для ИНТЕНСИВОВ_broken`).

### Шаг 3

Распаковать ZIP в `...\Cursor\VK  для ИНТЕНСИВОВ\`.

### Шаг 4

Проверить:

1. `run_agent.py` открывается;
2. `output/rubrics-transfer-links.html` — 9 рубрик;
3. `docs/checkpoints/CHECKPOINT-FULL-PROJECT-2026-05-29.md` на месте;
4. `.env` на месте (если скрипты не стартуют — восстановить `.env` из бэкапа).

### Шаг 5 (рекомендация на будущее)

```text
git init
git add .
git commit -m "checkpoint: full project 2026-05-29"
git tag checkpoint-full-2026-05-29
```

Откат: `git checkout checkpoint-full-2026-05-29`

---

## 12. Состояние на дату снимка

| Компонент | Статус |
|-----------|--------|
| run_agent.py v1 | рабочий |
| Месячный план | v1 |
| 9 рубрик VK (контент-эталоны) | утверждены в output + HTML |
| Supabase в прод-потоке | отложено по решению пользователя |
| serial сезон 1 | только серия 1 из 10 |
| Git | не инициализирован |

---

## 13. Контекст переписки Cursor

Транскрипт: `1a44b009-0971-43b5-92d5-d36cbf43c6d7` (agent-transcripts).

---

**Конец полного снимка проекта.**
