"""Оплата тарифа кабинета — тестовая заглушка (без реального списания)."""
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from webapp.forms import PaymentStubForm
from webapp.models import db

billing_bp = Blueprint("billing", __name__, url_prefix="/billing")

PLAN_PRICES = {
    "free": {"name": "Free", "price": 0, "hint": "14 дней полного доступа"},
    "standard": {"name": "Стандарт", "price": 1490, "hint": "Контент-ведение ВК"},
    "pro": {"name": "Pro", "price": 3900, "hint": "Контент + ВК Реклама"},
    "agency": {"name": "Agency", "price": 9900, "hint": "Команда и портфель"},
}

CHANNEL_PRICES = {
    "none": {"name": "—", "price": 0},
    "start": {"name": "Старт", "price": 690},
    "business": {"name": "Бизнес", "price": 1290},
    "premium": {"name": "Премиум", "price": 2290},
}

PLAN_STATUS_LABELS = {
    "trial": "Триал",
    "active": "Активен",
    "test_paid": "Оплачен (тест)",
    "none": "Не выбран",
}


def _calc_total(plan_code: str, channel_package: str, channel_count) -> dict:
    plan = PLAN_PRICES.get(plan_code) or PLAN_PRICES["standard"]
    ch = CHANNEL_PRICES.get(channel_package) or CHANNEL_PRICES["none"]
    try:
        n = max(0, min(int(channel_count or 0), 100))
    except (TypeError, ValueError):
        n = 0
    if channel_package == "none":
        n = 0
    channels_sum = ch["price"] * n
    return {
        "plan_name": plan["name"],
        "plan_price": plan["price"],
        "plan_hint": plan["hint"],
        "channel_name": ch["name"],
        "channel_price": ch["price"],
        "channel_count": n,
        "channels_sum": channels_sum,
        "total": plan["price"] + channels_sum,
    }


@billing_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    from webapp.services import access as acc

    if not acc.can(current_user, "billing"):
        flash("Оплату тарифа настраивает только владелец кабинета.", "warning")
        return redirect(url_for("smm.manager_panel"))

    form = PaymentStubForm()
    if request.method == "GET" and not form.is_submitted():
        code = (getattr(current_user, "plan_code", None) or "free").strip()
        if code in PLAN_PRICES and code != "free":
            form.plan_code.data = code
        else:
            form.plan_code.data = "standard"
        form.channel_package.data = "business"
        form.channel_count.data = 2

    if form.validate_on_submit():
        if not form.agree_test.data:
            flash("Отметьте галочку: это тестовая оплата, деньги не списываются.", "warning")
            return render_template(
                "billing/index.html",
                form=form,
                plans=PLAN_PRICES,
                current_plan=PLAN_PRICES.get(
                    (getattr(current_user, "plan_code", None) or "free").strip(),
                    PLAN_PRICES["free"],
                ),
                current_plan_code=(getattr(current_user, "plan_code", None) or "free").strip(),
                plan_status_label=PLAN_STATUS_LABELS.get(
                    (getattr(current_user, "plan_status", None) or "trial").strip(),
                    "—",
                ),
                plan_updated_at=getattr(current_user, "plan_updated_at", "") or "",
                plan_channels_note=getattr(current_user, "plan_channels_note", "") or "",
                preview=_calc_total(
                    form.plan_code.data or "standard",
                    form.channel_package.data or "business",
                    form.channel_count.data,
                ),
            )

        plan_code = (form.plan_code.data or "standard").strip()
        if plan_code not in PLAN_PRICES:
            plan_code = "standard"
        channel_package = (form.channel_package.data or "none").strip()
        if channel_package not in CHANNEL_PRICES:
            channel_package = "none"
        summary = _calc_total(plan_code, channel_package, form.channel_count.data)
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")

        current_user.plan_code = plan_code
        current_user.plan_status = "trial" if plan_code == "free" else "test_paid"
        current_user.plan_updated_at = now
        current_user.plan_channels_note = (
            f"{summary['channel_count']}×{channel_package}"
            if summary["channel_count"]
            else ""
        )
        db.session.commit()

        flash(
            f"Тестовая оплата принята — деньги не списаны. "
            f"Тариф «{summary['plan_name']}», сумма в тесте: {summary['total']} ₽/мес.",
            "success",
        )
        if plan_code in {"pro", "agency", "free"}:
            flash(
                "Следующий шаг: добавьте каналы и подключите кабинеты ВК Реклама.",
                "info",
            )
            return redirect(url_for("smm.ads_connect"))
        return redirect(url_for("billing.index"))

    current_code = (getattr(current_user, "plan_code", None) or "free").strip()
    current_plan = PLAN_PRICES.get(current_code, PLAN_PRICES["free"])
    status = (getattr(current_user, "plan_status", None) or "trial").strip()
    preview = _calc_total(
        form.plan_code.data or "standard",
        form.channel_package.data or "business",
        form.channel_count.data if form.channel_count.data is not None else 2,
    )

    return render_template(
        "billing/index.html",
        form=form,
        plans=PLAN_PRICES,
        current_plan=current_plan,
        current_plan_code=current_code,
        plan_status_label=PLAN_STATUS_LABELS.get(status, status or "—"),
        plan_updated_at=getattr(current_user, "plan_updated_at", "") or "",
        plan_channels_note=getattr(current_user, "plan_channels_note", "") or "",
        preview=preview,
    )
