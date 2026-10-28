"""Авторизация: регистрация, вход, выход + базовые страницы безопасности."""
from datetime import datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from webapp.forms import LoginForm, RegisterForm
from webapp.models import db, User
from webapp.services import access as acc
from webapp.services import security_ops as sec
from webapp.workspace_seed import ensure_default_workspace_for_user

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/home")
def home():
    """Главная продающая страница — всегда открывается (даже если уже вошли)."""
    form = LoginForm()
    return render_template("auth/login.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_app.config.get("DEV_SKIP_AUTH") or current_user.is_authenticated:
        return redirect(url_for("smm.manager_panel"))
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
            next_url = (request.args.get("next") or "").strip()
            if next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)
            return redirect(url_for("smm.manager_panel"))

        sec.log_event("login_fail", username=username, detail="bad_credentials")
        flash("Неверный логин или пароль.", "danger")
    return render_template("auth/login.html", form=form)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_app.config.get("DEV_SKIP_AUTH") or current_user.is_authenticated:
        return redirect(url_for("smm.manager_panel"))
    form = RegisterForm()
    if form.validate_on_submit():
        if User.query.filter_by(username=form.username.data.strip()).first():
            flash("Такой логин уже занят.", "danger")
            return render_template("auth/register.html", form=form)
        user = User(username=form.username.data.strip())
        user.set_password(form.password.data)
        user.privacy_accepted_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
        db.session.add(user)
        db.session.commit()
        ensure_default_workspace_for_user(user)
        sec.log_event("register", username=user.username, user_id=user.id)
        flash("Аккаунт создан. Войдите.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/register.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
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
    return render_template("auth/privacy.html")


@auth_bp.route("/security-log")
@login_required
def security_log():
    """Журнал безопасности — только владелец кабинета."""
    if not acc.can(current_user, "team"):
        flash("Журнал безопасности доступен владельцу кабинета.", "warning")
        return redirect(url_for("smm.manager_panel"))
    events = sec.recent_events(80)
    return render_template("auth/security_log.html", events=events)
