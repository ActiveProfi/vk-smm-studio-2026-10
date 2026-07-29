"""Сиды и лёгкая миграция SQLite под каналы/рубрики."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, text

from webapp.models import Rubric, Workspace, db

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Стартовый набор рубрик для канала НДС (копируются тексты из prompts/)
DEFAULT_NDS_RUBRICS = [
    ("expert", "Экспертный пост", "expert.md"),
    ("razbor", "Разбор", "razbor.md"),
    ("case", "Кейс", "case.md"),
    ("calculation", "Расчёт", "calculation.md"),
    ("law_review", "Обзор изменений", "law_review.md"),
    ("checklist", "Чек-лист", "checklist.md"),
    ("poll", "Опрос", "poll.md"),
    ("serial", "Сериал", "serial.md"),
    ("yumor", "Юмор", "yumor.md"),
    ("article_announcement", "Анонс статьи", "article_announcement.md"),
]

# Универсальный минимальный набор для новой тематики
GENERIC_STARTER_RUBRICS = [
    (
        "expert",
        "Экспертный пост",
        "# Рубрика: экспертный пост\n\n"
        "Подготовь экспертный пост для VK по теме канала.\n"
        "Пиши коротко, по делу, без выдуманных фактов.\n"
        "Структура: тезис → почему важно → 2–3 примера → что сделать → мягкий CTA.\n"
        "Чистый текст для VK без markdown.\n",
    ),
    (
        "checklist",
        "Чек-лист",
        "# Рубрика: чек-лист\n\n"
        "Собери практический чек-лист для VK.\n"
        "5–9 пунктов, каждый — одно действие.\n"
        "Без выдуманных норм и цифр.\n"
        "Чистый текст для VK без markdown.\n",
    ),
    (
        "case",
        "Кейс",
        "# Рубрика: кейс\n\n"
        "Разбери короткую историю/ситуацию по теме канала.\n"
        "Структура: ситуация → ошибка или развилка → решение → вывод.\n"
        "Чистый текст для VK без markdown.\n",
    ),
]


def _read_prompt(filename: str) -> str:
    path = PROJECT_ROOT / "prompts" / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"# Рубрика\n\nПромпт-файл {filename} не найден. Опишите правила рубрики здесь.\n"


def _column_exists(table: str, column: str) -> bool:
    insp = inspect(db.engine)
    if table not in insp.get_table_names():
        return False
    return any(col["name"] == column for col in insp.get_columns(table))


def ensure_schema() -> None:
    """create_all + добавление недостающих колонок в старую SQLite."""
    db.create_all()
    alters = []
    if _column_exists("user", "id") and not _column_exists("user", "active_workspace_id"):
        alters.append("ALTER TABLE user ADD COLUMN active_workspace_id INTEGER")
    if _column_exists("user", "id") and not _column_exists("user", "plan_code"):
        alters.append("ALTER TABLE user ADD COLUMN plan_code TEXT DEFAULT 'free'")
    if _column_exists("user", "id") and not _column_exists("user", "plan_status"):
        alters.append("ALTER TABLE user ADD COLUMN plan_status TEXT DEFAULT 'trial'")
    if _column_exists("user", "id") and not _column_exists("user", "plan_updated_at"):
        alters.append("ALTER TABLE user ADD COLUMN plan_updated_at TEXT DEFAULT ''")
    if _column_exists("user", "id") and not _column_exists("user", "plan_channels_note"):
        alters.append("ALTER TABLE user ADD COLUMN plan_channels_note TEXT DEFAULT ''")
    if _column_exists("draft", "id") and not _column_exists("draft", "workspace_id"):
        alters.append("ALTER TABLE draft ADD COLUMN workspace_id INTEGER")
    if _column_exists("draft", "id") and not _column_exists("draft", "generation_warning"):
        alters.append("ALTER TABLE draft ADD COLUMN generation_warning TEXT DEFAULT ''")
    if _column_exists("draft", "id") and not _column_exists("draft", "agent_answer"):
        alters.append("ALTER TABLE draft ADD COLUMN agent_answer TEXT DEFAULT ''")
    if _column_exists("draft", "id") and not _column_exists("draft", "materials_text"):
        alters.append("ALTER TABLE draft ADD COLUMN materials_text TEXT DEFAULT ''")
    if _column_exists("workspace", "id") and not _column_exists("workspace", "visual_style_prompt"):
        alters.append("ALTER TABLE workspace ADD COLUMN visual_style_prompt TEXT DEFAULT ''")
    if _column_exists("workspace", "id") and not _column_exists("workspace", "reference_images_json"):
        alters.append("ALTER TABLE workspace ADD COLUMN reference_images_json TEXT DEFAULT ''")
    if _column_exists("workspace", "id") and not _column_exists("workspace", "visual_style_preview_url"):
        alters.append("ALTER TABLE workspace ADD COLUMN visual_style_preview_url TEXT DEFAULT ''")
    if _column_exists("workspace", "id") and not _column_exists("workspace", "marketer_resume"):
        alters.append("ALTER TABLE workspace ADD COLUMN marketer_resume TEXT DEFAULT ''")
    if _column_exists("workspace", "id") and not _column_exists("workspace", "marketer_rules_json"):
        alters.append("ALTER TABLE workspace ADD COLUMN marketer_rules_json TEXT DEFAULT ''")
    if _column_exists("workspace", "id") and not _column_exists("workspace", "marketer_updated_at"):
        alters.append("ALTER TABLE workspace ADD COLUMN marketer_updated_at TEXT DEFAULT ''")
    if _column_exists("workspace", "id") and not _column_exists("workspace", "package_code"):
        alters.append("ALTER TABLE workspace ADD COLUMN package_code TEXT DEFAULT 'business'")
    if _column_exists("workspace", "id") and not _column_exists("workspace", "package_posts_limit"):
        alters.append("ALTER TABLE workspace ADD COLUMN package_posts_limit INTEGER DEFAULT 25")
    if _column_exists("workspace", "id") and not _column_exists("workspace", "package_period_start"):
        alters.append("ALTER TABLE workspace ADD COLUMN package_period_start TEXT DEFAULT ''")
    if _column_exists("workspace", "id") and not _column_exists("workspace", "client_approve_token"):
        alters.append("ALTER TABLE workspace ADD COLUMN client_approve_token TEXT DEFAULT ''")
    if _column_exists("workspace", "id") and not _column_exists("workspace", "require_client_approval"):
        alters.append("ALTER TABLE workspace ADD COLUMN require_client_approval INTEGER DEFAULT 0")
    if _column_exists("workspace", "id") and not _column_exists("workspace", "auto_publish_enabled"):
        alters.append("ALTER TABLE workspace ADD COLUMN auto_publish_enabled INTEGER DEFAULT 0")
    if _column_exists("draft", "id") and not _column_exists("draft", "publish_with_image"):
        alters.append("ALTER TABLE draft ADD COLUMN publish_with_image INTEGER DEFAULT 1")
    if _column_exists("draft", "id") and not _column_exists("draft", "publish_with_video"):
        alters.append("ALTER TABLE draft ADD COLUMN publish_with_video INTEGER DEFAULT 0")
    if _column_exists("draft", "id") and not _column_exists("draft", "client_status"):
        alters.append("ALTER TABLE draft ADD COLUMN client_status TEXT DEFAULT 'none'")
    if _column_exists("draft", "id") and not _column_exists("draft", "client_comment"):
        alters.append("ALTER TABLE draft ADD COLUMN client_comment TEXT DEFAULT ''")
    if _column_exists("draft", "id") and not _column_exists("draft", "content_plan_id"):
        alters.append("ALTER TABLE draft ADD COLUMN content_plan_id INTEGER")
    for stmt in alters:
        db.session.execute(text(stmt))
    if alters:
        db.session.commit()


def seed_rubrics_from_nds_templates(workspace: Workspace) -> None:
    for i, (code, title, filename) in enumerate(DEFAULT_NDS_RUBRICS):
        db.session.add(
            Rubric(
                workspace_id=workspace.id,
                code=code,
                title=title,
                prompt_text=_read_prompt(filename),
                base_prompt_key=code,
                sort_order=i,
                is_active=True,
            )
        )


def seed_generic_rubrics(workspace: Workspace) -> None:
    for i, (code, title, prompt) in enumerate(GENERIC_STARTER_RUBRICS):
        db.session.add(
            Rubric(
                workspace_id=workspace.id,
                code=code,
                title=title,
                prompt_text=prompt,
                base_prompt_key=code,
                sort_order=i,
                is_active=True,
            )
        )


def ensure_default_workspace_for_user(user) -> Workspace:
    """Если у пользователя нет каналов — создать пустой универсальный стартовый канал."""
    existing = Workspace.query.filter_by(user_id=user.id).first()
    if existing:
        if not user.active_workspace_id:
            user.active_workspace_id = existing.id
            db.session.commit()
        return existing

    ws = Workspace(
        user_id=user.id,
        name="Мой канал",
        theme="",
        description="",
        brand_site="",
        search_hint="",
        knowledge_text="",
        vk_token=user.vk_token or "",
        vk_group_id=user.vk_group_id or "",
        is_active=True,
    )
    db.session.add(ws)
    db.session.flush()
    seed_generic_rubrics(ws)
    user.active_workspace_id = ws.id
    db.session.commit()
    return ws
