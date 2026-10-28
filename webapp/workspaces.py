"""Управление каналами ВК и рубриками."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import threading

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from webapp.forms import RubricForm, SwitchWorkspaceForm, WorkspaceForm
from webapp.models import Draft, Rubric, Workspace, db
from webapp.services import vk_client
from webapp.services import vk_ads_client
from webapp.services import access as acc
from webapp.services.http_guard import scrub_secrets
from webapp.services.publish_formats import choices as pf_choices
from webapp.services.publish_formats import label as pf_label
from webapp.services.publish_formats import normalize_format as pf_code
from webapp.services.secrets_box import reveal, seal
from webapp.services import materials_bag
from webapp.services import workspace_visual as ws_visual
from webapp.services import workspace_ai as ws_ai
from webapp.services import content_plan as plan_svc
from webapp.services import marketer_brief as marketer_svc
from webapp.services import jobs as job_store
from webapp.services.extract_text import safe_storage_name
from webapp.workspace_seed import (
    ensure_default_workspace_for_user,
    seed_generic_rubrics,
    seed_rubrics_from_nds_templates,
)
workspaces_bp = Blueprint("workspaces", __name__, url_prefix="/workspaces")


def _sample_plan_if_requested():
    """Только для скриншота черновика плана, пока включён вход без пароля."""
    from flask import current_app, request

    if not current_app.config.get("DEV_SKIP_AUTH"):
        return []
    if (request.args.get("sample") or "") != "1":
        return []
    return [
        {
            "date": "2026-11-02",
            "time": "10:00",
            "topic": "Как выбрать зерно к утру",
            "rubric_title": "Экспертный пост",
            "rubric_code": "expert",
            "format": "image",
            "note": "коротко и по делу",
        },
        {
            "date": "2026-11-03",
            "time": "18:30",
            "topic": "Пар над чашкой",
            "rubric_title": "Кейс",
            "rubric_code": "case",
            "format": "animation",
            "note": "короткий ролик",
        },
        {
            "date": "2026-11-04",
            "time": "12:00",
            "topic": "Три напитка недели",
            "rubric_title": "Чек-лист",
            "rubric_code": "checklist",
            "format": "carousel",
            "note": "три кадра",
        },
    ]


def _user_workspace(workspace_id: int) -> Workspace:
    return acc.get_workspace_or_404(current_user, workspace_id)


def _visual_refs_for_template(ws: Workspace | None) -> list[dict]:
    if not ws:
        return []
    refs = ws_visual.load_reference_images(ws)
    for ref in refs:
        rel = ref.get("path") or ""
        ref["url"] = url_for(
            "smm.media_file",
            user_id=current_user.id,
            filename=rel,
        )
    return refs


def _run_style_preview_job(app, job_id: str, payload: dict) -> None:
    with app.app_context():
        progress = job_store.make_progress_callback(job_id)
        ws_id = int(payload.get("workspace_id") or 0)
        try:
            image_url = ws_visual.generate_style_preview_image(
                name=payload.get("name") or "",
                theme=payload.get("theme") or "",
                description=payload.get("description") or "",
                visual_style_prompt=payload.get("visual_style_prompt") or "",
                brand_site=payload.get("brand_site") or "",
                reference_image_urls=payload.get("reference_image_urls") or [],
                reference_local_files=payload.get("reference_local_files") or [],
                reference_image_names=payload.get("reference_image_names") or [],
                on_progress=progress,
            )
            ws = db.session.get(Workspace, ws_id)
            if ws:
                ws.visual_style_preview_url = image_url
                db.session.commit()
            job_store.update_job(
                job_id,
                status="done",
                step="done",
                message="Пример готов",
                percent=100,
                image_url=image_url,
                error="",
            )
        except Exception as exc:  # noqa: BLE001
            db.session.rollback()
            job_store.update_job(
                job_id,
                status="error",
                step="error",
                message="Ошибка генерации примера",
                percent=100,
                error=str(exc),
            )


def _vk_status_for_workspace(ws: Workspace | None) -> dict:
    """Краткий статус подключения без вызова API (для подсказок в UI)."""
    import os

    # подтянуть .env в os.environ
    try:
        import publish_vk_scheduled as vk_pub

        vk_pub.load_dotenv_file()
    except Exception:
        pass

    has_channel_token = bool(ws and (ws.vk_token or "").strip())
    has_channel_group = bool(ws and (ws.vk_group_id or "").strip())
    has_env_token = bool(
        os.environ.get("VK_USER_TOKEN", "").strip()
        or os.environ.get("VK_COMMUNITY_TOKEN", "").strip()
    )
    has_env_group = bool(os.environ.get("VK_GROUP_ID", "").strip())
    ready = (has_channel_token or has_env_token) and (has_channel_group or has_env_group)
    return {
        "ready": ready,
        "has_channel_token": has_channel_token,
        "has_channel_group": has_channel_group,
        "has_env_fallback": has_env_token and has_env_group,
    }


@workspaces_bp.route("/")
@login_required
def list_workspaces():
    ensure_default_workspace_for_user(current_user)
    items = list(acc.list_workspaces(current_user, active_only=False))
    switch_form = SwitchWorkspaceForm()
    active_ws = next((w for w in items if w.id == current_user.active_workspace_id), None)
    return render_template(
        "workspaces/list.html",
        workspaces=items,
        active_id=current_user.active_workspace_id,
        active_ws=active_ws,
        switch_form=switch_form,
        user_role=acc.ROLE_LABELS.get(acc.role_for_user(current_user), ""),
        can_create=acc.can(current_user, "workspace_create"),
    )


@workspaces_bp.route("/<int:workspace_id>/select", methods=["POST"])
@login_required
def select_workspace(workspace_id: int):
    """Выбрать канал (AJAX или обычный POST)."""
    ws = _user_workspace(workspace_id)
    current_user.active_workspace_id = ws.id
    db.session.commit()
    materials_bag.bind_workspace(ws.id)

    wants_json = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.accept_mimetypes.best == "application/json"
    )
    if wants_json:
        return jsonify(
            {
                "ok": True,
                "id": ws.id,
                "name": ws.name,
                "theme": ws.theme or "",
                "vk_group_id": ws.vk_group_id or "",
                "generate_url": url_for("smm.generate"),
                "drafts_url": url_for("smm.dashboard"),
                "content_plan_url": url_for(
                    "workspaces.content_plan", workspace_id=ws.id
                ),
            }
        )

    nxt = (request.form.get("next") or request.args.get("next") or "content_plan").strip()
    if nxt == "generate":
        return redirect(url_for("smm.generate"))
    if nxt == "channels":
        return redirect(url_for("workspaces.list_workspaces"))
    if nxt == "drafts":
        return redirect(url_for("smm.dashboard"))
    return redirect(url_for("workspaces.content_plan", workspace_id=ws.id))


@workspaces_bp.route("/switch", methods=["POST"])
@login_required
def switch_workspace():
    """Старый маршрут — перенаправляем на select."""
    form = SwitchWorkspaceForm()
    if not form.validate_on_submit():
        flash("Не удалось переключить канал.", "warning")
        return redirect(url_for("workspaces.list_workspaces"))
    ws_id = int(form.workspace_id.data)
    next_url = (request.form.get("next") or "drafts").strip()
    return select_workspace(ws_id)


@workspaces_bp.route("/new", methods=["GET", "POST"])
@login_required
def create_workspace():
    if not acc.can(current_user, "workspace_create"):
        flash("Создавать каналы может только владелец кабинета.", "warning")
        return redirect(url_for("workspaces.list_workspaces"))
    form = WorkspaceForm()
    if form.validate_on_submit():
        from webapp.services import business as biz

        owner_id = acc.agency_owner_id(current_user)
        ws = Workspace(
            user_id=owner_id,
            name=form.name.data.strip(),
            theme=(form.theme.data or "").strip(),
            description=(form.description.data or "").strip(),
            brand_site=(form.brand_site.data or "").strip(),
            search_hint=(form.search_hint.data or "").strip(),
            knowledge_text=(form.knowledge_text.data or "").strip(),
            visual_style_prompt=(form.visual_style_prompt.data or "").strip(),
            vk_token=seal((form.vk_token.data or "").strip()),
            vk_group_id=(form.vk_group_id.data or "").strip(),
            vk_ads_token=seal((form.vk_ads_token.data or "").strip()),
            vk_ads_account_id=(form.vk_ads_account_id.data or "").strip(),
            is_active=True,
        )
        db.session.add(ws)
        db.session.flush()
        biz.apply_package_fields(
            ws,
            code=form.package_code.data,
            custom_limit=form.package_posts_limit.data,
            require_approval=bool(form.require_client_approval.data),
            auto_publish=bool(form.auto_publish_enabled.data),
        )

        mode = form.seed_mode.data
        if mode == "nds":
            seed_rubrics_from_nds_templates(ws)
        elif mode == "generic":
            seed_generic_rubrics(ws)

        current_user.active_workspace_id = ws.id
        db.session.commit()
        flash("Канал создан. Можно настроить рубрики.", "success")
        return redirect(url_for("workspaces.rubrics", workspace_id=ws.id))
    return render_template(
        "workspaces/edit.html",
        form=form,
        workspace=None,
        vk_status=_vk_status_for_workspace(None),
        visual_refs=[],
        package_status=None,
        client_approve_url="",
    )


@workspaces_bp.route("/<int:workspace_id>/edit", methods=["GET", "POST"])
@login_required
def edit_workspace(workspace_id: int):
    ws = _user_workspace(workspace_id)
    if not acc.can(current_user, "workspace_settings", ws):
        flash("Недостаточно прав для настройки канала.", "warning")
        return redirect(url_for("workspaces.list_workspaces"))
    from webapp.services import business as biz

    form = WorkspaceForm(obj=ws)
    if request.method == "GET":
        # Не показываем токен в password-поле при открытии формы
        form.vk_token.data = ""
        form.vk_ads_token.data = ""
        if hasattr(form, "seed_mode"):
            form.seed_mode.data = "empty"

    if form.validate_on_submit():
        ws.name = form.name.data.strip()
        ws.theme = (form.theme.data or "").strip()
        ws.description = (form.description.data or "").strip()
        ws.brand_site = (form.brand_site.data or "").strip()
        ws.search_hint = (form.search_hint.data or "").strip()
        ws.knowledge_text = (form.knowledge_text.data or "").strip()
        ws.visual_style_prompt = (form.visual_style_prompt.data or "").strip()
        new_token = (form.vk_token.data or "").strip()
        if new_token:
            ws.vk_token = seal(new_token)
        ws.vk_group_id = (form.vk_group_id.data or "").strip()
        new_ads_token = (form.vk_ads_token.data or "").strip()
        if new_ads_token:
            ws.vk_ads_token = seal(new_ads_token)
        ws.vk_ads_account_id = (form.vk_ads_account_id.data or "").strip()
        old_code = (ws.package_code or "").strip()
        biz.apply_package_fields(
            ws,
            code=form.package_code.data,
            custom_limit=form.package_posts_limit.data,
            require_approval=bool(form.require_client_approval.data),
            auto_publish=bool(form.auto_publish_enabled.data),
        )
        db.session.commit()
        new_title = biz.package_title(ws.package_code)
        if (form.package_code.data or "").strip() != old_code:
            flash(f"Канал сохранён. Пакет теперь: {new_title}.", "success")
        else:
            flash("Канал сохранён.", "success")
        # Остаёмся на настройках — сразу видно новый пакет и полоску
        return redirect(url_for("workspaces.edit_workspace", workspace_id=ws.id))

    if request.method == "POST" and form.errors:
        flash("Не удалось сохранить. Проверьте поля формы.", "danger")

    token = biz.ensure_client_token(ws)
    pkg = biz.package_status(ws)
    ap_info = biz.auto_publish_queue_info(ws)
    return render_template(
        "workspaces/edit.html",
        form=form,
        workspace=ws,
        vk_status=_vk_status_for_workspace(ws),
        visual_refs=_visual_refs_for_template(ws),
        style_preview_url=(ws.visual_style_preview_url or "").strip(),
        rubric_count=Rubric.query.filter_by(workspace_id=ws.id).count(),
        marketer_resume=(ws.marketer_resume or "").strip(),
        marketer_updated_at=(ws.marketer_updated_at or "").strip(),
        marketer_has_rules=bool((ws.marketer_rules_json or "").strip()),
        package_status=pkg,
        auto_publish_info=ap_info,
        client_approve_url=url_for("smm.client_portal", token=token, _external=True),
    )


@workspaces_bp.route("/<int:workspace_id>/visual-refs/upload", methods=["POST"])
@login_required
def upload_visual_ref(workspace_id: int):
    """Загрузка референсных картинок стиля для канала."""
    ws = _user_workspace(workspace_id)
    denied = acc.guard("workspace_settings", ws)
    if denied:
        return denied
    files = request.files.getlist("reference_uploads")
    if not files or all(not f.filename for f in files):
        return jsonify({"ok": False, "error": "Выберите изображения."}), 400

    upload_dir = ws_visual.reference_upload_dir(
        Path(current_app.config["UPLOAD_FOLDER"]),
        current_user.id,
        ws.id,
    )
    added = []
    skipped = []
    for f in files:
        if not f or not f.filename:
            continue
        ext = Path(f.filename).suffix.lower()
        if ext not in ws_visual.REF_ALLOWED_EXT:
            skipped.append(f.filename)
            continue
        if len(ws_visual.load_reference_images(ws)) + len(added) >= ws_visual.MAX_REFERENCES:
            skipped.append(f.filename)
            continue
        display_name = Path(f.filename).name
        stamp = int(datetime.utcnow().timestamp() * 1000)
        safe_name = safe_storage_name(display_name)
        path = upload_dir / f"{stamp}_{safe_name}"
        try:
            path = ws_visual.save_uploaded_reference(f, path)
        except ValueError as exc:
            skipped.append(f"{display_name}: {exc}")
            continue
        relative = f"workspace/{ws.id}/refs/{path.name}"
        item = ws_visual.add_reference_image(ws, name=display_name, relative_path=relative)
        item["url"] = url_for("smm.media_file", user_id=current_user.id, filename=relative)
        added.append(item)

    if added:
        db.session.commit()

    if not added:
        msg = "Не удалось загрузить референсы."
        if skipped:
            msg += " Нужны png, jpg, jpeg, webp или gif. Не больше 8 файлов на канал."
        return jsonify({"ok": False, "error": msg}), 400

    refs = _visual_refs_for_template(ws)
    return jsonify({"ok": True, "added": added, "refs": refs, "skipped": skipped})


@workspaces_bp.route("/<int:workspace_id>/visual-refs/<ref_id>/delete", methods=["POST"])
@login_required
def delete_visual_ref(workspace_id: int, ref_id: str):
    ws = _user_workspace(workspace_id)
    denied = acc.guard("workspace_settings", ws)
    if denied:
        return denied
    removed = ws_visual.remove_reference_image(ws, ref_id)
    if not removed:
        return jsonify({"ok": False, "error": "Референс не найден."}), 404

    rel = (removed.get("path") or "").strip()
    if rel:
        file_path = Path(current_app.config["UPLOAD_FOLDER"]) / str(current_user.id) / rel
        if file_path.exists():
            try:
                file_path.unlink()
            except OSError:
                pass

    db.session.commit()
    return jsonify({"ok": True, "refs": _visual_refs_for_template(ws)})


@workspaces_bp.route("/<int:workspace_id>/style-preview/start", methods=["POST"])
@login_required
def start_style_preview(workspace_id: int):
    """Генерация примера картинки для утверждения стиля канала."""
    ws = _user_workspace(workspace_id)
    denied = acc.guard("workspace_settings", ws)
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    form_style = (data.get("visual_style_prompt") or "").strip()
    db_style = (ws.visual_style_prompt or "").strip()
    # Пустое/короткое поле на странице → берём сохранённый стиль канала
    if len(form_style) < 10:
        visual_style_prompt = db_style
    else:
        visual_style_prompt = form_style
    name = (data.get("name") or ws.name or "").strip()
    refs = ws_visual.load_reference_images(ws)
    upload_root = Path(current_app.config["UPLOAD_FOLDER"])
    local_files = ws_visual.resolve_reference_local_files(
        upload_root, current_user.id, refs
    )
    ref_names = [
        (r.get("name") or "").strip() for r in refs if (r.get("name") or "").strip()
    ]
    payload = {
        "kind": "style_preview",
        "workspace_id": ws.id,
        "name": name,
        "theme": (data.get("theme") or ws.theme or "").strip(),
        "description": (data.get("description") or ws.description or "").strip(),
        "visual_style_prompt": visual_style_prompt,
        "brand_site": (data.get("brand_site") or ws.brand_site or "").strip(),
        "reference_image_urls": ws_visual.build_media_urls(current_user.id, refs),
        "reference_local_files": local_files,
        "reference_image_names": ref_names,
    }
    if len(visual_style_prompt) < 10:
        return jsonify(
            {
                "ok": False,
                "error": (
                    "Промпт визуального стиля пустой. Заполните поле выше, "
                    "нажмите «Сохранить канал», затем снова «Сгенерировать пример»."
                ),
            }
        ), 400

    job_id = job_store.create_job(current_user.id, payload)
    app = current_app._get_current_object()
    threading.Thread(
        target=_run_style_preview_job,
        args=(app, job_id, payload),
        daemon=True,
    ).start()
    return jsonify({"ok": True, "job_id": job_id})


@workspaces_bp.route("/ai-generate-field", methods=["POST"])
@login_required
def ai_generate_field():
    """ИИ-генерация или улучшение полей настроек канала."""
    denied = acc.guard("workspace_settings")
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    field = (data.get("field") or "").strip()
    name = (data.get("name") or "").strip()
    theme = (data.get("theme") or "").strip()
    description = (data.get("description") or "").strip()
    current_text = (data.get("current_text") or "").strip()
    knowledge_text = (data.get("knowledge_text") or "").strip()
    brand_site = (data.get("brand_site") or "").strip()
    workspace_id = data.get("workspace_id")

    if field not in ws_ai.ALLOWED_FIELDS:
        return jsonify({"ok": False, "error": "Неизвестное поле для генерации."}), 400
    if len(name) < 2:
        return jsonify(
            {"ok": False, "error": "Сначала заполните название канала (минимум 2 символа)."}
        ), 400

    reference_images = None
    reference_names = ""
    refs_used = 0
    if field == "visual_style_prompt" and workspace_id:
        ws = _user_workspace(int(workspace_id))
        refs = ws_visual.load_reference_images(ws)
        if refs:
            reference_names = ws_visual.reference_names_summary(refs)
            reference_images = ws_visual.load_reference_images_b64(
                Path(current_app.config["UPLOAD_FOLDER"]),
                current_user.id,
                refs,
            )
            refs_used = len(reference_images or [])
            if refs_used == 0:
                return jsonify(
                    {
                        "ok": False,
                        "error": (
                            "Референсы есть в канале, но файлы не найдены на сервере. "
                            "Удалите старые и загрузите картинки заново."
                        ),
                    }
                ), 400
        if not knowledge_text:
            knowledge_text = (ws.knowledge_text or "").strip()
        if not brand_site:
            brand_site = (ws.brand_site or "").strip()

    try:
        text = ws_ai.generate_workspace_field(
            field,
            name=name,
            theme=theme,
            description=description,
            knowledge_text=knowledge_text,
            brand_site=brand_site,
            current_text=current_text,
            reference_images=reference_images,
            reference_names=reference_names,
        )
        improved = bool(current_text) and refs_used == 0
        return jsonify(
            {
                "ok": True,
                "text": text,
                "improved": improved,
                "refs_used": refs_used,
                "rewritten_from_refs": refs_used > 0,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": scrub_secrets(str(exc))}), 400


@workspaces_bp.route("/<int:workspace_id>/ai-generate-rubric", methods=["POST"])
@login_required
def ai_generate_rubric(workspace_id: int):
    """ИИ-генерация или улучшение промпта рубрики."""
    ws = _user_workspace(workspace_id)
    denied = acc.guard("workspace_settings", ws)
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    try:
        text = ws_ai.generate_rubric_prompt(
            workspace_name=ws.name or "",
            workspace_theme=ws.theme or "",
            workspace_description=ws.description or "",
            knowledge_text=ws.knowledge_text or "",
            rubric_code=(data.get("code") or "").strip(),
            rubric_title=(data.get("title") or "").strip(),
            current_text=(data.get("current_text") or "").strip(),
        )
        improved = bool((data.get("current_text") or "").strip())
        return jsonify({"ok": True, "text": text, "improved": improved})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": scrub_secrets(str(exc))}), 400


@workspaces_bp.route("/<int:workspace_id>/test-vk", methods=["POST"])
@login_required
def test_vk(workspace_id: int):
    """Проверка токена и группы (из формы или уже сохранённых данных)."""
    ws = _user_workspace(workspace_id)
    denied = acc.guard("workspace_settings", ws)
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    # Можно передать черновик из полей формы до сохранения
    token = (data.get("vk_token") or "").strip() or reveal(ws.vk_token)
    group_id = (data.get("vk_group_id") or "").strip() or (ws.vk_group_id or "")
    try:
        result = vk_client.test_connection(user_token=token, user_group_id=group_id)
        return jsonify({"ok": True, **result})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": scrub_secrets(str(exc))}), 400


@workspaces_bp.route("/test-vk-new", methods=["POST"])
@login_required
def test_vk_new():
    """Проверка при создании нового канала (ещё нет id)."""
    denied = acc.guard("workspace_create")
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    token = (data.get("vk_token") or "").strip()
    group_id = (data.get("vk_group_id") or "").strip()
    try:
        result = vk_client.test_connection(user_token=token, user_group_id=group_id)
        return jsonify({"ok": True, **result})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": scrub_secrets(str(exc))}), 400


@workspaces_bp.route("/<int:workspace_id>/test-ads", methods=["POST"])
@login_required
def test_ads(workspace_id: int):
    """Проверка токена VK Реклама для канала."""
    ws = _user_workspace(workspace_id)
    denied = acc.guard("workspace_settings", ws)
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    token = (data.get("vk_ads_token") or "").strip() or reveal(ws.vk_ads_token)
    try:
        result = vk_ads_client.test_connection(token=token)
        fresh = (result.get("access_token") or "").strip()
        if fresh and (
            (ws.vk_ads_token or "").strip()
            or not (data.get("vk_ads_token") or "").strip()
        ):
            # Обновлённый токен из .env/refresh — сохраним в канал, если канал уже был привязан
            if (ws.vk_ads_token or "").strip() and fresh != reveal(ws.vk_ads_token):
                ws.vk_ads_token = seal(fresh)
                db.session.commit()
        return jsonify({"ok": True, **{k: v for k, v in result.items() if k != "access_token"}})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": scrub_secrets(str(exc))}), 400


@workspaces_bp.route("/test-ads-new", methods=["POST"])
@login_required
def test_ads_new():
    """Проверка токена VK Реклама при создании канала."""
    denied = acc.guard("workspace_create")
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    token = (data.get("vk_ads_token") or "").strip()
    try:
        result = vk_ads_client.test_connection(token=token)
        public = {k: v for k, v in result.items() if k != "access_token"}
        return jsonify({"ok": True, **public})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": scrub_secrets(str(exc))}), 400


@workspaces_bp.route("/<int:workspace_id>/rubrics")
@login_required
def rubrics(workspace_id: int):
    ws = _user_workspace(workspace_id)
    items = (
        Rubric.query.filter_by(workspace_id=ws.id)
        .order_by(Rubric.sort_order.asc(), Rubric.id.asc())
        .all()
    )
    return render_template("workspaces/rubrics.html", workspace=ws, rubrics=items)


@workspaces_bp.route("/<int:workspace_id>/rubrics/new", methods=["GET", "POST"])
@login_required
def create_rubric(workspace_id: int):
    ws = _user_workspace(workspace_id)
    denied = acc.guard("workspace_settings", ws)
    if denied:
        return denied
    form = RubricForm()
    if form.validate_on_submit():
        from webapp.services.slugify import unique_rubric_code

        title = form.title.data.strip()
        existing = {
            r.code
            for r in Rubric.query.filter_by(workspace_id=ws.id).all()
            if r.code
        }
        code = unique_rubric_code(
            title,
            existing_codes=existing,
            preferred=(form.code.data or "").strip().lower() or None,
        )
        db.session.add(
            Rubric(
                workspace_id=ws.id,
                code=code,
                title=title,
                prompt_text=form.prompt_text.data.strip(),
                sort_order=form.sort_order.data or 0,
                is_active=bool(form.is_active.data),
            )
        )
        db.session.commit()
        flash(f"Рубрика добавлена (код: {code}).", "success")
        return redirect(url_for("workspaces.rubrics", workspace_id=ws.id))
    return render_template("workspaces/rubric_edit.html", form=form, workspace=ws, rubric=None)


@workspaces_bp.route("/<int:workspace_id>/rubrics/<int:rubric_id>/edit", methods=["GET", "POST"])
@login_required
def edit_rubric(workspace_id: int, rubric_id: int):
    ws = _user_workspace(workspace_id)
    denied = acc.guard("workspace_settings", ws)
    if denied:
        return denied
    rubric = Rubric.query.filter_by(id=rubric_id, workspace_id=ws.id).first_or_404()
    form = RubricForm(obj=rubric)
    if form.validate_on_submit():
        from webapp.services.slugify import unique_rubric_code

        title = form.title.data.strip()
        existing = {
            r.code
            for r in Rubric.query.filter_by(workspace_id=ws.id).all()
            if r.code
        }
        # Код при правке не меняем без нужды — стабильные ссылки в планах
        new_code = (rubric.code or "").strip().lower()
        if not new_code:
            new_code = unique_rubric_code(title, existing_codes=existing)
        rubric.code = new_code
        rubric.title = title
        rubric.prompt_text = form.prompt_text.data.strip()
        rubric.sort_order = form.sort_order.data or 0
        rubric.is_active = bool(form.is_active.data)
        db.session.commit()
        flash("Рубрика сохранена.", "success")
        return redirect(url_for("workspaces.rubrics", workspace_id=ws.id))
    return render_template(
        "workspaces/rubric_edit.html", form=form, workspace=ws, rubric=rubric
    )


@workspaces_bp.route("/<int:workspace_id>/rubrics/<int:rubric_id>/delete", methods=["POST"])
@login_required
def delete_rubric(workspace_id: int, rubric_id: int):
    ws = _user_workspace(workspace_id)
    denied = acc.guard("workspace_settings", ws)
    if denied:
        return denied
    rubric = Rubric.query.filter_by(id=rubric_id, workspace_id=ws.id).first_or_404()
    db.session.delete(rubric)
    db.session.commit()
    flash("Рубрика удалена.", "info")
    return redirect(url_for("workspaces.rubrics", workspace_id=ws.id))


def _run_marketer_brief_job(app, job_id: str, payload: dict) -> None:
    with app.app_context():
        progress = job_store.make_progress_callback(job_id)
        try:
            progress("prepare", "ИИ-маркетолог читает настройки канала…")
            ws = db.session.get(Workspace, int(payload["workspace_id"]))
            if not ws:
                raise ValueError("Канал не найден.")
            rubrics = _active_rubrics_payload(ws)
            refs = ws_visual.load_reference_images(ws)
            ref_names = ", ".join(
                (r.get("name") or "").strip()
                for r in refs
                if (r.get("name") or "").strip()
            )
            progress("content_plan", "Формирует резюме и правила для агентов…")
            brief = marketer_svc.generate_channel_marketer_brief(
                name=ws.name or "",
                theme=ws.theme or "",
                description=ws.description or "",
                brand_site=ws.brand_site or "",
                search_hint=ws.search_hint or "",
                knowledge_text=ws.knowledge_text or "",
                visual_style_prompt=ws.visual_style_prompt or "",
                reference_names=ref_names,
                rubrics=rubrics,
            )
            ws.marketer_resume = brief["resume"]
            ws.marketer_rules_json = brief["rules_json"]
            ws.marketer_updated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
            db.session.commit()
            from webapp.services import business as biz

            biz.safe_log_api_usage(
                user_id=int(payload.get("user_id") or ws.user_id),
                workspace_id=ws.id,
                kind="marketer",
                note="резюме канала",
            )
            job_store.update_job(
                job_id,
                status="done",
                step="done",
                message="Резюме канала готово",
                percent=100,
                plan_meta={
                    "resume": brief["resume"],
                    "updated_at": ws.marketer_updated_at,
                },
                error="",
            )
        except Exception as exc:  # noqa: BLE001
            db.session.rollback()
            job_store.update_job(
                job_id,
                status="error",
                step="error",
                message="Не удалось собрать резюме",
                percent=100,
                error=str(exc),
            )


@workspaces_bp.route("/<int:workspace_id>/marketer-brief", methods=["POST"])
@login_required
def marketer_brief_generate(workspace_id: int):
    """ИИ-маркетолог: резюме канала + правила для копирайтера/редактора/визуала."""
    ws = _user_workspace(workspace_id)
    denied = acc.guard("generate", ws)
    if denied:
        return denied
    # Берём актуальные значения из формы, если прислали (ещё не сохранённые)
    data = request.get_json(silent=True) or {}
    if data.get("save_fields"):
        name = (data.get("name") or ws.name or "").strip()
        if len(name) >= 2:
            ws.name = name
        ws.theme = (data.get("theme") if "theme" in data else ws.theme) or ""
        ws.theme = str(ws.theme).strip()
        if "description" in data:
            ws.description = str(data.get("description") or "").strip()
        if "brand_site" in data:
            ws.brand_site = str(data.get("brand_site") or "").strip()
        if "search_hint" in data:
            ws.search_hint = str(data.get("search_hint") or "").strip()
        if "knowledge_text" in data:
            ws.knowledge_text = str(data.get("knowledge_text") or "").strip()
        if "visual_style_prompt" in data:
            ws.visual_style_prompt = str(data.get("visual_style_prompt") or "").strip()
        db.session.commit()

    ok, err = marketer_svc.settings_ready_for_marketer(
        name=ws.name or "",
        theme=ws.theme or "",
        description=ws.description or "",
        knowledge_text=ws.knowledge_text or "",
        visual_style_prompt=ws.visual_style_prompt or "",
    )
    if not ok:
        return jsonify({"ok": False, "error": err}), 400

    payload = {"workspace_id": ws.id, "user_id": current_user.id}
    job_id = job_store.create_job(current_user.id, payload)
    app = current_app._get_current_object()
    threading.Thread(
        target=_run_marketer_brief_job,
        args=(app, job_id, payload),
        daemon=True,
    ).start()
    return jsonify({"ok": True, "job_id": job_id})


@workspaces_bp.route("/marketer-brief/job/<job_id>")
@login_required
def marketer_brief_job_status(job_id: str):
    job = job_store.get_job(job_id, user_id=current_user.id)
    if not job:
        return jsonify({"ok": False, "error": "Задание не найдено."}), 404
    return jsonify({"ok": True, "job": job})


def _active_rubrics_payload(ws: Workspace) -> list[dict[str, str]]:
    rows = (
        Rubric.query.filter_by(workspace_id=ws.id, is_active=True)
        .order_by(Rubric.sort_order.asc(), Rubric.id.asc())
        .all()
    )
    out: list[dict[str, str]] = []
    for r in rows:
        hint = (r.prompt_text or "").strip().replace("\n", " ")
        if len(hint) > 220:
            hint = hint[:220] + "…"
        item = {"code": r.code, "title": r.title}
        if hint:
            item["prompt_hint"] = hint
        out.append(item)
    return out


def _run_content_plan_job(app, job_id: str, payload: dict) -> None:
    with app.app_context():
        progress = job_store.make_progress_callback(job_id)
        try:
            progress("prepare", "ИИ-маркетолог изучает канал и аудиторию…")
            ws = db.session.get(Workspace, int(payload["workspace_id"]))
            if not ws:
                raise ValueError("Канал не найден.")
            rubrics = _active_rubrics_payload(ws)
            if not rubrics:
                raise ValueError("Нет активных рубрик. Добавьте рубрики канала.")

            days = int(payload.get("days") or 7)
            posts_count = payload.get("posts_count")
            posts_count = int(posts_count) if posts_count else None
            start_raw = str(payload.get("start_date") or "").strip()
            start_date = None
            if start_raw:
                from datetime import date as date_cls

                start_date = date_cls.fromisoformat(start_raw[:10])

            progress("content_plan", f"ИИ-маркетолог собирает план и лучшее время ({days} дн)…")
            result = plan_svc.generate_content_plan(
                workspace_name=ws.name or "",
                theme=ws.theme or "",
                description=ws.description or "",
                knowledge_text=ws.knowledge_text or "",
                brand_site=ws.brand_site or "",
                search_hint=ws.search_hint or "",
                visual_style_prompt=ws.visual_style_prompt or "",
                rubrics=rubrics,
                days=days,
                posts_count=posts_count,
                start_date=start_date,
            )
            items = result.get("items") or []
            plan_meta = {
                "audience_summary": result.get("audience_summary") or "",
                "timing_logic": result.get("timing_logic") or "",
            }
            from webapp.services import business as biz

            biz.safe_log_api_usage(
                user_id=int(payload.get("user_id") or ws.user_id),
                workspace_id=ws.id,
                kind="plan",
                note=f"контент-план {days} дн",
            )
            job_store.update_job(
                job_id,
                status="done",
                step="done",
                message=f"Готово: {len(items)} тем с временем публикации",
                percent=100,
                plan_items=items,
                plan_meta=plan_meta,
                error="",
            )
        except Exception as exc:  # noqa: BLE001
            job_store.update_job(
                job_id,
                status="error",
                step="error",
                message="ИИ-маркетолог не смог составить план",
                percent=100,
                error=str(exc),
                plan_items=[],
                plan_meta={},
            )


@workspaces_bp.route("/<int:workspace_id>/content-plan")
@login_required
def content_plan(workspace_id: int):
    """Страница контент-плана: период + ИИ-помощник."""
    from webapp.services import business as biz

    ws = _user_workspace(workspace_id)
    current_user.active_workspace_id = ws.id
    db.session.commit()
    materials_bag.bind_workspace(ws.id)
    rubrics = _active_rubrics_payload(ws)
    from datetime import date as date_cls

    saved_plans = []
    for p in biz.list_content_plans(ws):
        topics = biz.plan_items_from_json(p.items_json)
        saved_plans.append(
            {
                "plan": p,
                "topics_count": len(topics),
                "status_label": biz.client_status_label(p.client_status),
            }
        )

    return render_template(
        "workspaces/content_plan.html",
        workspace=ws,
        rubrics=rubrics,
        allowed_days=sorted(plan_svc.ALLOWED_DAYS),
        default_posts=plan_svc.DEFAULT_POSTS_BY_DAYS,
        today=date_cls.today().isoformat(),
        require_client_approval=bool(ws.require_client_approval),
        package_status=biz.package_status(ws),
        saved_plans=saved_plans,
        publish_formats=pf_choices(),
        sample_plan=_sample_plan_if_requested(),
    )


@workspaces_bp.route("/<int:workspace_id>/content-plan/generate", methods=["POST"])
@login_required
def content_plan_generate(workspace_id: int):
    ws = _user_workspace(workspace_id)
    denied = acc.guard("content", ws)
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    try:
        days = int(data.get("days") or 7)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Некорректный период."}), 400
    if days not in plan_svc.ALLOWED_DAYS:
        return jsonify({"ok": False, "error": "Выберите 7, 14, 21 или 31 день."}), 400

    posts_count = data.get("posts_count")
    try:
        posts_count = int(posts_count) if posts_count not in (None, "") else None
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Некорректное число постов."}), 400

    start_raw = str(data.get("start_date") or "").strip()
    if start_raw:
        try:
            from datetime import date as date_cls

            date_cls.fromisoformat(start_raw[:10])
        except ValueError:
            return jsonify({"ok": False, "error": "Некорректная дата начала."}), 400
    else:
        from datetime import date as date_cls

        start_raw = date_cls.today().isoformat()

    if not _active_rubrics_payload(ws):
        return jsonify(
            {
                "ok": False,
                "error": "Сначала добавьте хотя бы одну активную рубрику в канале.",
            }
        ), 400

    payload = {
        "workspace_id": ws.id,
        "user_id": current_user.id,
        "days": days,
        "posts_count": posts_count,
        "start_date": start_raw[:10],
    }
    job_id = job_store.create_job(current_user.id, payload)
    app = current_app._get_current_object()
    threading.Thread(
        target=_run_content_plan_job,
        args=(app, job_id, payload),
        daemon=True,
    ).start()
    return jsonify({"ok": True, "job_id": job_id})


@workspaces_bp.route("/content-plan/job/<job_id>")
@login_required
def content_plan_job_status(job_id: str):
    job = job_store.get_job(job_id, user_id=current_user.id)
    if not job:
        return jsonify({"ok": False, "error": "Задание не найдено."}), 404
    return jsonify({"ok": True, "job": job})


@workspaces_bp.route("/<int:workspace_id>/content-plan/send-client", methods=["POST"])
@login_required
def content_plan_send_client(workspace_id: int):
    """Отправить контент-план клиенту целиком (не по постам)."""
    from webapp.services import business as biz

    ws = _user_workspace(workspace_id)
    denied = acc.guard("content", ws)
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return jsonify({"ok": False, "error": "Нет строк плана для согласования."}), 400

    try:
        days = int(data.get("days") or 7)
    except (TypeError, ValueError):
        days = 7
    start_date = str(data.get("start_date") or "").strip()[:10]
    meta = data.get("plan_meta") if isinstance(data.get("plan_meta"), dict) else {}

    # Подставим названия рубрик для клиента
    rubrics = {
        r.code: r.title
        for r in Rubric.query.filter_by(workspace_id=ws.id, is_active=True).all()
    }
    enriched = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        code = str(row.get("rubric_code") or "").strip()
        if code and not row.get("rubric_title"):
            row["rubric_title"] = rubrics.get(code, code)
        enriched.append(row)

    try:
        batch = biz.create_plan_for_client(
            ws=ws,
            user_id=current_user.id,
            items=enriched,
            start_date=start_date,
            days=days,
            audience_summary=str(meta.get("audience_summary") or ""),
            timing_logic=str(meta.get("timing_logic") or ""),
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": scrub_secrets(str(exc))}), 400

    token = biz.ensure_client_token(ws)
    return jsonify(
        {
            "ok": True,
            "plan_id": batch.id,
            "title": batch.title,
            "client_url": url_for("smm.client_portal", token=token, _external=True),
            "approvals_url": url_for("smm.client_approvals", workspace_id=ws.id),
            "hint": "План отправлен клиенту. Когда согласует — внесите его в календарь на странице «Согласование».",
        }
    )


@workspaces_bp.route("/<int:workspace_id>/content-plan/approve", methods=["POST"])
@login_required
def content_plan_approve(workspace_id: int):
    """Утвердить план менеджером: создать черновики с датами в календаре."""
    from webapp.services import business as biz

    ws = _user_workspace(workspace_id)
    denied = acc.guard("content", ws)
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    items = data.get("items")
    plan_id = data.get("plan_id")
    batch = None
    if plan_id:
        from webapp.models import ContentPlanBatch

        batch = ContentPlanBatch.query.filter_by(
            id=int(plan_id), workspace_id=ws.id
        ).first()
        if not batch:
            return jsonify({"ok": False, "error": "План не найден."}), 404
        if bool(ws.require_client_approval) and (batch.client_status or "") != "approved":
            return jsonify(
                {
                    "ok": False,
                    "error": "Сначала дождитесь согласования контент-плана клиентом.",
                }
            ), 400
        items = biz.plan_items_from_json(batch.items_json)
    elif bool(ws.require_client_approval):
        return jsonify(
            {
                "ok": False,
                "error": "В канале включено согласование плана клиентом. "
                "Сначала нажмите «Отправить план клиенту», дождитесь согласия, "
                "затем внесите план в календарь со страницы «Согласование».",
            }
        ), 400

    if not isinstance(items, list) or not items:
        return jsonify({"ok": False, "error": "Нет строк плана для сохранения."}), 400

    try:
        biz.assert_can_add_posts(ws, len([x for x in items if isinstance(x, dict) and str(x.get("topic") or "").strip()]))
    except ValueError as exc:
        return jsonify({"ok": False, "error": scrub_secrets(str(exc))}), 400

    # Если план ещё не в архиве — сохраняем копию, чтобы потом можно было открыть
    if not batch:
        meta = data.get("plan_meta") if isinstance(data.get("plan_meta"), dict) else {}
        try:
            days = int(data.get("days") or 7)
        except (TypeError, ValueError):
            days = 7
        start_date = str(data.get("start_date") or "").strip()[:10]
        batch = biz.create_plan_for_client(
            ws=ws,
            user_id=current_user.id,
            items=items,
            start_date=start_date,
            days=days,
            audience_summary=str(meta.get("audience_summary") or ""),
            timing_logic=str(meta.get("timing_logic") or ""),
        )
        batch.client_status = "approved"
        batch.client_comment = "Внесено менеджером сразу в календарь"
        db.session.commit()

    created_ids = biz.create_planned_drafts_from_items(
        ws=ws,
        user_id=current_user.id,
        items=items,
        content_plan_id=batch.id if batch else None,
    )
    if not created_ids:
        return jsonify({"ok": False, "error": "Не удалось сохранить ни одной темы."}), 400

    if batch:
        batch.saved_to_calendar = True
        db.session.commit()

    return jsonify(
        {
            "ok": True,
            "created": len(created_ids),
            "draft_ids": created_ids,
            "plan_id": batch.id if batch else None,
            "plan_url": url_for("workspaces.content_plan_view", workspace_id=ws.id, plan_id=batch.id)
            if batch
            else "",
            "calendar_url": url_for("smm.calendar"),
            "drafts_url": url_for("smm.dashboard"),
            "queue_url": url_for("smm.generation_queue"),
            "mode": "variant_b",
            "hint": (
                "Посты сохранены в план. Текст и визуал генерируются "
                "за сутки до даты публикации — смотрите «Очередь генерации»."
            ),
        }
    )


@workspaces_bp.route("/<int:workspace_id>/content-plan/<int:plan_id>")
@login_required
def content_plan_view(workspace_id: int, plan_id: int):
    """Просмотр ранее сохранённого / согласованного контент-плана."""
    from webapp.models import ContentPlanBatch
    from webapp.services import business as biz
    from webapp.services import schedule_queue as sq

    ws = _user_workspace(workspace_id)
    plan = ContentPlanBatch.query.filter_by(id=plan_id, workspace_id=ws.id).first_or_404()
    topics = biz.plan_items_from_json(plan.items_json)
    for item in topics:
        if isinstance(item, dict):
            item["format"] = pf_code(item.get("format"))
            item["format_label"] = pf_label(item.get("format"))
    return render_template(
        "workspaces/content_plan_view.html",
        workspace=ws,
        plan=plan,
        topics=topics,
        status_label=biz.client_status_label(plan.client_status),
        format_publish_at=sq.format_publish_at,
        publish_formats=pf_choices(),
    )


@workspaces_bp.route("/<int:workspace_id>/content-plan/<int:plan_id>/formats", methods=["POST"])
@login_required
def content_plan_update_formats(workspace_id: int, plan_id: int):
    """Смена формата в уже сохранённом плане, пока он не в календаре."""
    import json

    from webapp.models import ContentPlanBatch, Draft
    from webapp.services.publish_formats import apply_to_draft

    ws = _user_workspace(workspace_id)
    denied = acc.guard("content", ws)
    if denied:
        return denied
    plan = ContentPlanBatch.query.filter_by(id=plan_id, workspace_id=ws.id).first_or_404()
    if plan.saved_to_calendar:
        flash("План уже в календаре. Формат каждого поста меняйте в карточке черновика.", "info")
        return redirect(url_for("workspaces.content_plan_view", workspace_id=ws.id, plan_id=plan.id))
    from webapp.services import business as biz

    items = biz.plan_items_from_json(plan.items_json)
    chosen = request.form.getlist("format")
    for index, item in enumerate(items):
        if isinstance(item, dict) and index < len(chosen):
            item["format"] = pf_code(chosen[index])
    plan.items_json = json.dumps(items, ensure_ascii=False)
    for draft in Draft.query.filter_by(content_plan_id=plan.id, workspace_id=ws.id).all():
        for item in items:
            if isinstance(item, dict) and (item.get("topic") or "") == (draft.topic or ""):
                kept = draft.post_text or ""
                apply_to_draft(draft, item.get("format"))
                draft.post_text = kept
                break
    db.session.commit()
    flash("Форматы в плане обновлены. Тексты постов не менялись.", "success")
    return redirect(url_for("workspaces.content_plan_view", workspace_id=ws.id, plan_id=plan.id))
