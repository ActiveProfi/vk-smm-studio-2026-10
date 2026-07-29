"""Основные экраны SMM: дашборд, генерация, предпросмотр, календарь, статистика."""
from __future__ import annotations

import ast
from datetime import datetime
from io import BytesIO
from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    url_for,
)
from flask_login import current_user, login_required
import threading
import requests

from webapp.forms import GenerateForm, PublishForm, ScheduleForm, parse_scheduled_for_parts
from webapp.models import Draft, Rubric, db
from webapp.services import materials_bag, vk_client
from webapp.services import draft_visual as dv
from webapp.services import workspace_visual as ws_visual
from webapp.services.extract_text import extract_and_cache, is_allowed_filename, safe_storage_name
from webapp.services import jobs as job_store
from webapp.services.pipeline import run_pipeline, run_visual_for_draft
from webapp.services import web_search as search_svc
from webapp.workspace_seed import ensure_default_workspace_for_user

smm_bp = Blueprint("smm", __name__)


def _active_workspace():
    ensure_default_workspace_for_user(current_user)
    ws = current_user.get_active_workspace()
    if ws:
        return ws
    return ensure_default_workspace_for_user(current_user)


def _sync_materials_for_workspace(workspace) -> None:
    """Очистить материалы, если открыли другой канал."""
    materials_bag.bind_workspace(workspace.id)


def _rubric_choices(workspace) -> list[tuple[str, str]]:
    rubrics = (
        Rubric.query.filter_by(workspace_id=workspace.id, is_active=True)
        .order_by(Rubric.sort_order.asc(), Rubric.id.asc())
        .all()
    )
    return [(r.code, r.title) for r in rubrics]


def _find_rubric(workspace, code: str) -> Rubric | None:
    return Rubric.query.filter_by(
        workspace_id=workspace.id, code=code, is_active=True
    ).first()


def _workspace_visual_payload(ws, user_id: int | None = None) -> dict:
    """Промпт стиля и URL референсов канала для генерации визуала."""
    from webapp.services import marketer_brief as marketer_svc

    uid = user_id or current_user.id
    refs = ws_visual.load_reference_images(ws)
    ref_names = [
        (r.get("name") or "").strip()
        for r in refs
        if (r.get("name") or "").strip()
    ]
    base_style = (getattr(ws, "visual_style_prompt", None) or "").strip()
    return {
        "visual_style_prompt": marketer_svc.merge_visual_style(base_style, ws),
        "reference_image_urls": ws_visual.build_media_urls(uid, refs),
        "reference_image_names": ref_names,
        "marketer_text_guidance": marketer_svc.text_agent_guidance(ws),
    }


def _manual_visual_dir(user_id: int) -> Path:
    path = Path(current_app.config["UPLOAD_FOLDER"]) / str(user_id) / "manual_visuals"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _restore_materials_from_draft(draft: Draft) -> str:
    """Вернуть материалы черновика даже для старых записей без materials_text."""
    materials = (draft.materials_text or "").strip()
    if len(materials) >= 10:
        return materials

    blocks: list[str] = []
    topic = (draft.topic or "").strip()
    if topic:
        blocks.append(f"=== Тема ===\n{topic}")

    raw_search = (draft.search_notes or "").strip()
    restored_sources: list[str] = []
    if raw_search:
        parsed = None
        try:
            parsed = ast.literal_eval(raw_search)
        except Exception:  # noqa: BLE001
            parsed = None

        if isinstance(parsed, list):
            for idx, item in enumerate(parsed[:10], start=1):
                if isinstance(item, dict):
                    title = (item.get("title") or "").strip()
                    snippet = (item.get("snippet") or "").strip()
                    url = (item.get("url") or "").strip()
                    chunk = [f"{idx}. {title or 'Источник'}"]
                    if snippet:
                        chunk.append(snippet)
                    if url:
                        chunk.append(url)
                    restored_sources.append("\n".join(chunk))
                elif item:
                    restored_sources.append(str(item).strip())
        elif raw_search:
            restored_sources.append(raw_search)

    if restored_sources:
        blocks.append(
            "=== Восстановленные материалы из прошлой генерации ===\n"
            + "\n\n".join(restored_sources)
        )

    post_text = (draft.post_text or "").strip()
    if post_text:
        blocks.append(
            "=== Текущий текст черновика ===\n"
            + post_text
            + "\n\nСделай новую версию текста на основе темы и материалов выше, "
            + "но не копируй текущий текст дословно."
        )

    return "\n\n".join(blocks).strip()


def _set_job_approval_required(job_id: str, message: str, *, draft_id: int | None = None) -> None:
    """Мягкая остановка: показать предупреждение и ждать подтверждения пользователя."""
    job_store.update_job(
        job_id,
        status="approval_required",
        step="approval_required",
        message="Проверка актуальности просит подтверждение",
        percent=18,
        warning=(message or "").strip(),
        error="",
        draft_id=draft_id,
    )


def _run_generate_job(app, job_id: str, payload: dict) -> None:
    with app.app_context():
        progress = job_store.make_progress_callback(job_id)
        try:
            progress("prepare", "Подготовка данных…")
            pipeline = run_pipeline(
                topic=payload["topic"],
                post_type=payload["post_type"],
                materials=payload["materials"],
                tone=payload["tone"],
                sources_note=payload["sources_note"],
                cta=payload["cta"],
                enable_web_search=False,
                enable_relevance=payload["enable_relevance"],
                generate_image=payload["generate_image"],
                generate_video=payload["generate_video"],
                force_continue_if_unsafe=bool(payload.get("force_continue_if_unsafe")),
                custom_prompt=payload["custom_prompt"],
                rubric_title=payload["rubric_title"],
                workspace_theme=payload["workspace_theme"],
                workspace_knowledge=payload["workspace_knowledge"],
                brand_site=payload["brand_site"],
                visual_style_prompt=payload.get("visual_style_prompt") or "",
                reference_image_urls=payload.get("reference_image_urls") or [],
                reference_image_names=payload.get("reference_image_names") or [],
                search_hint=payload["search_hint"],
                marketer_text_guidance=payload.get("marketer_text_guidance") or "",
                on_progress=progress,
            )

            if pipeline.get("approval_required"):
                _set_job_approval_required(
                    job_id,
                    pipeline.get("warning") or "Агент актуальности просит подтверждение.",
                )
                return

            if not pipeline.get("ok") and not pipeline.get("post_text"):
                job_store.update_job(
                    job_id,
                    status="error",
                    step="error",
                    message="Ошибка генерации",
                    percent=100,
                    error=pipeline.get("error") or "Неизвестная ошибка",
                )
                return

            progress("save_draft", "Сохранение черновика…")
            warning = (pipeline.get("warning") or "").strip()
            err = (pipeline.get("error") or "").strip()
            visual_requested = payload["generate_image"] or payload["generate_video"]
            has_visual = bool(pipeline.get("image_url") or pipeline.get("video_url"))
            if err and not has_visual:
                warning = (warning + " " + err).strip()
            elif err and has_visual:
                warning = (warning + " " + err).strip()
            if visual_requested and not has_visual and not warning:
                warning = "Визуал не сгенерирован. Попробуйте «Сгенерировать визуал» на странице черновика."

            continue_draft_id = payload.get("continue_draft_id")
            draft = None
            if continue_draft_id:
                draft = Draft.query.filter_by(
                    id=continue_draft_id,
                    user_id=payload["user_id"],
                    workspace_id=payload["workspace_id"],
                ).first()

            if draft:
                draft.topic = payload["topic"]
                draft.post_type = payload["post_type"]
                draft.tone = payload["tone"]
                draft.post_text = pipeline.get("post_text") or draft.post_text
                dv.apply_pipeline_urls(
                    draft,
                    pipeline,
                    generate_image=payload["generate_image"],
                    generate_video=payload["generate_video"],
                )
                draft.search_notes = pipeline.get("search_notes") or str(
                    payload.get("search_snapshot") or ""
                )
                draft.relevance_report = pipeline.get("relevance_report") or ""
                draft.materials_text = payload["materials"]
                draft.agent_answer = pipeline.get("agent_answer") or draft.agent_answer or ""
                draft.generation_warning = warning
                draft.status = "ready" if (draft.post_text and has_visual) else "draft"
            else:
                draft = Draft(
                    user_id=payload["user_id"],
                    workspace_id=payload["workspace_id"],
                    topic=payload["topic"],
                    post_type=payload["post_type"],
                    tone=payload["tone"],
                    post_text=pipeline.get("post_text") or "",
                    search_notes=pipeline.get("search_notes")
                    or str(payload.get("search_snapshot") or ""),
                    relevance_report=pipeline.get("relevance_report") or "",
                    materials_text=payload["materials"],
                    agent_answer=pipeline.get("agent_answer") or "",
                    generation_warning=warning,
                    status="ready"
                    if (
                        pipeline.get("post_text")
                        and has_visual
                    )
                    else "draft",
                )
                dv.apply_pipeline_urls(
                    draft,
                    pipeline,
                    generate_image=payload["generate_image"],
                    generate_video=payload["generate_video"],
                )
                db.session.add(draft)
            db.session.commit()

            from webapp.services import business as biz

            biz.safe_log_api_usage(
                user_id=payload["user_id"],
                workspace_id=payload["workspace_id"],
                kind="text",
                note=f"пост #{draft.id}",
            )
            if payload.get("generate_image") and pipeline.get("image_url"):
                biz.safe_log_api_usage(
                    user_id=payload["user_id"],
                    workspace_id=payload["workspace_id"],
                    kind="image",
                    note=f"пост #{draft.id}",
                )
            if payload.get("generate_video") and pipeline.get("video_url"):
                biz.safe_log_api_usage(
                    user_id=payload["user_id"],
                    workspace_id=payload["workspace_id"],
                    kind="video",
                    note=f"пост #{draft.id}",
                )

            visual_failed = visual_requested and not has_visual
            job_message = (
                "Текст готов. Визуал не получился — откройте черновик и перегенерируйте визуал."
                if visual_failed
                else "Готово"
            )
            job_store.update_job(
                job_id,
                status="done",
                step="done",
                message=job_message,
                percent=100,
                draft_id=draft.id,
                warning=warning,
                error=(warning or err) if visual_failed else ("" if pipeline.get("post_text") else (err or "Неизвестная ошибка")),
            )
        except Exception as exc:  # noqa: BLE001
            try:
                db.session.rollback()
            except Exception:  # noqa: BLE001
                pass
            job_store.update_job(
                job_id,
                status="error",
                step="error",
                message="Ошибка генерации",
                percent=100,
                error=str(exc),
            )


def _run_text_regen_job(app, job_id: str, payload: dict) -> None:
    with app.app_context():
        progress = job_store.make_progress_callback(job_id)
        draft_id = int(payload.get("draft_id") or 0)
        try:
            progress("prepare", "Подготовка данных…")
            pipeline = run_pipeline(
                topic=payload["topic"],
                post_type=payload["post_type"],
                materials=payload["materials"],
                tone=payload["tone"],
                sources_note=payload["sources_note"],
                cta=True,
                enable_web_search=False,
                enable_relevance=payload["enable_relevance"],
                generate_image=False,
                generate_video=False,
                force_continue_if_unsafe=bool(payload.get("force_continue_if_unsafe")),
                custom_prompt=payload["custom_prompt"],
                rubric_title=payload["rubric_title"],
                workspace_theme=payload["workspace_theme"],
                workspace_knowledge=payload["workspace_knowledge"],
                brand_site=payload["brand_site"],
                visual_style_prompt=payload.get("visual_style_prompt") or "",
                reference_image_urls=payload.get("reference_image_urls") or [],
                reference_image_names=payload.get("reference_image_names") or [],
                search_hint=payload["search_hint"],
                marketer_text_guidance=payload.get("marketer_text_guidance") or "",
                on_progress=progress,
            )

            if pipeline.get("approval_required"):
                _set_job_approval_required(
                    job_id,
                    pipeline.get("warning") or "Агент актуальности просит подтверждение.",
                    draft_id=draft_id or None,
                )
                return

            if not pipeline.get("post_text"):
                job_store.update_job(
                    job_id,
                    status="error",
                    step="error",
                    message="Ошибка генерации текста",
                    percent=100,
                    error=pipeline.get("error") or "Не удалось обновить текст",
                    draft_id=draft_id or None,
                )
                return

            progress("save_draft", "Сохранение черновика…")
            d = db.session.get(Draft, draft_id)
            if not d:
                job_store.update_job(
                    job_id,
                    status="error",
                    step="error",
                    message="Ошибка",
                    percent=100,
                    error="Черновик не найден",
                    draft_id=draft_id or None,
                )
                return

            d.topic = payload["topic"]
            d.post_type = payload["post_type"]
            d.tone = payload["tone"]
            d.post_text = pipeline.get("post_text") or d.post_text
            d.relevance_report = pipeline.get("relevance_report") or ""
            d.search_notes = pipeline.get("search_notes") or d.search_notes or ""
            d.agent_answer = pipeline.get("agent_answer") or d.agent_answer or ""
            d.materials_text = payload["materials"]
            d.image_url = ""
            d.video_url = ""
            d.publish_with_image = True
            d.publish_with_video = False
            d.generation_warning = "Текст обновлён. Перегенерируйте визуал, чтобы он соответствовал новому тексту."
            d.status = "draft"
            db.session.commit()

            from webapp.services import business as biz

            biz.safe_log_api_usage(
                user_id=payload["user_id"],
                workspace_id=payload.get("workspace_id"),
                kind="text",
                note=f"переген текста #{d.id}",
            )

            job_store.update_job(
                job_id,
                status="done",
                step="done",
                message="Готово",
                percent=100,
                draft_id=d.id,
                warning=d.generation_warning,
            )
        except Exception as exc:  # noqa: BLE001
            try:
                db.session.rollback()
            except Exception:  # noqa: BLE001
                pass
            job_store.update_job(
                job_id,
                status="error",
                step="error",
                message="Ошибка генерации текста",
                percent=100,
                error=str(exc),
                draft_id=draft_id or None,
            )


def _save_manual_visual(file_storage, *, user_id: int, prefix: str) -> tuple[str, str]:
    original_name = (file_storage.filename or "").strip()
    ext = Path(original_name).suffix.lower()
    stamp = int(datetime.utcnow().timestamp() * 1000)
    safe_name = safe_storage_name(original_name or f"{prefix}.bin")
    path = _manual_visual_dir(user_id) / f"{prefix}_{stamp}_{safe_name}"
    file_storage.save(path)
    relative_name = f"manual_visuals/{path.name}"
    media_url = url_for("smm.media_file", user_id=user_id, filename=relative_name)
    return media_url, path.name


def _render_generate(form, workspace, **extra):
    from webapp.services import business as biz

    bag = materials_bag.get_bag()
    return render_template(
        "smm/generate.html",
        form=form,
        workspace=workspace,
        bag_files=bag.get("files") or [],
        bag_search=bag.get("search") or [],
        bag_footer_files=bag.get("footer_files") or [],
        package_status=biz.package_status(workspace),
        **extra,
    )


@smm_bp.route("/")
@login_required
def dashboard():
    ws = _active_workspace()
    from_channel = (request.args.get("from_channel") or "").strip()
    if from_channel.isdigit():
        from webapp.models import Workspace

        cand = Workspace.query.filter_by(
            id=int(from_channel), user_id=current_user.id
        ).first()
        if cand:
            current_user.active_workspace_id = cand.id
            db.session.commit()
            materials_bag.bind_workspace(cand.id)
            ws = cand
    _sync_materials_for_workspace(ws)
    drafts = (
        Draft.query.filter_by(user_id=current_user.id, workspace_id=ws.id)
        .order_by(Draft.created_at.desc())
        .limit(20)
        .all()
    )
    from webapp.services import schedule_queue as sq

    due_count = len(sq.filter_due_for_generation(drafts))
    from webapp.services import business as biz

    return render_template(
        "smm/dashboard.html",
        drafts=drafts,
        workspace=ws,
        due_count=due_count,
        status_label_ru=sq.status_label_ru,
        needs_generation=sq.needs_generation,
        urgency_label=sq.urgency_label,
        package_status=biz.package_status(ws),
    )


@smm_bp.route("/manager")
@login_required
def manager_panel():
    """Панель управления менеджера: все каналы, статусы, уведомления за сутки."""
    from sqlalchemy import func

    from webapp.models import Rubric, Workspace
    from webapp.services import schedule_queue as sq
    from webapp.workspace_seed import ensure_default_workspace_for_user

    ensure_default_workspace_for_user(current_user)
    workspaces = (
        Workspace.query.filter_by(user_id=current_user.id)
        .order_by(Workspace.id.asc())
        .all()
    )
    drafts = Draft.query.filter_by(user_id=current_user.id).all()
    rubric_counts: dict[int, int] = {}
    if workspaces:
        rows = (
            db.session.query(Rubric.workspace_id, func.count(Rubric.id))
            .filter(Rubric.workspace_id.in_([w.id for w in workspaces]))
            .filter(Rubric.is_active.is_(True))
            .group_by(Rubric.workspace_id)
            .all()
        )
        rubric_counts = {int(wid): int(cnt) for wid, cnt in rows}

    board = sq.build_manager_board(
        workspaces,
        drafts,
        rubric_counts=rubric_counts,
    )
    from webapp.services import business as biz

    package_by_id = {w.id: biz.package_status(w) for w in workspaces}
    auto_publish_by_id = {w.id: biz.auto_publish_queue_info(w) for w in workspaces}
    api_costs_by_id = {w.id: biz.month_api_costs(w) for w in workspaces}

    return render_template(
        "smm/manager_panel.html",
        board=board,
        package_by_id=package_by_id,
        auto_publish_by_id=auto_publish_by_id,
        api_costs_by_id=api_costs_by_id,
        format_publish_at=sq.format_publish_at,
        urgency_label=sq.urgency_label,
        status_label_ru=sq.status_label_ru,
        active_id=current_user.active_workspace_id,
        hide_nav_channel_bind=True,
    )


@smm_bp.route("/generation-queue")
@login_required
def generation_queue():
    """Очередь генерации (вариант B): посты, до публикации которых ≤ 24 ч.

    Сейчас — по всем каналам текущего пользователя.
    Позже здесь же вырастет панель менеджера (уведомления по каналам).
    """
    from webapp.models import Workspace
    from webapp.services import schedule_queue as sq

    drafts = (
        Draft.query.filter_by(user_id=current_user.id)
        .filter(Draft.scheduled_for != "")
        .order_by(Draft.scheduled_for.asc())
        .all()
    )
    channel_filter = (request.args.get("channel") or "").strip()
    channel_id = int(channel_filter) if channel_filter.isdigit() else None
    if channel_id:
        drafts = [d for d in drafts if d.workspace_id == channel_id]
    due = sq.filter_due_for_generation(drafts)
    ws_ids = {d.workspace_id for d in due if d.workspace_id}
    # имена каналов для due + waiting
    name_ids = set(ws_ids)
    for d in drafts:
        if d.workspace_id:
            name_ids.add(d.workspace_id)
    workspaces: dict = {}
    if name_ids:
        workspaces = {
            w.id: w
            for w in Workspace.query.filter(Workspace.id.in_(list(name_ids))).all()
        }
    # planned but not yet in the 24h window — для понимания «что ждёт»
    waiting = [
        d
        for d in drafts
        if (d.status or "") == sq.STATUS_PLANNED
        and not sq.has_publish_materials(d)
        and not sq.needs_generation(d)
    ]
    return render_template(
        "smm/generation_queue.html",
        due=due,
        waiting=waiting,
        workspaces=workspaces,
        ahead_hours=sq.GENERATE_AHEAD_HOURS,
        status_label_ru=sq.status_label_ru,
        urgency_label=sq.urgency_label,
        hours_until_publish=sq.hours_until_publish,
        format_publish_at=sq.format_publish_at,
        active_workspace=_active_workspace(),
    )


@smm_bp.route("/generate/upload", methods=["POST"])
@login_required
def generate_upload():
    """Загрузка одного или нескольких файлов в корзину материалов."""
    ws = _active_workspace()
    _sync_materials_for_workspace(ws)
    files = request.files.getlist("uploads")
    if not files or all(not f.filename for f in files):
        return jsonify({"ok": False, "error": "Файлы не выбраны"}), 400

    upload_dir = Path(current_app.config["UPLOAD_FOLDER"]) / str(current_user.id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    added = []
    skipped = []
    for f in files:
        if not f or not f.filename:
            continue
        original_name = f.filename
        # Проверяем расширение по исходному имени (кириллица допустима)
        if not is_allowed_filename(original_name):
            skipped.append(original_name)
            continue
        name = safe_storage_name(original_name)
        stamp = int(datetime.utcnow().timestamp() * 1000)
        path = upload_dir / f"{stamp}_{name}"
        f.save(path)
        text = extract_and_cache(path)
        # В корзине показываем исходное имя файла пользователю
        display_name = Path(original_name).name
        item = materials_bag.add_file(name=display_name, path=str(path), text=text)
        added.append(item)

    if not added:
        msg = "Не удалось загрузить файлы."
        if skipped:
            msg += " Неподдерживаемый формат: " + ", ".join(skipped)
            msg += ". Нужны: txt, md, doc, docx, pdf, xls, xlsx, csv."
        return jsonify({"ok": False, "error": msg}), 400

    topic = (request.form.get("topic") or "").strip()
    summary = materials_bag.build_summary(topic=topic)
    return jsonify(
        {
            "ok": True,
            "added": added,
            "files": materials_bag.get_bag()["files"],
            "search": materials_bag.get_bag()["search"],
            "summary": summary,
        }
    )


@smm_bp.route("/generate/remove-file", methods=["POST"])
@login_required
def generate_remove_file():
    ws = _active_workspace()
    _sync_materials_for_workspace(ws)
    data = request.get_json(silent=True) or {}
    file_id = (data.get("id") or request.form.get("id") or "").strip()
    if not file_id:
        return jsonify({"ok": False, "error": "Не указан id файла"}), 400
    materials_bag.remove_file(file_id)
    topic = (data.get("topic") or request.form.get("topic") or "").strip()
    return jsonify(
        {
            "ok": True,
            "files": materials_bag.get_bag()["files"],
            "search": materials_bag.get_bag()["search"],
            "footer_files": materials_bag.get_bag().get("footer_files") or [],
            "summary": materials_bag.build_summary(topic=topic),
        }
    )


@smm_bp.route("/generate/footer-upload", methods=["POST"])
@login_required
def generate_footer_upload():
    """Загрузка файлов-образцов для подписи/логотипа внизу визуала."""
    ws = _active_workspace()
    _sync_materials_for_workspace(ws)
    files = request.files.getlist("footer_uploads")
    if not files or all(not f.filename for f in files):
        return jsonify({"ok": False, "error": "Файлы не выбраны"}), 400

    allowed = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".pdf", ".txt", ".md"}
    upload_dir = Path(current_app.config["UPLOAD_FOLDER"]) / str(current_user.id) / "footer"
    upload_dir.mkdir(parents=True, exist_ok=True)
    added = []
    skipped = []
    for f in files:
        if not f or not f.filename:
            continue
        original_name = f.filename
        ext = Path(original_name).suffix.lower()
        if ext not in allowed:
            skipped.append(original_name)
            continue
        name = safe_storage_name(original_name)
        stamp = int(datetime.utcnow().timestamp() * 1000)
        path = upload_dir / f"{stamp}_{name}"
        f.save(path)
        item = materials_bag.add_footer_file(name=Path(original_name).name, path=str(path))
        added.append(item)

    footer_text = (request.form.get("visual_footer") or "").strip()
    if footer_text:
        materials_bag.set_footer_text(footer_text)

    if not added:
        msg = "Не удалось загрузить файлы."
        if skipped:
            msg += " Нужны: png, jpg, webp, gif, svg, pdf, txt, md."
        return jsonify({"ok": False, "error": msg}), 400

    topic = (request.form.get("topic") or "").strip()
    return jsonify(
        {
            "ok": True,
            "footer_files": materials_bag.get_bag().get("footer_files") or [],
            "footer_text": materials_bag.get_footer_text(),
            "summary": materials_bag.build_summary(topic=topic),
        }
    )


@smm_bp.route("/generate/footer-remove", methods=["POST"])
@login_required
def generate_footer_remove():
    ws = _active_workspace()
    _sync_materials_for_workspace(ws)
    data = request.get_json(silent=True) or {}
    file_id = (data.get("id") or "").strip()
    if not file_id:
        return jsonify({"ok": False, "error": "Не указан id файла"}), 400
    materials_bag.remove_footer_file(file_id)
    topic = (data.get("topic") or "").strip()
    return jsonify(
        {
            "ok": True,
            "footer_files": materials_bag.get_bag().get("footer_files") or [],
            "summary": materials_bag.build_summary(topic=topic),
        }
    )


@smm_bp.route("/generate/footer-text", methods=["POST"])
@login_required
def generate_footer_text():
    ws = _active_workspace()
    _sync_materials_for_workspace(ws)
    data = request.get_json(silent=True) or {}
    text = (data.get("visual_footer") or "").strip()
    materials_bag.set_footer_text(text)
    topic = (data.get("topic") or "").strip()
    return jsonify(
        {
            "ok": True,
            "footer_text": materials_bag.get_footer_text(),
            "summary": materials_bag.build_summary(topic=topic),
        }
    )


@smm_bp.route("/generate/web-search", methods=["POST"])
@login_required
def generate_web_search():
    ws = _active_workspace()
    _sync_materials_for_workspace(ws)
    data = request.get_json(silent=True) or {}
    topic = (data.get("topic") or request.form.get("topic") or "").strip()
    if len(topic) < 3:
        return jsonify({"ok": False, "error": "Сначала укажите тему (минимум 3 символа)."}), 400

    results = search_svc.search_topic(topic, search_hint=ws.search_hint or "")
    added = materials_bag.add_search_results(results)
    return jsonify(
        {
            "ok": True,
            "added_count": len(added),
            "files": materials_bag.get_bag()["files"],
            "search": materials_bag.get_bag()["search"],
            "summary": materials_bag.build_summary(topic=topic),
        }
    )


@smm_bp.route("/generate/remove-search", methods=["POST"])
@login_required
def generate_remove_search():
    ws = _active_workspace()
    _sync_materials_for_workspace(ws)
    data = request.get_json(silent=True) or {}
    item_id = (data.get("id") or "").strip()
    if not item_id:
        return jsonify({"ok": False, "error": "Не указан id"}), 400
    materials_bag.remove_search(item_id)
    topic = (data.get("topic") or "").strip()
    return jsonify(
        {
            "ok": True,
            "files": materials_bag.get_bag()["files"],
            "search": materials_bag.get_bag()["search"],
            "summary": materials_bag.build_summary(topic=topic),
        }
    )


@smm_bp.route("/generate/refresh-summary", methods=["POST"])
@login_required
def generate_refresh_summary():
    ws = _active_workspace()
    _sync_materials_for_workspace(ws)
    data = request.get_json(silent=True) or {}
    topic = (data.get("topic") or "").strip()
    return jsonify({"ok": True, "summary": materials_bag.build_summary(topic=topic)})


@smm_bp.route("/generate/start", methods=["POST"])
@login_required
def generate_start():
    """Запуск генерации в фоне + job_id для прогресса."""
    ws = _active_workspace()
    _sync_materials_for_workspace(ws)
    form = GenerateForm()
    form.post_type.choices = _rubric_choices(ws)

    if not form.post_type.choices:
        return jsonify({"ok": False, "error": "Сначала добавьте рубрику в канале."}), 400

    if not form.validate_on_submit():
        errors = []
        for field, errs in form.errors.items():
            errors.extend(errs)
        return jsonify({"ok": False, "error": "; ".join(errors) or "Проверьте форму."}), 400

    from webapp.services import business as biz

    try:
        biz.assert_can_generate_post(ws)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    rubric = _find_rubric(ws, form.post_type.data)
    if not rubric:
        return jsonify({"ok": False, "error": "Выбранная рубрика не найдена."}), 400

    materials = (form.materials.data or "").strip()
    if len(materials) < 10:
        materials = materials_bag.build_summary(topic=(form.topic.data or "").strip())
    if len(materials) < 10:
        return jsonify(
            {
                "ok": False,
                "error": "Нет материалов. Загрузите файлы, сделайте веб-поиск или впишите тезисы.",
            }
        ), 400

    footer = (form.visual_footer.data or "").strip() or materials_bag.get_footer_text() or (ws.brand_site or "")
    if footer:
        materials_bag.set_footer_text(footer)
        # на всякий случай продублируем в саммари, если пользователь правил только поле подписи
        if "=== Подпись внизу визуала ===" not in materials:
            materials = (
                materials.rstrip()
                + "\n\n=== Подпись внизу визуала ===\n"
                + f"Текст подписи: {footer}\n"
                + "В image/video промпте добавь эту подпись маленьким текстом строго по центру в самом низу."
            )

    payload = {
        "user_id": current_user.id,
        "workspace_id": ws.id,
        "kind": "generate",
        "continue_draft_id": request.form.get("continue_draft_id", type=int),
        "topic": form.topic.data.strip(),
        "post_type": rubric.code,
        "rubric_title": rubric.title or "",
        "custom_prompt": rubric.prompt_text or "",
        "materials": materials,
        "tone": (form.tone.data or "").strip(),
        "sources_note": (form.sources_note.data or "").strip(),
        "cta": bool(form.cta.data),
        "enable_relevance": bool(form.enable_relevance.data),
        "generate_image": bool(form.generate_image.data),
        "generate_video": bool(form.generate_video.data),
        "workspace_theme": ws.theme or "",
        "workspace_knowledge": ws.knowledge_text or "",
        "brand_site": footer,
        "search_hint": ws.search_hint or "",
        "search_snapshot": list(materials_bag.get_bag().get("search") or []),
        "force_continue_if_unsafe": False,
        **_workspace_visual_payload(ws),
    }

    job_id = job_store.create_job(current_user.id, payload)
    app = current_app._get_current_object()
    threading.Thread(target=_run_generate_job, args=(app, job_id, payload), daemon=True).start()
    return jsonify({"ok": True, "job_id": job_id})


@smm_bp.route("/generate/job/<job_id>")
@login_required
def generate_job_status(job_id: str):
    job = job_store.get_job(job_id, user_id=current_user.id)
    if not job:
        return jsonify({"ok": False, "error": "Задание не найдено"}), 404
    # После успеха полной генерации очищаем корзину (не для preview стиля и догенерации)
    if job.get("status") == "done":
        payload = job_store.get_job_payload(job_id, user_id=current_user.id) or {}
        if payload.get("kind") == "generate":
            try:
                materials_bag.clear_bag()
            except RuntimeError:
                pass
    return jsonify({"ok": True, "job": job})


@smm_bp.route("/generate/job/<job_id>/approve", methods=["POST"])
@login_required
def generate_job_approve(job_id: str):
    job = job_store.get_job(job_id, user_id=current_user.id)
    if not job:
        return jsonify({"ok": False, "error": "Задание не найдено"}), 404
    if job.get("status") != "approval_required":
        return jsonify({"ok": False, "error": "Подтверждение для этого задания не требуется."}), 400

    payload = job_store.get_job_payload(job_id, user_id=current_user.id)
    if not payload:
        return jsonify({"ok": False, "error": "Не удалось восстановить параметры генерации."}), 400

    payload["force_continue_if_unsafe"] = True
    job_store.set_job_payload(job_id, payload)
    job_store.update_job(
        job_id,
        status="running",
        step="queued",
        message="Подтверждено, продолжаем генерацию…",
        percent=2,
        warning="",
        error="",
    )

    app = current_app._get_current_object()
    if payload.get("kind") == "text_only":
        threading.Thread(target=_run_text_regen_job, args=(app, job_id, payload), daemon=True).start()
    else:
        threading.Thread(target=_run_generate_job, args=(app, job_id, payload), daemon=True).start()
    return jsonify({"ok": True, "job_id": job_id})


@smm_bp.route("/generate", methods=["GET", "POST"])
@login_required
def generate():
    ws = _active_workspace()
    _sync_materials_for_workspace(ws)
    form = GenerateForm()
    form.post_type.choices = _rubric_choices(ws)
    continue_draft = None
    continue_draft_id = request.args.get("continue", type=int)
    if continue_draft_id:
        continue_draft = Draft.query.filter_by(
            id=continue_draft_id,
            user_id=current_user.id,
            workspace_id=ws.id,
        ).first()

    if not form.post_type.choices:
        flash("Сначала добавьте хотя бы одну рубрику в этом канале.", "warning")
        return redirect(url_for("workspaces.rubrics", workspace_id=ws.id))

    if request.method == "GET" and continue_draft:
        form.topic.data = continue_draft.topic or ""
        form.tone.data = continue_draft.tone or ""
        if continue_draft.post_type:
            form.post_type.data = continue_draft.post_type
        restored_materials = _restore_materials_from_draft(continue_draft)
        if restored_materials:
            form.materials.data = restored_materials
        elif not form.materials.data:
            form.materials.data = materials_bag.build_summary(topic=form.topic.data or "")
    elif request.method == "GET" and not form.materials.data:
        form.materials.data = materials_bag.build_summary(topic="")

    if request.method == "GET":
        form.visual_footer.data = (
            materials_bag.get_footer_text() or (ws.brand_site or "")
        )

    # Обычный POST оставлен как запасной путь (без JS)
    if form.validate_on_submit() and not request.headers.get("X-Requested-With"):
        # если кто-то отправил форму без JS — тоже через start нельзя просто;
        # покажем подсказку использовать кнопку с прогрессом
        flash("Обновите страницу и нажмите «Сгенерировать» ещё раз (нужен прогресс в браузере).", "info")

    return _render_generate(form, ws, continue_draft=continue_draft)


@smm_bp.route("/preview/<int:draft_id>/visual/start", methods=["POST"])
@login_required
def preview_visual_start(draft_id: int):
    """Догенерация визуала для существующего черновика — текст не пересоздаём."""
    draft = Draft.query.filter_by(id=draft_id, user_id=current_user.id).first_or_404()
    data = request.get_json(silent=True) or {}
    generate_image = bool(data.get("generate_image", True))
    generate_video = bool(data.get("generate_video", False))
    if not generate_image and not generate_video:
        return jsonify({"ok": False, "error": "Выберите картинку или видео."}), 400
    if not (draft.post_text or "").strip():
        return jsonify({"ok": False, "error": "В черновике нет текста поста."}), 400

    # Всё нужное — в обычные переменные ДО фона.
    # После commit ORM-объект draft в другом потоке «отцепляется» и ломает генерацию.
    workspace = draft.workspace
    brand_footer = (
        (data.get("visual_footer") or "").strip()
        or (workspace.brand_site if workspace else "")
        or ""
    )
    visual_ctx = _workspace_visual_payload(workspace, current_user.id)
    draft_id_copy = int(draft.id)
    post_text_copy = draft.post_text or ""
    topic_copy = draft.topic or ""
    agent_answer_copy = draft.agent_answer or ""

    payload = {
        "kind": "visual_only",
        "user_id": current_user.id,
        "workspace_id": workspace.id if workspace else draft.workspace_id,
        "draft_id": draft_id_copy,
        "generate_image": generate_image,
        "generate_video": generate_video,
        **visual_ctx,
    }
    job_id = job_store.create_job(current_user.id, payload)
    app = current_app._get_current_object()
    draft.generation_warning = ""
    db.session.commit()

    def _worker():
        with app.app_context():
            progress = job_store.make_progress_callback(job_id)
            try:
                progress("visual_prepare", "Идёт генерация визуала…")
                pipeline = run_visual_for_draft(
                    post_text=post_text_copy,
                    topic=topic_copy,
                    agent_answer=agent_answer_copy,
                    generate_image=generate_image,
                    generate_video=generate_video,
                    brand_site=brand_footer,
                    visual_style_prompt=payload.get("visual_style_prompt") or "",
                    reference_image_urls=payload.get("reference_image_urls") or [],
                    reference_image_names=payload.get("reference_image_names") or [],
                    on_progress=progress,
                )
                has_visual = bool(pipeline.get("image_url") or pipeline.get("video_url"))
                warning = (pipeline.get("warning") or "").strip()
                err = (pipeline.get("error") or "").strip()
                if err and not has_visual:
                    warning = (warning + " " + err).strip()
                elif err and has_visual:
                    warning = (warning + " " + err).strip()

                d = db.session.get(Draft, draft_id_copy)
                if not d:
                    job_store.update_job(
                        job_id,
                        status="error",
                        step="error",
                        message="Ошибка",
                        percent=100,
                        error="Черновик не найден",
                    )
                    return

                if pipeline.get("agent_answer"):
                    d.agent_answer = pipeline["agent_answer"]
                dv.apply_pipeline_urls(
                    d,
                    pipeline,
                    generate_image=generate_image,
                    generate_video=generate_video,
                )
                d.generation_warning = warning if not has_visual else ""
                if d.post_text and has_visual:
                    d.status = "ready"
                db.session.commit()

                from webapp.services import business as biz

                if generate_image and pipeline.get("image_url"):
                    biz.safe_log_api_usage(
                        user_id=payload["user_id"],
                        workspace_id=payload.get("workspace_id"),
                        kind="image",
                        note=f"визуал #{d.id}",
                    )
                if generate_video and pipeline.get("video_url"):
                    biz.safe_log_api_usage(
                        user_id=payload["user_id"],
                        workspace_id=payload.get("workspace_id"),
                        kind="video",
                        note=f"визуал #{d.id}",
                    )

                if not has_visual:
                    fail_msg = warning or "Визуал не получился."
                    job_store.update_job(
                        job_id,
                        status="done",
                        step="done",
                        message=fail_msg,
                        percent=100,
                        draft_id=d.id,
                        warning=fail_msg,
                    )
                    return

                job_store.update_job(
                    job_id,
                    status="done",
                    step="done",
                    message="Готово",
                    percent=100,
                    draft_id=d.id,
                    warning=warning,
                )
            except Exception as exc:  # noqa: BLE001
                db.session.rollback()
                job_store.update_job(
                    job_id,
                    status="error",
                    step="error",
                    message="Ошибка генерации визуала",
                    percent=100,
                    error=str(exc),
                    draft_id=draft_id_copy,
                )

    threading.Thread(target=_worker, daemon=True).start()
    return jsonify({"ok": True, "job_id": job_id})


@smm_bp.route("/preview/<int:draft_id>/visual-selection", methods=["POST"])
@login_required
def preview_visual_selection(draft_id: int):
    """Сохранить галочки «что публиковать в VK»."""
    draft = Draft.query.filter_by(id=draft_id, user_id=current_user.id).first_or_404()
    data = request.get_json(silent=True) or {}
    dv.set_publish_flags(
        draft,
        publish_with_image=bool(data.get("publish_with_image")),
        publish_with_video=bool(data.get("publish_with_video")),
    )
    db.session.commit()
    pub_image, pub_video = dv.get_publish_flags(draft)
    return jsonify(
        {
            "ok": True,
            "publish_with_image": pub_image,
            "publish_with_video": pub_video,
        }
    )


@smm_bp.route("/preview/<int:draft_id>/text/start", methods=["POST"])
@login_required
def preview_text_start(draft_id: int):
    """Перегенерация текста прямо из черновика, без возврата на форму генерации."""
    draft = Draft.query.filter_by(id=draft_id, user_id=current_user.id).first_or_404()
    workspace = draft.workspace or _active_workspace()
    rubric = _find_rubric(workspace, draft.post_type or "")
    if not rubric:
        return jsonify({"ok": False, "error": "Рубрика черновика не найдена в текущем канале."}), 400

    materials = _restore_materials_from_draft(draft)
    if len(materials) < 10:
        return jsonify(
            {
                "ok": False,
                "error": "В черновике нет материалов для перегенерации. Откройте страницу генерации и добавьте материалы.",
            }
        ), 400
    if materials != (draft.materials_text or ""):
        draft.materials_text = materials
        db.session.commit()

    payload = {
        "kind": "text_only",
        "user_id": current_user.id,
        "draft_id": draft.id,
        "workspace_id": workspace.id,
        "topic": draft.topic or "",
        "post_type": rubric.code,
        "rubric_title": rubric.title or "",
        "custom_prompt": rubric.prompt_text or "",
        "materials": materials,
        "tone": draft.tone or "",
        "sources_note": "материалы пользователя + база знаний канала",
        "enable_relevance": True,
        "workspace_theme": workspace.theme or "",
        "workspace_knowledge": workspace.knowledge_text or "",
        "brand_site": workspace.brand_site or "",
        "search_hint": workspace.search_hint or "",
        "force_continue_if_unsafe": False,
        **_workspace_visual_payload(workspace),
    }
    job_id = job_store.create_job(current_user.id, payload)
    app = current_app._get_current_object()
    threading.Thread(target=_run_text_regen_job, args=(app, job_id, payload), daemon=True).start()
    return jsonify({"ok": True, "job_id": job_id})


@smm_bp.route("/media/<int:user_id>/<path:filename>")
@login_required
def media_file(user_id: int, filename: str):
    if current_user.id != user_id:
        return "Доступ запрещён", 403
    base_dir = Path(current_app.config["UPLOAD_FOLDER"]) / str(user_id)
    return send_from_directory(base_dir, filename)


@smm_bp.route("/preview/<int:draft_id>/upload-visual", methods=["POST"])
@login_required
def preview_upload_visual(draft_id: int):
    draft = Draft.query.filter_by(id=draft_id, user_id=current_user.id).first_or_404()
    image_file = request.files.get("image_visual")
    video_file = request.files.get("video_visual")
    allowed_image = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    allowed_video = {".mp4", ".webm", ".mov", ".m4v"}

    changed_image = False
    changed_video = False
    if image_file and image_file.filename:
        ext = Path(image_file.filename).suffix.lower()
        if ext not in allowed_image:
            flash("Для изображения нужны: png, jpg, jpeg, webp или gif.", "danger")
            return redirect(url_for("smm.preview", draft_id=draft.id))
        image_url, _ = _save_manual_visual(image_file, user_id=current_user.id, prefix="image")
        draft.image_url = image_url
        changed_image = True

    if video_file and video_file.filename:
        ext = Path(video_file.filename).suffix.lower()
        if ext not in allowed_video:
            flash("Для видео нужны: mp4, webm, mov или m4v.", "danger")
            return redirect(url_for("smm.preview", draft_id=draft.id))
        video_url, _ = _save_manual_visual(video_file, user_id=current_user.id, prefix="video")
        draft.video_url = video_url
        changed_video = True

    if not changed_image and not changed_video:
        flash("Выберите изображение или видео для загрузки.", "warning")
        return redirect(url_for("smm.preview", draft_id=draft.id))

    if changed_image and not changed_video:
        draft.video_url = ""
        draft.publish_with_image = True
        draft.publish_with_video = False
    elif changed_video and not changed_image:
        draft.image_url = ""
        draft.publish_with_image = False
        draft.publish_with_video = True
    elif changed_image and changed_video:
        draft.publish_with_image = True
        draft.publish_with_video = True

    draft.generation_warning = ""
    if draft.post_text and (draft.image_url or draft.video_url):
        draft.status = "ready"
    db.session.commit()
    flash("Визуал загружен в черновик.", "success")
    return redirect(url_for("smm.preview", draft_id=draft.id))


@smm_bp.route("/preview/<int:draft_id>/download/<kind>")
@login_required
def preview_download_visual(draft_id: int, kind: str):
    draft = Draft.query.filter_by(id=draft_id, user_id=current_user.id).first_or_404()
    media_url = draft.image_url if kind == "image" else draft.video_url if kind == "video" else ""
    if not media_url:
        flash("Файл для скачивания не найден.", "warning")
        return redirect(url_for("smm.preview", draft_id=draft.id))

    if media_url.startswith("/media/"):
        prefix = f"/media/{current_user.id}/"
        filename = media_url[len(prefix):] if media_url.startswith(prefix) else ""
        if not filename:
            flash("Не удалось определить локальный файл.", "danger")
            return redirect(url_for("smm.preview", draft_id=draft.id))
        base_dir = Path(current_app.config["UPLOAD_FOLDER"]) / str(current_user.id)
        return send_from_directory(base_dir, filename, as_attachment=True)

    try:
        resp = requests.get(media_url, timeout=60)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        flash(f"Не удалось скачать визуал: {exc}", "danger")
        return redirect(url_for("smm.preview", draft_id=draft.id))

    ext = Path(media_url).suffix or (".png" if kind == "image" else ".mp4")
    download_name = f"draft-{draft.id}-{kind}{ext}"
    mimetype = resp.headers.get("Content-Type") or ("image/png" if kind == "image" else "video/mp4")
    return send_file(
        BytesIO(resp.content),
        mimetype=mimetype,
        as_attachment=True,
        download_name=download_name,
    )


@smm_bp.route("/preview/<int:draft_id>/visual/<kind>")
@login_required
def preview_visual_full(draft_id: int, kind: str):
    draft = Draft.query.filter_by(id=draft_id, user_id=current_user.id).first_or_404()
    if kind == "image":
        media_url = draft.image_url or ""
    elif kind == "video":
        media_url = draft.video_url or ""
    else:
        flash("Неизвестный тип визуала.", "warning")
        return redirect(url_for("smm.preview", draft_id=draft.id))

    if not media_url:
        flash("Визуал ещё не добавлен.", "warning")
        return redirect(url_for("smm.preview", draft_id=draft.id))

    return render_template(
        "smm/visual_full.html",
        draft=draft,
        kind=kind,
        media_url=media_url,
    )


@smm_bp.route("/preview/<int:draft_id>", methods=["GET", "POST"])
@login_required
def preview(draft_id: int):
    draft = Draft.query.filter_by(id=draft_id, user_id=current_user.id).first_or_404()
    ws = draft.workspace or _active_workspace()
    publish_form = PublishForm()
    schedule_form = ScheduleForm()
    action = request.form.get("form_action", "")

    token = (ws.vk_token if ws else "") or current_user.vk_token or ""
    group_id = (ws.vk_group_id if ws else "") or current_user.vk_group_id or ""
    vk_ready = False
    vk_group_label = group_id or "—"
    try:
        import os
        import publish_vk_scheduled as vk_pub

        vk_pub.load_dotenv_file()
        vk_ready = bool(
            (token or os.environ.get("VK_USER_TOKEN") or os.environ.get("VK_COMMUNITY_TOKEN"))
            and (group_id or os.environ.get("VK_GROUP_ID"))
        )
        vk_group_label = group_id or os.environ.get("VK_GROUP_ID", "") or "—"
    except Exception:
        vk_ready = bool(token and group_id)

    if request.method == "POST" and action == "publish" and publish_form.validate_on_submit():
        if not vk_ready:
            flash("Сначала подключите ВК в настройках канала.", "warning")
            return redirect(url_for("smm.preview", draft_id=draft.id))
        from webapp.services import business as biz

        if ws:
            ok_plan, plan_err = biz.plan_is_approved_for_draft(draft, ws)
            if not ok_plan:
                flash(plan_err, "warning")
                return redirect(url_for("smm.preview", draft_id=draft.id))
        pub_image = request.form.get("publish_with_image") == "1"
        pub_video = request.form.get("publish_with_video") == "1"
        dv.set_publish_flags(
            draft,
            publish_with_image=pub_image,
            publish_with_video=pub_video,
        )
        image_url, video_url = dv.resolve_publish_media(draft)
        if not image_url and not video_url:
            db.session.commit()
            flash("Отметьте картинку или видео для публикации.", "warning")
            return redirect(url_for("smm.preview", draft_id=draft.id))
        try:
            resp = vk_client.publish_draft(
                post_text=draft.post_text,
                image_url=image_url,
                video_url=video_url,
                topic=draft.topic,
                user_token=token,
                user_group_id=group_id,
            )
            post_id = resp.get("post_id")
            draft.vk_post_id = str(post_id) if post_id is not None else ""
            draft.status = "published"
            db.session.commit()
            flash(f"Опубликовано в ВК. post_id={draft.vk_post_id}", "success")
        except Exception as exc:  # noqa: BLE001
            flash(f"Ошибка публикации: {exc}", "danger")
        return redirect(url_for("smm.preview", draft_id=draft.id))

    if request.method == "POST" and action == "schedule" and schedule_form.validate_on_submit():
        draft.scheduled_for = getattr(schedule_form, "built_scheduled_for", "") or ""
        draft.status = "ready"
        db.session.commit()
        flash(
            f"Дата поставлена в календарь: "
            f"{schedule_form.sched_day.data}.{schedule_form.sched_month.data}."
            f"{schedule_form.sched_year.data} "
            f"{schedule_form.sched_hour.data}:{schedule_form.sched_minute.data}",
            "success",
        )
        return redirect(url_for("smm.preview", draft_id=draft.id))

    # Подставляем сохранённую дату в ячейки (при GET или если форма ещё не заполнена)
    if request.method == "GET" or action != "schedule":
        parts = parse_scheduled_for_parts(draft.scheduled_for)
        if parts["day"]:
            schedule_form.sched_day.data = parts["day"]
            schedule_form.sched_month.data = parts["month"]
            schedule_form.sched_year.data = parts["year"]
            schedule_form.sched_hour.data = parts["hour"]
            schedule_form.sched_minute.data = parts["minute"]

    pub_image, pub_video = dv.get_publish_flags(draft)
    from webapp.services import business as biz

    client_url = ""
    plan_status = ""
    if ws:
        client_url = url_for(
            "smm.client_portal",
            token=biz.ensure_client_token(ws),
            _external=True,
        )
        if draft.content_plan_id and draft.content_plan:
            plan_status = biz.client_status_label(draft.content_plan.client_status)

    return render_template(
        "smm/preview.html",
        draft=draft,
        publish_with_image=pub_image,
        publish_with_video=pub_video,
        workspace=ws,
        publish_form=publish_form,
        schedule_form=schedule_form,
        vk_ready=vk_ready,
        vk_group_label=vk_group_label,
        client_approve_url=client_url,
        require_client_approval=bool(ws.require_client_approval) if ws else False,
        plan_status=plan_status,
    )


@smm_bp.route("/calendar")
@login_required
def calendar():
    ws = _active_workspace()
    drafts = (
        Draft.query.filter_by(user_id=current_user.id, workspace_id=ws.id)
        .filter(Draft.scheduled_for != "")
        .order_by(Draft.scheduled_for.asc())
        .all()
    )
    from webapp.services import schedule_queue as sq

    return render_template(
        "smm/calendar.html",
        drafts=drafts,
        workspace=ws,
        status_label_ru=sq.status_label_ru,
        needs_generation=sq.needs_generation,
        urgency_label=sq.urgency_label,
        ahead_hours=sq.GENERATE_AHEAD_HOURS,
    )


@smm_bp.route("/stats")
@login_required
def stats():
    ws = _active_workspace()
    error = ""
    data = None
    token = ws.vk_token or current_user.vk_token or ""
    group_id = ws.vk_group_id or current_user.vk_group_id or ""
    try:
        data = vk_client.get_stats(user_token=token, user_group_id=group_id)
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
    return render_template("smm/stats.html", data=data, error=error, workspace=ws)


@smm_bp.route("/report")
@smm_bp.route("/report/<int:workspace_id>")
@login_required
def month_report(workspace_id: int | None = None):
    """Месячный отчёт клиенту: план / готово / опубликовано + расходы API."""
    from webapp.services import business as biz

    ws, year, month = _resolve_report_period(workspace_id)
    report = biz.build_month_report(ws, year=year, month=month)
    month_choices = [
        {"value": m, "label": biz.MONTH_NAMES_RU[m].capitalize()}
        for m in range(1, 13)
    ]
    return render_template(
        "smm/month_report.html",
        report=report,
        workspace=ws,
        month_title=biz.month_title_ru(year, month),
        month_choices=month_choices,
        print_mode=request.args.get("print") == "1",
    )


def _resolve_report_period(workspace_id: int | None = None):
    """Канал + год/месяц для страницы отчёта и скачивания."""
    from webapp.models import Workspace

    if workspace_id:
        ws = Workspace.query.filter_by(id=workspace_id, user_id=current_user.id).first_or_404()
        current_user.active_workspace_id = ws.id
        db.session.commit()
    else:
        ws = _active_workspace()

    now = datetime.utcnow()
    try:
        year = int(request.args.get("year") or now.year)
        month = int(request.args.get("month") or now.month)
    except (TypeError, ValueError):
        year, month = now.year, now.month
    if month < 1 or month > 12:
        month = now.month
    return ws, year, month


def _download_report_file(*, workspace_id: int, kind: str):
    """Собрать Excel/PDF и отдать как вложение (скачивание в браузере)."""
    from io import BytesIO

    from flask import send_file

    from webapp.services import business as biz
    from webapp.services import report_export as export_svc

    ws, year, month = _resolve_report_period(workspace_id)
    report = biz.build_month_report(ws, year=year, month=month)
    month_title = biz.month_title_ru(year, month)
    channel = ws.name or f"channel_{ws.id}"

    # Имя файла только латиницей — иначе часть браузеров «глотает» скачивание
    fname = f"report_ws{ws.id}_{year}-{month:02d}"
    if kind == "excel":
        data = export_svc.build_excel_bytes(
            report, channel_name=channel, month_title=month_title
        )
        return send_file(
            BytesIO(data),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=f"{fname}.xlsx",
            max_age=0,
        )
    data = export_svc.build_pdf_bytes(
        report, channel_name=channel, month_title=month_title
    )
    return send_file(
        BytesIO(data),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{fname}.pdf",
        max_age=0,
    )


@smm_bp.route("/report/<int:workspace_id>/excel")
@login_required
def month_report_excel(workspace_id: int):
    """Скачать месячный отчёт в Excel."""
    return _download_report_file(workspace_id=workspace_id, kind="excel")


@smm_bp.route("/report/<int:workspace_id>/pdf")
@login_required
def month_report_pdf(workspace_id: int):
    """Скачать месячный отчёт в PDF."""
    return _download_report_file(workspace_id=workspace_id, kind="pdf")


@smm_bp.route("/auto-publish", methods=["POST"])
@smm_bp.route("/auto-publish/<int:workspace_id>", methods=["POST"])
@login_required
def auto_publish_now(workspace_id: int | None = None):
    """Запустить автопубликацию due-постов (кнопка менеджера)."""
    from webapp.models import Workspace
    from webapp.services import business as biz

    if workspace_id:
        ws = Workspace.query.filter_by(id=workspace_id, user_id=current_user.id).first_or_404()
    else:
        ws = _active_workspace()
    result = biz.run_auto_publish_for_workspace(ws)
    if not result.get("ok"):
        flash(result.get("error") or "Автопубликация не выполнена.", "warning")
    else:
        msg = f"Проверено: {result.get('checked', 0)}. Опубликовано: {result.get('published', 0)}."
        errs = result.get("errors") or []
        if errs:
            msg += " Ошибки: " + "; ".join(errs[:5])
            flash(msg, "warning")
        else:
            flash(msg, "success")
    nxt = request.form.get("next") or request.referrer or url_for("smm.manager_panel")
    return redirect(nxt)




@smm_bp.route("/approvals")
@smm_bp.route("/approvals/<int:workspace_id>")
@login_required
def client_approvals(workspace_id: int | None = None):
    """Страница менеджера: согласование контент-планов целиком."""
    from webapp.models import Workspace
    from webapp.services import business as biz
    from webapp.services import schedule_queue as sq

    if workspace_id:
        ws = Workspace.query.filter_by(id=workspace_id, user_id=current_user.id).first_or_404()
        current_user.active_workspace_id = ws.id
        db.session.commit()
    else:
        ws = _active_workspace()

    token = biz.ensure_client_token(ws)
    client_url = url_for("smm.client_portal", token=token, _external=True)
    plans = biz.list_content_plans(ws)
    plan_rows = []
    for p in plans:
        topics = biz.plan_items_from_json(p.items_json)
        plan_rows.append(
            {
                "plan": p,
                "topics": topics,
                "topics_count": len(topics),
                "status_label": biz.client_status_label(p.client_status),
            }
        )
    pending_count = biz.count_pending_plan_approvals(ws)

    return render_template(
        "smm/client_approvals.html",
        workspace=ws,
        client_url=client_url,
        plan_rows=plan_rows,
        pending_count=pending_count,
        format_publish_at=sq.format_publish_at,
        require_client_approval=bool(ws.require_client_approval),
    )


@smm_bp.route("/approvals/<int:workspace_id>/to-calendar/<int:plan_id>", methods=["POST"])
@login_required
def client_approvals_to_calendar(workspace_id: int, plan_id: int):
    """Внести согласованный план в календарь."""
    from webapp.models import ContentPlanBatch, Workspace
    from webapp.services import business as biz

    ws = Workspace.query.filter_by(id=workspace_id, user_id=current_user.id).first_or_404()
    plan = ContentPlanBatch.query.filter_by(id=plan_id, workspace_id=ws.id).first_or_404()
    if (plan.client_status or "") != "approved":
        flash("В календарь можно внести только согласованный клиентом план.", "warning")
        return redirect(url_for("smm.client_approvals", workspace_id=ws.id))
    if plan.saved_to_calendar:
        flash("Этот план уже был внесён в календарь.", "info")
        return redirect(url_for("smm.client_approvals", workspace_id=ws.id))

    items = biz.plan_items_from_json(plan.items_json)
    try:
        biz.assert_can_add_posts(ws, len(items))
    except ValueError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("smm.client_approvals", workspace_id=ws.id))
    created = biz.create_planned_drafts_from_items(
        ws=ws,
        user_id=current_user.id,
        items=items,
        content_plan_id=plan.id,
    )
    if not created:
        flash("Не удалось создать посты из плана.", "danger")
        return redirect(url_for("smm.client_approvals", workspace_id=ws.id))
    plan.saved_to_calendar = True
    db.session.commit()
    flash(f"В календарь добавлено постов: {len(created)}.", "success")
    return redirect(url_for("smm.generation_queue"))


@smm_bp.route("/approvals/<int:workspace_id>/regen-link", methods=["POST"])
@login_required
def client_approvals_regen_link(workspace_id: int):
    from webapp.models import Workspace
    from webapp.services import business as biz

    ws = Workspace.query.filter_by(id=workspace_id, user_id=current_user.id).first_or_404()
    biz.regenerate_client_token(ws)
    flash("Ссылка обновлена. Старую ссылку клиенту больше не отправляйте.", "info")
    return redirect(url_for("smm.client_approvals", workspace_id=ws.id))


@smm_bp.route("/client/<token>", methods=["GET", "POST"])
def client_portal(token: str):
    """Публичная страница: клиент согласует контент-план целиком."""
    from webapp.models import ContentPlanBatch, Workspace
    from webapp.services import business as biz
    from webapp.services import schedule_queue as sq

    token = (token or "").strip()
    ws = Workspace.query.filter_by(client_approve_token=token).first_or_404()
    if request.method == "POST":
        plan_id = request.form.get("plan_id", type=int)
        decision = (request.form.get("decision") or "").strip()
        comment = (request.form.get("comment") or "").strip()[:1000]
        plan = ContentPlanBatch.query.filter_by(id=plan_id, workspace_id=ws.id).first()
        try:
            if not plan:
                raise ValueError("План не найден.")
            biz.decide_content_plan(plan, decision=decision, comment=comment)
            if decision == "approve":
                flash("Контент-план согласован. Спасибо!", "success")
            else:
                flash("План отклонён. Менеджер увидит комментарий.", "info")
        except ValueError as exc:
            flash(str(exc), "warning")
        return redirect(url_for("smm.client_portal", token=token))

    plans = biz.list_content_plans(ws)
    plan_rows = []
    for p in plans:
        if (p.client_status or "") not in {"pending", "approved", "rejected"}:
            continue
        topics = biz.plan_items_from_json(p.items_json)
        plan_rows.append(
            {
                "plan": p,
                "topics": topics,
                "status_label": biz.client_status_label(p.client_status),
            }
        )

    return render_template(
        "smm/client_portal.html",
        workspace=ws,
        plan_rows=plan_rows,
        format_publish_at=sq.format_publish_at,
        token=token,
    )

