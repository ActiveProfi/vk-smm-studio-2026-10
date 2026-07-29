"""Авторизация: регистрация, вход, выход."""
from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user

from webapp.forms import LoginForm, RegisterForm
from webapp.models import db, User
from webapp.workspace_seed import ensure_default_workspace_for_user

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/home")
def home():
    """Главная продающая страница — всегда открывается (даже если уже вошли)."""
    form = LoginForm()
    return render_template("auth/login.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    from flask import current_app

    if current_app.config.get("DEV_SKIP_AUTH") or current_user.is_authenticated:
        return redirect(url_for("smm.manager_panel"))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data.strip()).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            ensure_default_workspace_for_user(user)
            flash("Вы вошли.", "success")
            return redirect(url_for("smm.manager_panel"))
        flash("Неверный логин или пароль.", "danger")
    return render_template("auth/login.html", form=form)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    from flask import current_app

    if current_app.config.get("DEV_SKIP_AUTH") or current_user.is_authenticated:
        return redirect(url_for("smm.manager_panel"))
    form = RegisterForm()
    if form.validate_on_submit():
        if User.query.filter_by(username=form.username.data.strip()).first():
            flash("Такой логин уже занят.", "danger")
            return render_template("auth/register.html", form=form)
        user = User(username=form.username.data.strip())
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        ensure_default_workspace_for_user(user)
        flash("Аккаунт создан. Войдите.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/register.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    from flask import current_app

    logout_user()
    if current_app.config.get("DEV_SKIP_AUTH"):
        flash("В режиме разработки выход сразу снова входит автоматически.", "info")
        return redirect(url_for("smm.manager_panel"))
    flash("Вы вышли.", "info")
    return redirect(url_for("auth.home"))
