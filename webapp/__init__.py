"""Фабрика Flask-приложения."""
from pathlib import Path
import os


def _fix_ssl_certs() -> None:
    """На Windows Python часто не видит CA — чиним через certifi."""
    try:
        import certifi

        ca = certifi.where()
        os.environ.setdefault("SSL_CERT_FILE", ca)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", ca)
    except Exception:
        pass


def _load_project_dotenv() -> None:
    """Подтянуть .env из корня проекта (для WEBAPP_* и ключей)."""
    root = Path(__file__).resolve().parent.parent
    env_path = root / ".env"
    if not env_path.is_file():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except Exception:
        pass


_fix_ssl_certs()
_load_project_dotenv()

from flask import Flask, redirect, url_for, request
from flask_login import current_user, login_user
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

from webapp.config import PRIVACY_POLICY_VERSION, Config
from webapp.models import db, bcrypt, User
from webapp.auth import auth_bp
from webapp.smm import smm_bp
from webapp.workspaces import workspaces_bp
from webapp.billing import billing_bp
from webapp.team import team_bp
from webapp.workspace_seed import ensure_default_workspace_for_user, ensure_schema
from webapp.services import access as acc


def _dev_skip_auth_enabled() -> bool:
    return (os.environ.get("WEBAPP_DEV_SKIP_AUTH") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _ensure_dev_user() -> User | None:
    """Пользователь для авто-входа: WEBAPP_LOGIN или первый в базе."""
    login = (os.environ.get("WEBAPP_LOGIN") or "").strip()
    password = (os.environ.get("WEBAPP_PASSWORD") or "dev").strip() or "dev"
    user = None
    if login:
        user = User.query.filter_by(username=login).first()
        if not user:
            user = User(username=login)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
    if not user:
        user = User.query.order_by(User.id.asc()).first()
    if user:
        ensure_default_workspace_for_user(user)
    return user


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    if test_config and "DEV_SKIP_AUTH" in test_config:
        app.config["DEV_SKIP_AUTH"] = bool(test_config.get("DEV_SKIP_AUTH"))
    else:
        app.config["DEV_SKIP_AUTH"] = _dev_skip_auth_enabled()

    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    bcrypt.init_app(app)
    csrf = CSRFProtect(app)

    login_manager = LoginManager()
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Сначала войдите в систему."
    login_manager.init_app(app)

    @app.errorhandler(400)
    def handle_bad_request(err):
        """CSRF и прочие 400 для AJAX — JSON, а не HTML (иначе в UI «Ошибка сети»)."""
        wants_json = (
            request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or (request.accept_mimetypes.best == "application/json")
            or (request.content_type or "").startswith("application/json")
        )
        if wants_json:
            from flask import jsonify

            desc = getattr(err, "description", None) or str(err) or "Ошибка запроса"
            low = str(desc).lower()
            if "csrf" in low:
                desc = (
                    "Сессия устарела (ошибка безопасности формы). "
                    "Обновите страницу (F5) и нажмите кнопку ещё раз."
                )
            return jsonify({"ok": False, "error": desc}), 400
        return err

    @app.errorhandler(413)
    def handle_request_entity_too_large(err):
        """Слишком большой файл — JSON для AJAX, иначе в UI «Ошибка сети»."""
        wants_json = (
            request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or (request.accept_mimetypes.best == "application/json")
            or (request.content_type or "").startswith("multipart/form-data")
        )
        msg = (
            "Файлы слишком большие для одной загрузки (лимит 64 МБ на все файлы сразу). "
            "Загрузите по 1–2 фото за раз или уменьшите размер фото."
        )
        if wants_json:
            from flask import jsonify

            return jsonify({"ok": False, "error": msg}), 413
        return msg, 413

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(User, int(user_id))

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        # Скрипты страниц встроены в шаблоны, стили — Bootstrap и Google Fonts.
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "img-src 'self' data: blob: https: http:; "
            "media-src 'self' blob: https: http:; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "connect-src 'self'; "
            "frame-ancestors 'self'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "object-src 'none'",
        )
        if request.endpoint != "static" and getattr(current_user, "is_authenticated", False):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.before_request
    def auto_login_in_dev():
        """На время разработки: сразу «как будто вошли», без формы."""
        if not app.config.get("DEV_SKIP_AUTH"):
            return None
        if request.endpoint in {None, "static", "health"}:
            return None
        if current_user.is_authenticated:
            return None
        user = _ensure_dev_user()
        if user:
            login_user(user, remember=True)
        return None

    @app.before_request
    def require_privacy_consent():
        """Без согласия с текущей политикой кабинет не открываем. Удаление данных доступно."""
        if not current_user.is_authenticated or app.config.get("DEV_SKIP_AUTH"):
            return None
        allowed = {
            "static",
            "health",
            "auth.privacy",
            "auth.accept_privacy",
            "auth.logout",
            "auth.account",
            "auth.export_data",
            "auth.delete_account",
            "smm.client_portal",
        }
        if request.endpoint in allowed:
            return None
        version = (getattr(current_user, "privacy_policy_version", None) or "").strip()
        accepted = (getattr(current_user, "privacy_accepted_at", None) or "").strip()
        if version == PRIVACY_POLICY_VERSION and accepted:
            return None
        return redirect(url_for("auth.accept_privacy"))

    @app.context_processor
    def inject_active_workspace():
        if current_user.is_authenticated:
            ensure_default_workspace_for_user(current_user)
            role = acc.role_for_user(current_user)
            nav_workspaces = []
            try:
                nav_workspaces = list(acc.list_workspaces(current_user, active_only=True).limit(40))
            except Exception:
                nav_workspaces = []
            return {
                "active_workspace": current_user.get_active_workspace(),
                "nav_workspaces": nav_workspaces,
                "hide_nav_channel_bind": False,
                "dev_skip_auth": bool(app.config.get("DEV_SKIP_AUTH")),
                "user_role": acc.ROLE_LABELS.get(role, role),
                "user_role_code": role,
                "can_manage_team": acc.can(current_user, "team"),
            }
        return {
            "active_workspace": None,
            "nav_workspaces": [],
            "hide_nav_channel_bind": False,
            "dev_skip_auth": bool(app.config.get("DEV_SKIP_AUTH")),
            "user_role": "",
            "user_role_code": "",
            "can_manage_team": False,
        }

    from webapp.services.post_format import render_vk_post_html

    @app.template_filter("vk_post_html")
    def vk_post_html_filter(text: str) -> str:
        return render_vk_post_html(text or "")

    @app.template_filter("publish_format_label")
    def publish_format_label_filter(value: str) -> str:
        from webapp.services.publish_formats import label

        return label(value)

    app.register_blueprint(auth_bp)
    app.register_blueprint(smm_bp)
    app.register_blueprint(workspaces_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(team_bp)

    @app.route("/health")
    def health():
        return {"status": "ok"}

    @app.route("/")
    def root():
        # Гости — на главную (лендинг); вошедшие — в кабинет
        if app.config.get("DEV_SKIP_AUTH") or current_user.is_authenticated:
            return redirect(url_for("smm.manager_panel"))
        return redirect(url_for("auth.home"))

    @app.route("/start")
    def start():
        if app.config.get("DEV_SKIP_AUTH") or current_user.is_authenticated:
            return redirect(url_for("smm.manager_panel"))
        return redirect(url_for("auth.login"))

    with app.app_context():
        ensure_schema()
        if not app.config.get("TESTING"):
            try:
                from webapp.services.security_ops import purge_old_events

                purge_old_events()
            except Exception:
                pass
            try:
                from webapp.services.jobs import purge_old_jobs

                purge_old_jobs()
            except Exception:
                pass

    if not app.config.get("TESTING"):
        try:
            from webapp.services.auto_publish_worker import start_auto_publish_worker

            start_auto_publish_worker(app)
        except Exception:
            pass

    return app
