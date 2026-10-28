# Агент референсов: как канал отдаёт картинки в генерацию

Техническая документация модуля, который **хранит, выбирает и передаёт референсы** стиля канала в текстовый агент и в модели картинок (VseGPT → KIE GPT Image 2).

Референсы привязаны к **конкретному каналу** (`Workspace`), не к глобальному проекту.

---

## 1. Назначение

| Задача | Что делает |
|--------|------------|
| Хранение | До 8 картинок на канал в `Workspace.reference_images_json` + файлы на диске |
| Промпт стиля | Vision (Claude): до 4 картинок base64 → пересборка `visual_style_prompt` |
| Генерация поста | URL референсов + имена → в user-message агента + в `image_input` у модели картинки |
| Пример стиля | Те же URL при «Сгенерировать пример» на странице канала |

---

## 2. Ключевые файлы

| Роль | Файл |
|------|------|
| Модель БД | `webapp/models.py` → поле `reference_images_json` |
| CRUD референсов, сжатие, URL, base64 | `webapp/services/workspace_visual.py` |
| HTTP: upload / delete / style-preview | `webapp/workspaces.py` |
| Vision → промпт стиля | `webapp/services/workspace_ai.py` |
| Сбор payload для генерации поста | `webapp/smm.py` → `_workspace_visual_payload` |
| Пайплайн картинки | `webapp/services/pipeline.py` → `_generate_visuals` |
| Правило реальных фото, фильтр localhost, `image_input` | `run_agent.py` |
| Лимит размера запроса | `webapp/config.py` → `MAX_CONTENT_LENGTH` (64 МБ) |
| UI | `webapp/templates/workspaces/edit.html` |

Правила поведения агента (текст):

- `docs/models/kie-visual-rules.md` — блок «Реальные фото из референсов»
- `docs/workflows/visual-decision.md` §5C
- `docs/workflows/visual-prompt-check.md` — этап 3
- константа `REAL_PHOTO_REFERENCE_RULE` в `run_agent.py`

---

## 3. Хранение данных

### 3.1. JSON в канале

Поле `Workspace.reference_images_json` — массив объектов:

```json
[
  {
    "id": "ref_1738000000000",
    "name": "портрет-лицо.jpg",
    "path": "workspace/3/refs/1738000000000_portret.jpg"
  }
]
```

- `id` — уникальный идентификатор для удаления в UI  
- `name` — исходное имя файла (для промпта агента)  
- `path` — путь **относительно** `UPLOAD_FOLDER / {user_id}/`

### 3.2. Файлы на диске

```
webapp/uploads/{user_id}/workspace/{workspace_id}/refs/{stamp}_{safe_name}.jpg
```

Лимиты:

| Константа | Значение | Где |
|-----------|----------|-----|
| `MAX_REFERENCES` | 8 | хранение на канал |
| `MAX_REFERENCES_FOR_AI` | 4 | vision при «ИИ генерация» стиля |
| `REF_ALLOWED_EXT` | png, jpg, jpeg, webp, gif | upload |
| `REF_MAX_SIDE_PX` | 2048 | сжатие при upload |
| `REF_JPEG_QUALITY` | 88 | сжатие |
| `MAX_CONTENT_LENGTH` | 64 МБ | весь HTTP-запрос |

При загрузке (`save_uploaded_reference`): крупные фото уменьшаются по длинной стороне до 2048 px и сохраняются как JPEG (GIF без перекодирования).

---

## 4. Два способа «отдать» референсы агенту

Система использует **два разных канала** — их нельзя путать.

**Жёсткое правило:** `vision_reference ≠ generation_reference`.  
То, что Claude увидел фото через base64, **не** значит, что image API получила reference.

### A. Vision (текст → промпт стиля)

**Когда:** кнопка «ИИ генерация» у поля `visual_style_prompt` на странице канала.

**Цепочка:**

1. `POST /workspaces/ai-generate-field` (+ `workspace_id`)
2. `load_reference_images` → `load_reference_images_b64` (до 4 файлов)
3. `workspace_ai.generate_workspace_field(..., reference_images=[...])`
4. В Claude уходит multimodal message: картинки base64 + текст задачи
5. Ответ — новый текст `visual_style_prompt` (при наличии референсов — **полная пересборка с нуля**)

Провайдер: предпочтительно прямой Anthropic; иначе KIE.

### B. Image generation (картинка / пример стиля / визуал поста)

**Когда:** генерация поста, «Сгенерировать пример», visual-only.

**Цепочка:**

1. `load_reference_images(ws)` + `resolve_reference_local_files` (абсолютные пути на диске)
2. Опционально `build_media_urls` (если URL публичный — можно сразу)
3. **Перед API call** в `run_agent.generate_image_url_with_fallback`:
   - `prepare_generation_reference_urls`: localhost URL отбрасываются; локальные файлы → **KIE File Upload** (`https://kieai.redpandaai.co/api/file-base64-upload`) → временный `downloadUrl`
   - лог `GENERATION REFERENCE AUDIT` (VISION vs GENERATION counts, EXTERNALLY ACCESSIBLE, IMAGE_INPUT SENT)
4. Если `reference_required` и generation refs = 0 → статус `REAL_PERSON_REFERENCE_UNAVAILABLE` (fail-safe: сцена без человека, без подмены лица текстом)
5. Если refs есть → модель **`gpt-image-2-image-to-image`** с полем `input_urls` (не text-to-image + не VseGPT)
6. VseGPT используется **только** когда generation refs не нужны / недоступны (он не принимает image references)

### Критерий готовности (localhost)

В логах при реальном фото Ксении должно быть:

```
VISION REFERENCES: > 0
GENERATION REFERENCES: > 0
EXTERNALLY ACCESSIBLE: yes
IMAGE_INPUT SENT: https://tempfile.redpandaai.co/...
```

Если ушёл только текстовый prompt без `input_urls` — тест **не пройден**.

---

## 5. Поток генерации поста (схема)

```
Канал (Workspace)
  ├─ visual_style_prompt          → текст фирменного стиля
  └─ reference_images_json        → список файлов
           │
           ▼
smm._workspace_visual_payload()
  ├─ visual_style_prompt (+ правила маркетолога)
  ├─ reference_image_urls   (до 8)
  └─ reference_image_names  (до 8)
           │
           ▼
pipeline.run_generation / run_visual_for_draft
           │
     ┌─────┴─────┐
     ▼           ▼
  Текст (Claude)   Картинка (VseGPT→KIE)
  build_user_message:
  - имена + URL в блоке стиля
  - REAL_PHOTO_REFERENCE_RULE
                   │
                   ▼
            _generate_visuals:
            - filter localhost
            - append_real_photo_reference_rule
            - generate_image_url_with_fallback(
                  image_vd,
                  reference_image_urls=...
              )
                   │
                   ▼
            build_image_payload → input.image_input
```

---

## 6. Правило поведения агента (реальные фото)

Код: `REAL_PHOTO_REFERENCE_RULE` в `run_agent.py`.

Если среди референсов есть реальные фото (особенно **люди / животные**):

1. Сначала выбрать **наиболее подходящее** реальное фото (ракурс, эмоция, жест, план).
2. Подать как `image_input`: **сохранить лицо и тело** персонажа.
3. Генеративно менять в основном **сцену вокруг** (фон, реквизит, свет, инфографика).
4. Другой ракурс → искать **другое реальное фото**, не «поворачивать» генерацией.
5. Нет подходящего фото → не выдумывать лицо; ближайший кадр или сцена без персонажа / силуэт.
6. В промпте KIE явно указать: какой референс — основа персонажа и что менять вокруг.

Правило подмешивается:

- в user-message текстового агента (если есть refs);
- в финальный image-prompt пайплайна и style-preview (если после фильтра есть публичные URL).

---

## 7. HTTP API (страница канала)

| Метод | Путь | Назначение |
|-------|------|------------|
| `POST` | `/workspaces/<id>/visual-refs/upload` | Загрузка файлов (`reference_uploads`) |
| `POST` | `/workspaces/<id>/visual-refs/<ref_id>/delete` | Удаление |
| `POST` | `/workspaces/<id>/style-preview/start` | Пример стиля + refs из БД |
| `POST` | `/workspaces/ai-generate-field` | ИИ-поле; для стиля — vision по refs |

Ответы AJAX при ошибках CSRF / 413 — JSON `{ok:false, error:"..."}` (см. обработчики в `webapp/__init__.py`).

---

## 8. Важные ограничения

1. **Один канал = свои референсы.** Нельзя подставлять refs другого `workspace_id`.
2. **`vision_reference ≠ generation_reference`.** Base64 для Claude не заменяет `input_urls` для image API.
3. **Localhost URL** (`127.0.0.1`) во внешний API не уходят. На локальной разработке локальные файлы заливаются в KIE tempfile (`file-base64-upload` → `downloadUrl`), затем в `gpt-image-2-image-to-image`.
4. **VseGPT не принимает image references.** При наличии generation refs пайплайн идёт сразу в KIE image-to-image.
5. При смене референсов промпт стиля нужно **пересобрать с нуля** («ИИ генерация»), не «чуть улучшить» старый.
6. MIME определяется по **содержимому файла**, не только по расширению (`detect_image_media_type`).
7. Слишком большой пакет файлов → HTTP 413; рекомендуется грузить по 1–2 фото за раз.
8. **Fail-safe:** если нужен реальный персонаж, а generation reference недоступен → `REAL_PERSON_REFERENCE_UNAVAILABLE`, сцена без человека (не подмена «похожей женщиной» по тексту).

---

## 9. Чек-лист проверки

- [ ] В канале есть refs в UI и в `reference_images_json`
- [ ] Файлы лежат под `webapp/uploads/{user_id}/workspace/{id}/refs/`
- [ ] После «ИИ генерация» стиля в промпте есть правило про реальные фото / палитру с рефов
- [ ] Job генерации: в input есть `reference_image_urls` (или хотя бы имена)
- [ ] Если хост публичный — в image payload есть `image_input`
- [ ] Если хост localhost — `image_input` пустой (ожидаемо), стиль из текста промпта

---

## 10. Точки входа в коде (быстрый поиск)

```text
workspace_visual.load_reference_images
workspace_visual.build_media_urls
workspace_visual.load_reference_images_b64
workspace_visual.save_uploaded_reference
smm._workspace_visual_payload
pipeline._generate_visuals
run_agent.filter_public_reference_urls
run_agent.append_real_photo_reference_rule
run_agent.build_image_payload  → input.image_input
run_agent.REAL_PHOTO_REFERENCE_RULE
```
