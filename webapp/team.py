"""Команда агентства: приглашение менеджеров и наблюдателей."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from webapp.forms import TeamInviteForm
from webapp.models import TeamMember, User, db
from webapp.services import access as acc

team_bp = Blueprint("team", __name__, url_prefix="/team")


@team_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    """Управление командой — только владелец агентства."""
    form = TeamInviteForm()
    membership = acc.membership_for(current_user)

    # Сотрудник видит свою роль, без управления
    if membership:
        agency = db.session.get(User, membership.agency_user_id)
        return render_template(
            "team/index.html",
            form=None,
            members=[],
            is_owner=False,
            my_role=acc.ROLE_LABELS.get(membership.role, membership.role),
            agency_name=(agency.username if agency else "—"),
            plan_ok=True,
            plan_warning="",
            member_count=0,
            max_members=acc.MAX_TEAM_MEMBERS,
        )

    plan_ok = acc.plan_allows_team(current_user)
    plan_warning = ""
    if not plan_ok:
        plan_warning = (
            "По тарифам команда входит в Agency. "
            "Сейчас можно протестировать на триале или перейти на Agency в разделе «Оплата»."
        )

    if form.validate_on_submit():
        if not plan_ok and (getattr(current_user, "plan_code", "") or "").strip().lower() == "standard":
            flash("На тарифе Стандарт команда недоступна. Выберите Agency в «Оплата».", "warning")
            return redirect(url_for("billing.index"))

        if acc.team_count(current_user.id) >= acc.MAX_TEAM_MEMBERS:
            flash(f"Лимит команды: {acc.MAX_TEAM_MEMBERS} сотрудников.", "warning")
            return redirect(url_for("team.index"))

        username = (form.username.data or "").strip()
        role = (form.role.data or acc.ROLE_MANAGER).strip().lower()
        if role not in {acc.ROLE_MANAGER, acc.ROLE_VIEWER}:
            role = acc.ROLE_MANAGER
        password = (form.password.data or "").strip()

        if username.lower() == (current_user.username or "").lower():
            flash("Нельзя добавить самого себя.", "warning")
            return redirect(url_for("team.index"))

        member_user = User.query.filter_by(username=username).first()
        created_new = False
        if not member_user:
            if len(password) < 8:
                flash(
                    "Такого логина ещё нет. Укажите пароль (от 8 символов) — создадим аккаунт сотруднику.",
                    "warning",
                )
                return render_template(
                    "team/index.html",
                    form=form,
                    members=_members_view(current_user.id),
                    is_owner=True,
                    my_role=acc.ROLE_LABELS[acc.ROLE_OWNER],
                    agency_name=current_user.username,
                    plan_ok=plan_ok,
                    plan_warning=plan_warning,
                    member_count=acc.team_count(current_user.id),
                    max_members=acc.MAX_TEAM_MEMBERS,
                )
            member_user = User(username=username)
            member_user.set_password(password)
            # Сотрудник наследует «бесплатный» статус — доступ через членство
            member_user.plan_code = "free"
            member_user.plan_status = "none"
            db.session.add(member_user)
            db.session.flush()
            created_new = True
        else:
            # Уже состоит в другой команде?
            other = TeamMember.query.filter_by(user_id=member_user.id, is_active=True).first()
            if other and other.agency_user_id != current_user.id:
                flash("Этот пользователь уже в другой команде.", "danger")
                return redirect(url_for("team.index"))
            existing = TeamMember.query.filter_by(
                agency_user_id=current_user.id,
                user_id=member_user.id,
            ).first()
            if existing and existing.is_active:
                flash("Этот сотрудник уже в команде.", "info")
                return redirect(url_for("team.index"))
            if existing:
                existing.is_active = True
                existing.role = role
                db.session.commit()
                flash("Сотрудник снова активирован.", "success")
                return redirect(url_for("team.index"))

        db.session.add(
            TeamMember(
                agency_user_id=current_user.id,
                user_id=member_user.id,
                role=role,
                is_active=True,
            )
        )
        db.session.commit()
        from webapp.services import security_ops as sec

        sec.log_event(
            "team_add",
            detail=f"user={username} role={role}",
            user_id=current_user.id,
        )
        if created_new:
            flash(
                f"Создан аккаунт «{username}» и добавлен как {acc.ROLE_LABELS.get(role, role)}. "
                "Передайте логин и пароль сотруднику.",
                "success",
            )
        else:
            flash(
                f"«{username}» добавлен как {acc.ROLE_LABELS.get(role, role)}.",
                "success",
            )
        return redirect(url_for("team.index"))

    return render_template(
        "team/index.html",
        form=form,
        members=_members_view(current_user.id),
        is_owner=True,
        my_role=acc.ROLE_LABELS[acc.ROLE_OWNER],
        agency_name=current_user.username,
        plan_ok=plan_ok,
        plan_warning=plan_warning,
        member_count=acc.team_count(current_user.id),
        max_members=acc.MAX_TEAM_MEMBERS,
    )


@team_bp.route("/<int:member_id>/role", methods=["POST"])
@login_required
def change_role(member_id: int):
    if acc.membership_for(current_user):
        flash("Менять роли может только владелец.", "warning")
        return redirect(url_for("team.index"))
    from flask import request

    row = TeamMember.query.filter_by(
        id=member_id, agency_user_id=current_user.id, is_active=True
    ).first_or_404()
    role = (request.form.get("role") or "").strip().lower()
    if role not in {acc.ROLE_MANAGER, acc.ROLE_VIEWER}:
        flash("Неизвестная роль.", "danger")
        return redirect(url_for("team.index"))
    row.role = role
    db.session.commit()
    flash("Роль обновлена.", "success")
    return redirect(url_for("team.index"))


@team_bp.route("/<int:member_id>/remove", methods=["POST"])
@login_required
def remove_member(member_id: int):
    if acc.membership_for(current_user):
        flash("Удалять сотрудников может только владелец.", "warning")
        return redirect(url_for("team.index"))
    row = TeamMember.query.filter_by(
        id=member_id, agency_user_id=current_user.id, is_active=True
    ).first_or_404()
    row.is_active = False
    db.session.commit()
    from webapp.services import security_ops as sec

    sec.log_event(
        "team_remove",
        detail=f"member_id={member_id}",
        user_id=current_user.id,
    )
    flash("Сотрудник отключён от команды.", "info")
    return redirect(url_for("team.index"))


def _members_view(agency_user_id: int) -> list[dict]:
    rows = acc.team_members(agency_user_id)
    out = []
    for row in rows:
        user = db.session.get(User, row.user_id)
        out.append(
            {
                "id": row.id,
                "username": user.username if user else f"id:{row.user_id}",
                "role": row.role,
                "role_label": acc.ROLE_LABELS.get(row.role, row.role),
                "created_at": row.created_at,
            }
        )
    return out
