"""Модели: пользователи, каналы ВК, рубрики, черновики."""
from datetime import datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt

db = SQLAlchemy()
bcrypt = Bcrypt()


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    # устаревшие поля (оставлены для совместимости; основной источник — Workspace)
    vk_token = db.Column(db.Text, default="")
    vk_group_id = db.Column(db.String(64), default="")
    active_workspace_id = db.Column(db.Integer, db.ForeignKey("workspace.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Тариф кабинета (заглушка оплаты, без реального списания)
    plan_code = db.Column(db.String(32), default="free")  # free|standard|pro|agency
    plan_status = db.Column(db.String(32), default="trial")  # trial|active|test_paid|none
    plan_updated_at = db.Column(db.String(32), default="")
    plan_channels_note = db.Column(db.String(120), default="")  # текст для теста, напр. «2×business»
    privacy_accepted_at = db.Column(db.String(32), default="")

    drafts = db.relationship(
        "Draft",
        backref="author",
        lazy=True,
        foreign_keys="Draft.user_id",
    )
    workspaces = db.relationship(
        "Workspace",
        backref="owner",
        lazy=True,
        foreign_keys="Workspace.user_id",
    )

    def set_password(self, password: str) -> None:
        self.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")

    def check_password(self, password: str) -> bool:
        return bcrypt.check_password_hash(self.password_hash, password)

    def get_active_workspace(self):
        from webapp.services import access as acc

        if self.active_workspace_id:
            ws = db.session.get(Workspace, self.active_workspace_id)
            if ws and acc.can_access_workspace(self, ws):
                return ws
        first = acc.list_workspaces(self).first()
        if first:
            return first
        return (
            Workspace.query.filter_by(user_id=self.id, is_active=True)
            .order_by(Workspace.id.asc())
            .first()
        )


class TeamMember(db.Model):
    """Сотрудник агентства: доступ к каналам владельца (agency_user_id)."""

    __tablename__ = "team_member"

    id = db.Column(db.Integer, primary_key=True)
    agency_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    role = db.Column(db.String(32), default="manager")  # manager | viewer
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    agency = db.relationship("User", foreign_keys=[agency_user_id])
    member = db.relationship("User", foreign_keys=[user_id])


class Workspace(db.Model):
    """Канал / сообщество ВК со своей тематикой и рубриками."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    theme = db.Column(db.String(300), default="")  # кратко: НДС, маркетинг…
    description = db.Column(db.Text, default="")
    brand_site = db.Column(db.String(200), default="")
    search_hint = db.Column(db.String(300), default="")  # уточнение для веб-поиска
    knowledge_text = db.Column(db.Text, default="")  # своя база фактов канала
    visual_style_prompt = db.Column(db.Text, default="")  # промпт визуального стиля канала
    reference_images_json = db.Column(db.Text, default="")  # JSON: референсы для стиля
    visual_style_preview_url = db.Column(db.String(1000), default="")  # пример картинки для утверждения
    # Резюме для менеджера + правила агентов (копирайтер / редактор / визуал) от ИИ-маркетолога
    marketer_resume = db.Column(db.Text, default="")
    marketer_rules_json = db.Column(db.Text, default="")
    marketer_updated_at = db.Column(db.String(64), default="")
    # Пакет услуг агентства
    package_code = db.Column(db.String(32), default="business")  # start|business|premium|custom|none
    package_posts_limit = db.Column(db.Integer, default=25)  # 0 = без лимита
    package_period_start = db.Column(db.String(32), default="")  # YYYY-MM-DD
    # Согласование с клиентом (ссылка на страницу планов)
    client_approve_token = db.Column(db.String(64), default="")
    require_client_approval = db.Column(db.Boolean, default=False)
    # Автопубликация due-постов
    auto_publish_enabled = db.Column(db.Boolean, default=False)
    vk_token = db.Column(db.Text, default="")
    vk_group_id = db.Column(db.String(64), default="")
    # VK Реклама (ads.vk.com): токен API + подпись кабинета для менеджера
    vk_ads_token = db.Column(db.Text, default="")
    vk_ads_account_id = db.Column(db.String(64), default="")
    vk_ads_client_id = db.Column(db.String(128), default="")
    vk_ads_client_secret = db.Column(db.Text, default="")
    vk_ads_refresh_token = db.Column(db.Text, default="")
    vk_ads_token_expires_at = db.Column(db.String(32), default="")  # unix time
    vk_ads_status = db.Column(db.String(32), default="")  # connected|error|""
    vk_ads_last_error = db.Column(db.Text, default="")
    vk_ads_connected_at = db.Column(db.String(64), default="")
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    rubrics = db.relationship(
        "Rubric",
        backref="workspace",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="Rubric.sort_order",
    )
    drafts = db.relationship("Draft", backref="workspace", lazy=True)
    content_plans = db.relationship(
        "ContentPlanBatch",
        backref="workspace",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="ContentPlanBatch.id.desc()",
    )


class ContentPlanBatch(db.Model):
    """Контент-план целиком — его согласовывает клиент (не каждый пост)."""

    __tablename__ = "content_plan_batch"

    id = db.Column(db.Integer, primary_key=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspace.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(200), default="")
    start_date = db.Column(db.String(32), default="")
    days = db.Column(db.Integer, default=7)
    items_json = db.Column(db.Text, default="[]")  # темы, даты, рубрики
    audience_summary = db.Column(db.Text, default="")
    timing_logic = db.Column(db.Text, default="")
    # none | pending | approved | rejected
    client_status = db.Column(db.String(32), default="pending")
    client_comment = db.Column(db.Text, default="")
    # черновики уже созданы в календаре из этого плана
    saved_to_calendar = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Rubric(db.Model):
    """Рубрика канала: свой код, название и промпт генерации."""

    id = db.Column(db.Integer, primary_key=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspace.id"), nullable=False)
    code = db.Column(db.String(64), nullable=False)  # латиница, для внутренних ссылок
    title = db.Column(db.String(120), nullable=False)
    prompt_text = db.Column(db.Text, default="")
    base_prompt_key = db.Column(db.String(64), default="")  # из какого шаблона создали
    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Draft(db.Model):
    """Черновик поста для предпросмотра и публикации из веб-интерфейса."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspace.id"), nullable=True)
    content_plan_id = db.Column(db.Integer, db.ForeignKey("content_plan_batch.id"), nullable=True)
    topic = db.Column(db.String(300), default="")
    post_type = db.Column(db.String(64), default="expert")
    tone = db.Column(db.String(200), default="")
    post_text = db.Column(db.Text, default="")
    image_url = db.Column(db.String(1000), default="")
    video_url = db.Column(db.String(1000), default="")
    publish_with_image = db.Column(db.Boolean, default=True)
    publish_with_video = db.Column(db.Boolean, default=False)
    search_notes = db.Column(db.Text, default="")
    relevance_report = db.Column(db.Text, default="")
    generation_warning = db.Column(db.Text, default="")  # почему не получился визуал
    agent_answer = db.Column(db.Text, default="")  # полный ответ модели — для догенерации визуала
    materials_text = db.Column(db.Text, default="")  # материалы — чтобы продолжить с черновика
    status = db.Column(db.String(32), default="draft")
    # planned = из контент-плана (тема+дата); draft = в работе;
    # generating / ready / published / error — конвейер варианта B
    scheduled_for = db.Column(db.String(64), default="")
    vk_post_id = db.Column(db.String(64), default="")
    # устаревшие поля поста (согласование теперь на уровне ContentPlanBatch)
    client_status = db.Column(db.String(32), default="none")
    client_comment = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    content_plan = db.relationship("ContentPlanBatch", backref="drafts", lazy=True)


class ApiUsageLog(db.Model):
    """Учёт расходов API по каналу (оценка в рублях для агентства)."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspace.id"), nullable=True)
    kind = db.Column(db.String(32), default="text")  # text|image|video|plan|marketer
    units = db.Column(db.Integer, default=1)
    cost_rub = db.Column(db.Float, default=0.0)
    note = db.Column(db.String(300), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SecurityEvent(db.Model):
    """Журнал безопасности: входы, ошибки, смена команды/тарифа."""

    __tablename__ = "security_event"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    kind = db.Column(db.String(64), default="")  # login_ok|login_fail|logout|team_add|...
    username = db.Column(db.String(80), default="")
    ip = db.Column(db.String(64), default="")
    detail = db.Column(db.String(500), default="")
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
