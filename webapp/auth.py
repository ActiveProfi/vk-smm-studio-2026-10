"""Авторизация: регистрация, вход, выход, согласие и права по персональным данным."""
from datetime import datetime

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from webapp.config import PRIVACY_POLICY_VERSION
from webapp.forms import LoginForm, RegisterForm
from webapp.models import db, User
from webapp.services import access as acc
from webapp.services import personal_data
from webapp.services import security_ops as sec
from webapp.services.http_guard import safe_next_url
from webapp.workspace_seed import ensure_default_workspace_for_user

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _home_after_login() -> str:
    return url_for("smm.manager_panel")


@auth_bp.route("/home")
def home():
    """Главная продающая страница — всегда открывается (даже если уже вошли)."""
    form = LoginForm()
    return render_template("auth/login.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_app.config.get("DEV_SKIP_AUTH") or current_user.is_authenticated:
        return redirect(_home_after_login())
    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        blocked, msg = sec.login_is_blocked(username)
        if blocked:
            flash(msg, "danger")
            return render_template("auth/login.html", form=form)

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=False)
            ensure_default_workspace_for_user(user)
            sec.log_event("login_ok", username=username, user_id=user.id)
            flash("Вы вошли.", "success")
            next_url = safe_next_url(request.args.get("next"), _home_after_login())
            return redirect(next_url)

        sec.log_event("login_fail", username=username, detail="bad_credentials")
        flash("Неверный логин или пароль.", "danger")
    return render_template("auth/login.html", form=form)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_app.config.get("DEV_SKIP_AUTH") or current_user.is_authenticated:
        return redirect(_home_after_login())
    form = RegisterForm()
    if form.validate_on_submit():
        blocked, msg = sec.register_is_blocked()
        if blocked:
            flash(msg, "danger")
            return render_template("auth/register.html", form=form)
        sec.log_event("register_attempt", username=form.username.data.strip())
        if User.query.filter_by(username=form.username.data.strip()).first():
            flash("Такой логин уже занят.", "danger")
            return render_template("auth/register.html", form=form)
        user = User(username=form.username.data.strip())
        user.set_password(form.password.data)
        user.privacy_accepted_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
        user.privacy_policy_version = PRIVACY_POLICY_VERSION
        db.session.add(user)
        db.session.commit()
        ensure_default_workspace_for_user(user)
        sec.log_event("register", username=user.username, user_id=user.id)
        flash("Аккаунт создан. Войдите.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/register.html", form=form)


@auth_bp.route("/logout", methods=["GET", "POST"])
@login_required
def logout():
    # Выход только кнопкой (POST). Ссылка с чужого сайта не должна разлогинивать.
    if request.method != "POST":
        return render_template("auth/logout_confirm.html")
    uname = current_user.username if current_user.is_authenticated else ""
    uid = current_user.id if current_user.is_authenticated else None
    logout_user()
    sec.log_event("logout", username=uname, user_id=uid)
    if current_app.config.get("DEV_SKIP_AUTH"):
        flash("В режиме разработки выход сразу снова входит автоматически.", "info")
        return redirect(url_for("smm.manager_panel"))
    flash("Вы вышли.", "info")
    return redirect(url_for("auth.home"))


@auth_bp.route("/privacy")
def privacy():
    """Политика обработки персональных данных (краткая, для продукта)."""
    return render_template(
        "auth/privacy.html",
        policy_version=PRIVACY_POLICY_VERSION,
    )


@auth_bp.route("/accept-privacy", methods=["GET", "POST"])
@login_required
def accept_privacy():
    if request.method == "POST":
        if request.form.get("agree") != "1":
            flash("Чтобы пользоваться кабинетом, нужно согласие с политикой.", "warning")
        else:
            current_user.privacy_accepted_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
            current_user.privacy_policy_version = PRIVACY_POLICY_VERSION
            db.session.commit()
            sec.log_event("privacy_accept", detail=PRIVACY_POLICY_VERSION)
            flash("Согласие сохранено.", "success")
            return redirect(_home_after_login())
    return render_template(
        "auth/accept_privacy.html",
        policy_version=PRIVACY_POLICY_VERSION,
    )


@auth_bp.route("/account")
@login_required
def account():
    return render_template(
        "auth/account.html",
        policy_version=PRIVACY_POLICY_VERSION,
        accepted_at=getattr(current_user, "privacy_accepted_at", "") or "",
        accepted_version=getattr(current_user, "privacy_policy_version", "") or "",
    )


@auth_bp.route("/export-data")
@login_required
def export_data():
    payload = personal_data.export_account(current_user)
    sec.log_event("data_export", detail="json")
    response = jsonify(payload)
    filename = f"vk-smm-data-{current_user.id}.json"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Cache-Control"] = "no-store"
    return response


@auth_bp.route("/delete-account", methods=["POST"])
@login_required
def delete_account():
    password = request.form.get("password") or ""
    confirm = (request.form.get("confirm") or "").strip()
    if confirm != "УДАЛИТЬ":
        flash("Чтобы удалить кабинет, введите слово УДАЛИТЬ.", "warning")
        return redirect(url_for("auth.account"))
    if not current_user.check_password(password):
        sec.log_event("data_delete_denied", detail="bad_password")
        flash("Пароль не подошёл. Кабинет не удалён.", "danger")
        return redirect(url_for("auth.account"))
    user = db.session.get(User, current_user.id)
    sec.log_event("data_delete", username=user.username, user_id=user.id)
    logout_user()
    personal_data.delete_account(user)
    flash("Кабинет и связанные данные удалены.", "info")
    return redirect(url_for("auth.home"))


@auth_bp.route("/security-log")
@login_required
def security_log():
    """Журнал безопасности — только владелец своего агентства."""
    if not acc.can(current_user, "team"):
        flash("Журнал безопасности доступен владельцу кабинета.", "warning")
        return redirect(url_for("smm.manager_panel"))
    # Сотрудник чужого агентства не должен видеть журнал владельца как «свой».
    if acc.membership_for(current_user):
        flash("Журнал безопасности доступен владельцу кабинета.", "warning")
        return redirect(url_for("smm.manager_panel"))
    events = sec.recent_events(current_user.id, 80)
    return render_template("auth/security_log.html", events=events)
