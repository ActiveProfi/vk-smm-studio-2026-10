"""Формы веб-приложения."""
from datetime import datetime

from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, MultipleFileField
from wtforms import (
    StringField,
    PasswordField,
    SubmitField,
    TextAreaField,
    SelectField,
    BooleanField,
    IntegerField,
    HiddenField,
)
from wtforms.validators import DataRequired, Length, EqualTo, Optional, Regexp, ValidationError


class RegisterForm(FlaskForm):
    username = StringField("Логин", validators=[DataRequired(), Length(3, 80)])
    password = PasswordField(
        "Пароль",
        validators=[DataRequired(), Length(8, 128)],
        render_kw={"placeholder": "Не меньше 8 символов"},
    )
    password2 = PasswordField(
        "Повтор пароля",
        validators=[DataRequired(), EqualTo("password", message="Пароли не совпадают")],
    )
    privacy_agree = BooleanField(
        "Согласен с политикой обработки персональных данных",
        default=False,
    )
    submit = SubmitField("Зарегистрироваться")

    def validate_privacy_agree(self, field):
        if not field.data:
            raise ValidationError("Нужно принять политику персональных данных.")


class LoginForm(FlaskForm):
    username = StringField("Логин", validators=[DataRequired()])
    password = PasswordField("Пароль", validators=[DataRequired()])
    submit = SubmitField("Войти")


class WorkspaceForm(FlaskForm):
    name = StringField("Название канала", validators=[DataRequired(), Length(2, 120)])
    theme = StringField("Тематика", validators=[Optional(), Length(0, 300)])
    description = TextAreaField("Описание", validators=[Optional()], render_kw={"rows": 3})
    brand_site = StringField(
        "Подпись внизу визуала (по умолчанию для канала)",
        validators=[Optional(), Length(0, 200)],
        render_kw={"placeholder": "например: мойсайт.ru  или  название бренда"},
    )
    search_hint = StringField(
        "Подсказка для веб-поиска",
        validators=[Optional(), Length(0, 300)],
        render_kw={"placeholder": "например: ремонт квартир  или  SMM ВКонтакте"},
    )
    knowledge_text = TextAreaField(
        "База знаний канала",
        validators=[Optional()],
        render_kw={
            "rows": 10,
            "placeholder": "Факты, правила и термины только для этого канала. Оставьте пустым, если не нужно.",
        },
    )
    visual_style_prompt = TextAreaField(
        "Промпт визуального стиля канала",
        validators=[Optional(), Length(0, 20000)],
        render_kw={
            "rows": 8,
            "placeholder": "Опишите постоянный стиль картинок для этого канала: палитра, шрифты, композиция, настроение. "
            "Например: «Светлый фон, жёлтые акценты, крупная кириллица, педагогическая инфографика без персонажей».",
        },
    )
    vk_token = PasswordField(
        "VK API токен (пользователя-админа)",
        validators=[Optional(), Length(0, 512)],
        render_kw={
            "placeholder": "Оставьте пустым, чтобы не менять сохранённый токен",
            "autocomplete": "new-password",
        },
    )
    vk_group_id = StringField(
        "ID группы ВК",
        validators=[Optional(), Length(0, 64)],
        render_kw={"placeholder": "например: 123456789  (только цифры)"},
    )
    vk_ads_account_id = StringField(
        "ID / номер кабинета ВК Реклама",
        validators=[Optional(), Length(0, 64)],
        render_kw={"placeholder": "Например, 12345678 (для вашей заметки)"},
    )
    vk_ads_token = PasswordField(
        "Токен API ВК Реклама",
        validators=[Optional(), Length(0, 1024)],
        render_kw={
            "placeholder": "Оставьте пустым, чтобы не менять сохранённый токен",
            "autocomplete": "new-password",
        },
    )
    seed_mode = SelectField(
        "Стартовые рубрики",
        choices=[
            ("generic", "Универсальный минимум (3 рубрики)"),
            ("empty", "Без рубрик (добавлю сам)"),
            ("nds", "Пример: полный набор рубрик НДС (шаблон курса)"),
        ],
        default="generic",
    )
    package_code = SelectField(
        "Пакет услуг",
        choices=[
            ("none", "Без пакета (без лимита)"),
            ("start", "Старт · 12 постов/мес"),
            ("business", "Бизнес · 25 постов/мес"),
            ("premium", "Премиум · 45 постов/мес"),
            ("custom", "Свой лимит"),
        ],
        default="business",
    )
    package_posts_limit = IntegerField(
        "Свой лимит постов в месяц",
        validators=[Optional()],
        default=12,
    )
    require_client_approval = BooleanField(
        "Перед внесением контент-плана в календарь нужно согласование клиента",
        default=False,
    )
    auto_publish_enabled = BooleanField(
        "Автопубликация: готовые посты сами уходят в ВК, когда наступает время в календаре",
        default=False,
    )
    submit = SubmitField("Сохранить канал")


class RubricForm(FlaskForm):
    # Код создаётся автоматически из названия — поле скрыто в UI
    code = StringField(
        "Код (латиница)",
        validators=[
            Optional(),
            Length(0, 64),
            Regexp(
                r"^$|^[a-z][a-z0-9_]*$",
                message="Только латиница, цифры и _",
            ),
        ],
    )
    title = StringField("Название рубрики", validators=[DataRequired(), Length(2, 120)])
    prompt_text = TextAreaField(
        "Промпт рубрики",
        validators=[DataRequired(), Length(20, 50000)],
        render_kw={"rows": 14},
    )
    sort_order = IntegerField("Порядок", default=0, validators=[Optional()])
    is_active = BooleanField("Активна", default=True)
    submit = SubmitField("Сохранить рубрику")


class SwitchWorkspaceForm(FlaskForm):
    workspace_id = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Выбрать")


class GenerateForm(FlaskForm):
    topic = StringField("Тема", validators=[DataRequired(), Length(3, 300)])
    post_type = SelectField("Рубрика", choices=[], validators=[DataRequired()])
    tone = StringField(
        "Тон",
        default="спокойно, профессионально, простым языком",
        validators=[Optional(), Length(0, 200)],
    )
    uploads = MultipleFileField(
        "Загрузка материалов",
        validators=[
            Optional(),
            FileAllowed(
                ["txt", "md", "markdown", "csv", "doc", "docx", "pdf", "xls", "xlsx"],
                "Разрешены: txt, md, Word, PDF, Excel",
            ),
        ],
    )
    materials = TextAreaField(
        "Саммари материалов и тезисы",
        validators=[Optional(), Length(0, 20000)],
        render_kw={"rows": 10},
    )
    sources_note = StringField(
        "Источники",
        default="материалы пользователя + веб-поиск + база знаний канала",
        validators=[Optional(), Length(0, 500)],
    )
    enable_relevance = BooleanField("Проверка актуальности (отдельный агент)", default=True)
    generate_image = BooleanField("Картинка (GPT Image 2)", default=True)
    generate_video = BooleanField("Видео", default=False)
    video_provider = SelectField(
        "Нейросеть для видео",
        choices=[
            ("kling", "Kling 3.0"),
            ("minimax", "MiniMax H3"),
            ("veo", "Veo 3.1"),
            ("hailuo", "Hailuo 02"),
        ],
        default="kling",
        validators=[Optional()],
    )
    # Краткий бриф по скиллу «генерация видео» (6 блоков) — остальное допишет приложение
    video_object = StringField(
        "Персонаж / объект",
        validators=[Optional(), Length(0, 300)],
        render_kw={"placeholder": "например: керамическая кружка с кофе"},
    )
    video_action = StringField(
        "Действие",
        validators=[Optional(), Length(0, 300)],
        render_kw={"placeholder": "например: пар поднимается и растворяется"},
    )
    video_place = StringField(
        "Место",
        validators=[Optional(), Length(0, 300)],
        render_kw={"placeholder": "например: дубовая столешница у окна, утро"},
    )
    video_camera = SelectField(
        "Камера",
        choices=[],  # заполняется в __init__ из скилла
        validators=[Optional()],
    )
    video_light = SelectField(
        "Свет",
        choices=[],
        validators=[Optional()],
    )
    video_style = SelectField(
        "Стиль",
        choices=[],
        validators=[Optional()],
    )
    video_negative = StringField(
        "Запреты в кадре",
        default="текст, надписи, логотипы, водяной знак",
        validators=[Optional(), Length(0, 500)],
        render_kw={"placeholder": "что нельзя показывать в ролике"},
    )
    visual_footer = StringField(
        "Подпись внизу визуала",
        validators=[Optional(), Length(0, 200)],
        render_kw={"placeholder": "например: мойсайт.ru  или  название бренда"},
    )
    cta = BooleanField("Добавить CTA", default=True)
    submit = SubmitField("Сгенерировать")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from webapp.services.video_prompt_skill import (
            CAMERA_CHOICES,
            LIGHT_CHOICES,
            STYLE_CHOICES,
        )

        self.video_camera.choices = list(CAMERA_CHOICES)
        self.video_light.choices = list(LIGHT_CHOICES)
        self.video_style.choices = list(STYLE_CHOICES)

    def validate_materials(self, field):
        text = (field.data or "").strip()
        if len(text) < 10:
            raise ValidationError(
                "Саммари пустое. Загрузите файлы и/или нажмите «Веб-поиск», "
                "либо впишите тезисы вручную (минимум 10 символов)."
            )


class PublishForm(FlaskForm):
    submit = SubmitField("Опубликовать в ВК")


class ScheduleForm(FlaskForm):
    """Дата и время отдельными ячейками — удобно вводить цифрами."""

    sched_day = StringField(
        "День",
        validators=[DataRequired(message="Укажите день")],
        render_kw={
            "maxlength": 2,
            "inputmode": "numeric",
            "pattern": "[0-9]*",
            "placeholder": "ДД",
            "autocomplete": "off",
            "class": "form-control datetime-cell",
        },
    )
    sched_month = StringField(
        "Месяц",
        validators=[DataRequired(message="Укажите месяц")],
        render_kw={
            "maxlength": 2,
            "inputmode": "numeric",
            "pattern": "[0-9]*",
            "placeholder": "ММ",
            "autocomplete": "off",
            "class": "form-control datetime-cell",
        },
    )
    sched_year = StringField(
        "Год",
        validators=[DataRequired(message="Укажите год")],
        render_kw={
            "maxlength": 4,
            "inputmode": "numeric",
            "pattern": "[0-9]*",
            "placeholder": "ГГГГ",
            "autocomplete": "off",
            "class": "form-control datetime-cell datetime-cell--year",
        },
    )
    sched_hour = StringField(
        "Час",
        validators=[DataRequired(message="Укажите час")],
        render_kw={
            "maxlength": 2,
            "inputmode": "numeric",
            "pattern": "[0-9]*",
            "placeholder": "ЧЧ",
            "autocomplete": "off",
            "class": "form-control datetime-cell",
        },
    )
    sched_minute = StringField(
        "Минута",
        validators=[DataRequired(message="Укажите минуты")],
        render_kw={
            "maxlength": 2,
            "inputmode": "numeric",
            "pattern": "[0-9]*",
            "placeholder": "ММ",
            "autocomplete": "off",
            "class": "form-control datetime-cell",
        },
    )
    submit = SubmitField("Поставить в календарь")

    def validate(self, extra_validators=None):
        if not super().validate(extra_validators=extra_validators):
            return False
        try:
            self.built_scheduled_for = build_scheduled_for_iso(
                self.sched_day.data,
                self.sched_month.data,
                self.sched_year.data,
                self.sched_hour.data,
                self.sched_minute.data,
            )
        except ValueError as exc:
            self.sched_day.errors.append(str(exc))
            return False
        return True


def build_scheduled_for_iso(
    day: str | None,
    month: str | None,
    year: str | None,
    hour: str | None,
    minute: str | None,
    *,
    tz_offset: str = "+10:00",
) -> str:
    """Собирает ISO-дату из отдельных ячеек (часовой пояс по умолчанию +10)."""
    try:
        d = int(str(day or "").strip())
        m = int(str(month or "").strip())
        y = int(str(year or "").strip())
        h = int(str(hour or "").strip())
        mi = int(str(minute or "").strip())
    except ValueError as exc:
        raise ValueError("В ячейках должны быть только цифры") from exc

    if not (1 <= m <= 12):
        raise ValueError("Месяц должен быть от 1 до 12")
    if not (1 <= d <= 31):
        raise ValueError("День должен быть от 1 до 31")
    if not (2024 <= y <= 2100):
        raise ValueError("Год должен быть от 2024 до 2100")
    if not (0 <= h <= 23):
        raise ValueError("Час должен быть от 0 до 23")
    if not (0 <= mi <= 59):
        raise ValueError("Минуты должны быть от 0 до 59")

    try:
        dt = datetime(y, m, d, h, mi, 0)
    except ValueError as exc:
        raise ValueError("Такой даты не существует (проверьте день и месяц)") from exc

    return f"{dt.strftime('%Y-%m-%dT%H:%M:%S')}{tz_offset}"


def parse_scheduled_for_parts(value: str | None) -> dict[str, str]:
    """Разбирает сохранённую дату на ячейки для формы."""
    empty = {"day": "", "month": "", "year": "", "hour": "", "minute": ""}
    raw = (value or "").strip()
    if not raw:
        return empty

    # ISO: 2026-07-20T10:00:00+10:00
    try:
        normalized = raw.replace("Z", "+00:00")
        if " " in normalized and "T" not in normalized:
            normalized = normalized.replace(" ", "T", 1)
        dt = datetime.fromisoformat(normalized)
        return {
            "day": f"{dt.day:02d}",
            "month": f"{dt.month:02d}",
            "year": f"{dt.year:04d}",
            "hour": f"{dt.hour:02d}",
            "minute": f"{dt.minute:02d}",
        }
    except ValueError:
        pass

    import re

    m = re.match(
        r"^(\d{1,2})[./](\d{1,2})[./](\d{4})\s+(\d{1,2}):(\d{2})",
        raw,
    )
    if m:
        return {
            "day": f"{int(m.group(1)):02d}",
            "month": f"{int(m.group(2)):02d}",
            "year": m.group(3),
            "hour": f"{int(m.group(4)):02d}",
            "minute": m.group(5),
        }
    return empty


class PaymentStubForm(FlaskForm):
    """Тестовая оплата тарифа кабинета — деньги не списываются."""

    plan_code = SelectField(
        "Тариф кабинета",
        choices=[
            ("standard", "Стандарт — 1 490 ₽/мес"),
            ("pro", "Pro — 3 900 ₽/мес (+ ВК Реклама)"),
            ("agency", "Agency — 9 900 ₽/мес"),
            ("free", "Free — 0 ₽ · триал 14 дней"),
        ],
        validators=[DataRequired()],
    )
    channel_package = SelectField(
        "Пакет для расчёта каналов (тест)",
        choices=[
            ("none", "Без каналов в счёте"),
            ("start", "Старт · 690 ₽ за канал"),
            ("business", "Бизнес · 1 290 ₽ за канал"),
            ("premium", "Премиум · 2 290 ₽ за канал"),
        ],
        default="business",
        validators=[DataRequired()],
    )
    channel_count = IntegerField(
        "Сколько каналов учесть в тестовом счёте",
        default=2,
        validators=[Optional()],
    )
    payer_name = StringField(
        "Имя плательщика",
        validators=[DataRequired(), Length(2, 120)],
        render_kw={"placeholder": "Как в тестовой карте"},
    )
    card_number = StringField(
        "Номер карты (тест)",
        validators=[DataRequired(), Length(12, 24)],
        render_kw={"placeholder": "4242 4242 4242 4242", "autocomplete": "off"},
    )
    card_exp = StringField(
        "Срок (ММ/ГГ)",
        validators=[DataRequired(), Length(4, 7)],
        render_kw={"placeholder": "12/28", "autocomplete": "off"},
    )
    card_cvc = StringField(
        "CVC (тест)",
        validators=[DataRequired(), Length(3, 4)],
        render_kw={"placeholder": "123", "autocomplete": "off"},
    )
    agree_test = BooleanField(
        "Понимаю: это тестовая оплата, деньги не списываются",
        default=False,
    )
    submit = SubmitField("Оплатить (тест)")


class TeamInviteForm(FlaskForm):
    """Добавить сотрудника в команду агентства."""

    username = StringField(
        "Логин сотрудника",
        validators=[DataRequired(), Length(2, 80)],
        render_kw={"placeholder": "например: manager1"},
    )
    role = SelectField(
        "Роль",
        choices=[
            ("manager", "Менеджер — контент, генерация, публикация"),
            ("viewer", "Наблюдатель — только просмотр и отчёты"),
        ],
        default="manager",
        validators=[DataRequired()],
    )
    password = PasswordField(
        "Пароль (если логина ещё нет — создадим аккаунт)",
        validators=[Optional(), Length(0, 128)],
        render_kw={
            "placeholder": "От 6 символов, только для нового логина",
            "autocomplete": "new-password",
        },
    )
    submit = SubmitField("Добавить в команду")
