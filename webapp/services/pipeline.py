"""Конвейер генерации: поиск → актуальность → текст KIE → Image 2 / Kling."""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import run_agent as agent  # noqa: E402

from webapp.services import relevance as relevance_svc
from webapp.services import video_prompt_skill as video_skill
from webapp.services import web_search as search_svc

VISUAL_PROGRESS = "Идёт генерация визуала"


def _notify(on_progress, step: str, message: str | None = None) -> None:
    if on_progress:
        try:
            on_progress(step, message)
        except Exception:
            pass


def _run_with_progress_pulse(on_progress, step: str, base_message: str, fn):
    """Долгие запросы к KIE: шлём «пульс» каждые 12 сек, чтобы было видно, что процесс жив."""
    if not on_progress:
        return fn()

    stop = threading.Event()
    start = time.time()

    def _heartbeat() -> None:
        while not stop.wait(12):
            elapsed = int(time.time() - start)
            mins, secs = divmod(elapsed, 60)
            _notify(
                on_progress,
                step,
                f"{VISUAL_PROGRESS}… прошло {mins:02d}:{secs:02d}",
            )

    thread = threading.Thread(target=_heartbeat, daemon=True)
    thread.start()
    try:
        return fn()
    finally:
        stop.set()


def _append_error(result: dict, message: str) -> None:
    prev = (result.get("error") or "").strip()
    result["error"] = (prev + " " + message).strip() if prev else message.strip()


def _build_relevance_warning(relevance_data: dict | None, fallback: str = "") -> str:
    """Короткое предупреждение для пользователя без длинного JSON."""
    data = relevance_data or {}
    summary = str(data.get("summary") or fallback or "").strip()
    risky = [str(x).strip() for x in (data.get("outdated_or_risky") or []) if str(x).strip()]
    recs = [str(x).strip() for x in (data.get("recommendations") or []) if str(x).strip()]
    parts: list[str] = []
    if summary:
        parts.append(summary.rstrip("."))
    if risky:
        parts.append("Сомнение: " + risky[0].rstrip("."))
    elif recs:
        parts.append("Рекомендация: " + recs[0].rstrip("."))
    text = ". ".join(part for part in parts if part).strip()
    return text or "Агент актуальности не уверен в части фактов. Проверьте и подтвердите генерацию."


def _write_temp_input(data: dict) -> Path:
    out_dir = PROJECT_ROOT / "output" / "webapp"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"input-{int(time.time())}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def run_pipeline(
    *,
    topic: str,
    post_type: str,
    materials: str,
    tone: str,
    sources_note: str,
    cta: bool = True,
    enable_web_search: bool = True,
    enable_relevance: bool = True,
    generate_image: bool = True,
    generate_video: bool = False,
    video_provider: str = "kling",
    video_brief: dict | None = None,
    force_continue_if_unsafe: bool = False,
    custom_prompt: str = "",
    rubric_title: str = "",
    workspace_theme: str = "",
    workspace_knowledge: str = "",
    brand_site: str = "",
    visual_style_prompt: str = "",
    reference_image_urls: list[str] | None = None,
    reference_image_names: list[str] | None = None,
    reference_local_files: list[dict] | None = None,
    search_hint: str = "",
    marketer_text_guidance: str = "",
    on_progress=None,
) -> dict:
    """
    Полный прогон для веб-формы.
    custom_prompt / workspace_* — режим универсального канала.
    """
    result: dict = {
        "ok": False,
        "topic": topic,
        "post_type": post_type,
        "rubric_title": rubric_title,
        "post_text": "",
        "image_url": "",
        "video_url": "",
        "search_notes": "",
        "relevance_report": "",
        "relevance_safe": True,
        "approval_required": False,
        "error": "",
        "warning": "",
        "steps": [],
    }

    materials_list = [line.strip() for line in materials.splitlines() if line.strip()]
    if topic and not any(topic.lower() in m.lower() for m in materials_list):
        materials_list.insert(0, f"Тема поста: {topic}")
    if workspace_theme:
        materials_list.insert(0, f"Тематика канала: {workspace_theme}")
    if (marketer_text_guidance or "").strip():
        materials_list.insert(
            0,
            "Правила ИИ-маркетолога канала (копирайтер + редактор, соблюдать):\n"
            + marketer_text_guidance.strip(),
        )
    if (visual_style_prompt or "").strip():
        materials_list.insert(
            0,
            "Визуальный стиль канала (палитра, шрифты, композиция):\n"
            + visual_style_prompt.strip(),
        )
    ref_names = [n for n in (reference_image_names or []) if str(n).strip()]
    if ref_names:
        materials_list.insert(
            0,
            "Референсы стиля канала: " + ", ".join(ref_names[:8]),
        )

    search_text = ""
    search_results: list = []
    if enable_web_search:
        result["steps"].append("web_search")
        _notify(on_progress, "prepare", "Веб-поиск по теме…")
        search_results = search_svc.search_topic(topic, search_hint=search_hint)
        search_text = search_svc.format_search_for_agent(search_results)
        result["search_notes"] = search_svc.search_notes_json(search_results)
        materials_list.append("Справка из веб-поиска (проверить на актуальность):\n" + search_text)

    relevance_data: dict | None = None
    if enable_relevance:
        result["steps"].append("relevance_check")
        _notify(on_progress, "relevance_check")
        try:
            knowledge = (workspace_knowledge or "").strip()
            if not knowledge:
                knowledge = "База знаний канала не заполнена. Проверяй только материалы пользователя и веб-поиск."
            relevance_data = relevance_svc.check_relevance(
                topic=topic,
                materials=materials,
                search_text=search_text,
                knowledge_excerpt=knowledge,
                workspace_theme=workspace_theme,
            )
            result["relevance_report"] = json.dumps(relevance_data, ensure_ascii=False, indent=2)
            result["relevance_safe"] = bool(relevance_data.get("is_safe", False))
            if not result["relevance_safe"] and not force_continue_if_unsafe:
                result["approval_required"] = True
                result["warning"] = _build_relevance_warning(relevance_data)
                return result
            approved = relevance_data.get("approved_facts") or []
            if approved:
                materials_list.insert(
                    1,
                    "Одобренные факты после проверки актуальности:\n- "
                    + "\n- ".join(str(x) for x in approved),
                )
        except Exception as exc:  # noqa: BLE001
            result["relevance_report"] = json.dumps(
                {"is_safe": False, "summary": str(exc)},
                ensure_ascii=False,
            )
            result["relevance_safe"] = False
            if not force_continue_if_unsafe:
                result["approval_required"] = True
                result["warning"] = _build_relevance_warning(
                    None,
                    fallback=f"Проверка актуальности завершилась с ошибкой: {exc}",
                )
                return result

    visual_intent = "decide"
    if generate_video and not generate_image:
        visual_intent = "video"
    elif generate_image and not generate_video:
        visual_intent = "image"
    elif generate_image and generate_video:
        visual_intent = "video"
    else:
        visual_intent = "image"

    if generate_video:
        materials_list.append(
            "ОБЯЗАТЕЛЬНО: visual_intent=video. В ответе укажи visual_type: video, "
            "маршрут image_to_video или text_to_video, модель Kling, "
            "и отдельные промпты для кадра и анимации. Не подменяй видео статичной картинкой. "
            "Все надписи в кадре — только кириллица (русский алфавит), чётко и без латиницы "
            "(кроме подписи внизу, если она явно задана во входных данных)."
        )
        materials_list.append(
            video_skill.llm_video_skill_instructions(video_brief=video_brief)
        )
        if video_skill.brief_has_content(video_brief):
            materials_list.append(
                "Итоговый video_prompt_text в ответе должен совпадать с брифом пользователя "
                "по объекту/действию/месту; недостающие блоки допиши по формуле скилла."
            )

    if generate_image or generate_video:
        materials_list.append(
            "ОБЯЗАТЕЛЬНО для визуала: смысловой текст на картинке/в видео только кириллицей. "
            "В image-промпте каждую русскую фразу указывай в «ёлочках» точно по-русски. "
            "Потребуй крупный чёткий рубленый шрифт, без ошибок, без псевдокириллицы и без латиницы "
            "в смысловых блоках."
        )

    input_data = {
        "post_type": post_type,
        "raw_materials": materials_list,
        "sources_note": sources_note or "материалы пользователя + база знаний канала",
        "tone": tone or "спокойно, профессионально",
        "cta": "yes" if cta else "no",
        "visual_intent": visual_intent,
    }
    if custom_prompt.strip():
        input_data["custom_prompt"] = custom_prompt.strip()
        input_data["rubric_title"] = rubric_title or post_type
        input_data["workspace_theme"] = workspace_theme
        input_data["workspace_knowledge"] = workspace_knowledge
        input_data["brand_site"] = brand_site
        input_data["visual_style_prompt"] = visual_style_prompt
        if reference_image_urls:
            input_data["reference_image_urls"] = list(reference_image_urls)[:8]
        if reference_image_names:
            input_data["reference_image_names"] = list(reference_image_names)[:8]

    input_path = _write_temp_input(input_data)

    try:
        result["steps"].append("text_generation")
        _notify(on_progress, "text_generation")
        data = agent.load_input(input_path)
        user_message = agent.build_user_message(data)
        rubric_lock = str(data.get("rubric_title") or data.get("post_type") or "")
        payload = agent.build_claude_payload(user_message, rubric_lock=rubric_lock)
        agent.write_outputs(user_message, payload)

        provider, api_key_text = agent.resolve_text_provider("kie")
        response_data = agent.send_claude_request(payload, api_key_text, provider)
        _, response_text_path = agent.write_response_outputs(response_data)
        answer_text = agent.read_text(response_text_path)
        clean_post_text = agent.extract_vk_post_text(answer_text)
        agent.write_clean_post_output(clean_post_text)
        validation = agent.validate_clean_post_text(clean_post_text, data)
        if not validation["is_safe"]:
            result["error"] = "Текст поста не прошёл проверку: " + "; ".join(
                validation["errors"]
            )
            result["post_text"] = clean_post_text
            return result
        result["post_text"] = clean_post_text
        result["agent_answer"] = answer_text

        visual_data = None
        try:
            visual_data = agent.extract_visual_data(answer_text)
            if visual_data.get("visual_type") == "unknown":
                visual_data = None
        except Exception:
            visual_data = None

        if generate_image or generate_video:
            _generate_visuals(
                result,
                visual_data,
                generate_image=generate_image,
                generate_video=generate_video,
                video_provider=video_provider,
                video_brief=video_brief,
                topic=topic,
                brand_site=brand_site,
                visual_style_prompt=visual_style_prompt,
                reference_image_urls=reference_image_urls or [],
                reference_image_names=reference_image_names or [],
                reference_local_files=reference_local_files or [],
                on_progress=on_progress,
            )

        result["ok"] = bool(result["post_text"])
        return result
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
        return result


def _resolve_visual_data(
    *,
    agent_answer: str,
    post_text: str,
    topic: str,
    generate_image: bool,
    generate_video: bool,
    brand_site: str = "",
    visual_style_prompt: str = "",
    reference_image_urls: list[str] | None = None,
    reference_image_names: list[str] | None = None,
    video_brief: dict | None = None,
    on_progress=None,
) -> tuple[dict | None, str]:
    answer = (agent_answer or "").strip()
    if answer:
        try:
            vd = agent.extract_visual_data(answer)
            if vd.get("visual_type") != "unknown":
                return vd, answer
        except Exception:
            pass

    _notify(on_progress, "visual_prepare", f"{VISUAL_PROGRESS}…")
    visual_intent = "video" if generate_video else "image"
    footer_line = (
        f"Подпись внизу визуала: `{brand_site}` — добавь маленьким текстом строго по центру внизу.\n"
        if (brand_site or "").strip()
        else "Подпись внизу визуала не задана — не выдумывай сайт и не добавляй чужой адрес.\n"
    )
    style_line = ""
    if (visual_style_prompt or "").strip():
        style_line = (
            "Визуальный стиль канала (обязательно учесть в промпте для KIE):\n"
            f"{visual_style_prompt.strip()}\n\n"
        )
    ref_line = ""
    ref_names = [n for n in (reference_image_names or []) if str(n).strip()]
    if ref_names:
        ref_line = "Референсы стиля канала: " + ", ".join(ref_names[:8]) + ".\n\n"
    elif reference_image_urls:
        ref_line = "URL референсов стиля:\n" + "\n".join(
            f"- {u}" for u in (reference_image_urls or [])[:8]
        ) + "\n\n"
    user_message = (
        "Текст поста для VK уже готов. Нужны только промпты для визуала (разделы 3 и 4).\n\n"
        f"Тема: {topic}\n"
        f"visual_intent: {visual_intent}\n"
        f"{footer_line}"
        f"{style_line}"
        f"{ref_line}"
        f"Текст поста:\n{post_text}\n\n"
    )
    if generate_video:
        user_message += video_skill.llm_video_skill_instructions(
            video_brief=video_brief
        ) + "\n"
    user_message += (
        "Строгий формат ответа:\n"
        "## 3. Рекомендация по визуалу\n"
        "Формат: `image` (или `video` если нужен ролик).\n\n"
        "## 4. Промпт для KIE (GPT Image 2)\n"
        "Промпт для картинки обязательно в тройных кавычках markdown (```), на русском языке.\n"
        "Надписи в кадре — только кириллица, каждую фразу в «ёлочках».\n"
        "Не пиши промпт на английском и не используй blockquote (>).\n"
    )
    if generate_video:
        user_message += (
            "\nЕсли нужен ролик — отдельно дай ## 4b. Промпт для видео "
            "по формуле 6 блоков (объект, действие, место, камера, свет, стиль), "
            "тоже в тройных кавычках markdown.\n"
        )
    provider, api_key_text = agent.resolve_text_provider("kie")
    payload = agent.build_claude_payload(user_message, rubric_lock="visual")
    response_data = agent.send_claude_request(payload, api_key_text, provider)
    _, response_text_path = agent.write_response_outputs(response_data)
    new_answer = agent.read_text(response_text_path)
    try:
        vd = agent.extract_visual_data(new_answer)
        if vd.get("visual_type") == "unknown":
            return None, new_answer
        return vd, new_answer
    except Exception:
        return None, new_answer


def _generate_visuals(
    result: dict,
    visual_data: dict | None,
    *,
    generate_image: bool,
    generate_video: bool,
    video_provider: str = "kling",
    video_brief: dict | None = None,
    topic: str = "",
    brand_site: str = "",
    visual_style_prompt: str = "",
    reference_image_urls: list[str] | None = None,
    reference_image_names: list[str] | None = None,
    reference_local_files: list[dict] | None = None,
    on_progress=None,
) -> None:
    kie_key = agent.get_api_key()
    _notify(on_progress, "visual_prepare", f"{VISUAL_PROGRESS}…")
    # Публичные URL (не localhost) + локальные файлы → generation refs в run_agent
    ref_urls = list(reference_image_urls or [])
    local_files = list(reference_local_files or [])
    ref_names = list(reference_image_names or [])
    style_suffix = ""
    if (visual_style_prompt or "").strip():
        style_suffix = (
            "\n\nСтиль канала (обязательно): "
            + visual_style_prompt.strip()[:1200]
        )

    if not visual_data:
        # Если есть бриф пользователя — всё равно можно собрать видеопромпт без ответа LLM
        if generate_video and video_skill.brief_has_content(video_brief):
            visual_data = {}
        else:
            _append_error(
                result,
                "Визуал не создан: модель не вернула промпт для картинки или видео.",
            )
            return

    # Скилл: пользовательский бриф перекрывает / дополняет video_prompt_text
    if generate_video:
        visual_data = video_skill.apply_video_brief_to_visual_data(
            visual_data,
            video_brief,
            topic=topic,
            channel_style=visual_style_prompt or "",
        ) or visual_data

    need_still_image = generate_image or generate_video
    if need_still_image and visual_data:
        image_prompt = (
            visual_data.get("image_prompt_text")
            or visual_data.get("prompt_text")
            or ""
        ).strip()
        if not image_prompt and generate_image and not generate_video:
            _append_error(result, "Визуал не создан: пустой промпт для картинки.")
        elif image_prompt and (generate_image or generate_video):
            try:
                result["steps"].append("image_gpt_image_2")
                _notify(on_progress, "image_gpt_image_2", f"{VISUAL_PROGRESS}…")
                has_any_ref = bool(local_files) or bool(
                    agent.filter_public_reference_urls(ref_urls)
                )
                prompt_with_refs = agent.append_real_photo_reference_rule(
                    image_prompt + style_suffix,
                    has_references=has_any_ref,
                )
                image_vd = {
                    "prompt_text": prompt_with_refs,
                    "aspect_ratio": visual_data.get(
                        "image_prompt_aspect_ratio",
                        visual_data.get("aspect_ratio", "9:16" if generate_video else "4:5"),
                    ),
                    "resolution": visual_data.get(
                        "image_prompt_resolution",
                        visual_data.get("resolution", "1K"),
                    ),
                    "output_format": visual_data.get(
                        "image_prompt_output_format",
                        visual_data.get("output_format", "png"),
                    ),
                }
                image_vd, vreport = agent.validate_and_prepare_image_visual_data(
                    image_vd, brand_footer=brand_site
                )
                agent.write_visual_validation_report(image_vd, vreport)
                if vreport["is_safe"]:
                    _notify(
                        on_progress,
                        "image_gpt_image_2",
                        f"{VISUAL_PROGRESS}… generation refs",
                    )

                    def _image_job() -> tuple[str, str]:
                        return agent.generate_image_url_with_fallback(
                            image_vd,
                            reference_image_urls=ref_urls,
                            reference_local_files=local_files,
                            reference_image_names=ref_names,
                            kie_key=kie_key,
                            allow_no_person_fallback=True,
                        )

                    try:
                        image_url, provider_label = _run_with_progress_pulse(
                            on_progress,
                            "image_gpt_image_2",
                            VISUAL_PROGRESS,
                            _image_job,
                        )
                    except agent.RealPersonReferenceUnavailableError as ref_fail:
                        _append_error(result, str(ref_fail))
                        image_url, provider_label = "", ""
                    except Exception as img_fail:  # noqa: BLE001
                        _append_error(result, str(img_fail))
                        image_url, provider_label = "", ""

                    if image_url:
                        result["image_url"] = image_url
                        if agent.REAL_PERSON_REFERENCE_UNAVAILABLE in (
                            image_vd.get("prompt_text") or ""
                        ):
                            result["warning"] = (
                                (result.get("warning") or "")
                                + " "
                                + agent.REAL_PERSON_REFERENCE_UNAVAILABLE
                                + ": сцена без конкретного человека (нет generation reference)."
                            ).strip()
                        if "резерв" in (provider_label or "").lower():
                            result["warning"] = (
                                (result.get("warning") or "")
                                + f" Картинка создана через резерв {provider_label}."
                            ).strip()
                        elif "image-to-image" in (provider_label or "").lower():
                            result["warning"] = (
                                (result.get("warning") or "")
                                + " Картинка с реальным фото-референсом (KIE image-to-image)."
                            ).strip()
                else:
                    _append_error(
                        result,
                        "Промпт для картинки не прошёл проверку: "
                        + "; ".join(vreport.get("errors") or []),
                    )
            except Exception as img_exc:  # noqa: BLE001
                _append_error(result, f"Ошибка картинки: {img_exc}")

    if generate_video:
        provider = agent.normalize_video_provider(video_provider, default="kling")
        provider_label = agent.VIDEO_PROVIDER_LABELS.get(provider, provider)
        step_name = f"video_{provider}"
        if not visual_data:
            _append_error(result, "Видео не создано: нет данных для видео.")
        else:
            try:
                video_vd = _coerce_visual_for_video(visual_data, provider)
                # Запреты из брифа — в конец промпта (безопасный путь для всех моделей)
                neg = (video_vd.get("video_negative_prompt") or "").strip()
                if not neg and video_brief:
                    neg = video_skill.resolve_negative_prompt(video_brief)
                if neg:
                    video_vd["video_prompt_text"] = video_skill.attach_negative_to_prompt_if_needed(
                        video_vd.get("video_prompt_text") or "",
                        neg,
                        provider=provider,
                    )
                if not (video_vd.get("video_prompt_text") or "").strip():
                    _append_error(result, "Видео не создано: нет промпта для видео.")
                else:
                    result["steps"].append(step_name)
                    _notify(on_progress, step_name, f"{VISUAL_PROGRESS}… {provider_label}")
                    base_image_url = result.get("image_url") or None
                    video_route = video_vd.get("video_route", "text_to_video")
                    if video_vd.get("video_has_text_overlay"):
                        video_route = "image_to_video"
                    if base_image_url:
                        video_route = "image_to_video"
                    if video_route == "image_to_video" and not base_image_url:
                        video_route = "text_to_video"
                        _append_error(
                            result,
                            "Кадр для видео не готов, пробуем другой режим.",
                        )

                    use_image = base_image_url if video_route == "image_to_video" else None

                    def _make_payload(kling_mode: str = "pro") -> dict:
                        return agent.build_video_payload(
                            video_vd,
                            provider,
                            base_image_url=use_image,
                            kling_mode=kling_mode,
                        )

                    video_payload = _make_payload("pro" if provider == "kling" else "pro")
                    try:
                        video_create = agent.create_video_task(video_payload, kie_key)
                    except Exception as create_exc:  # noqa: BLE001
                        if provider == "kling":
                            _notify(
                                on_progress,
                                step_name,
                                f"{VISUAL_PROGRESS}… {provider_label} повтор",
                            )
                            video_payload = _make_payload("std")
                            video_create = agent.create_video_task(video_payload, kie_key)
                            _append_error(
                                result,
                                f"Первый запрос видео не прошёл ({create_exc}); повтор.",
                            )
                        else:
                            raise

                    video_task_id = video_create.get("data", {}).get("taskId", "")
                    if not video_task_id:
                        _append_error(result, "Сервис не принял задачу на видео.")
                    else:
                        try:
                            video_result = _run_with_progress_pulse(
                                on_progress,
                                step_name,
                                f"{VISUAL_PROGRESS} ({provider_label})",
                                lambda: agent.wait_for_any_video_result(
                                    video_task_id, kie_key, provider, timeout_sec=900
                                ),
                            )
                        except Exception as wait_exc:  # noqa: BLE001
                            if provider != "kling":
                                raise
                            _notify(
                                on_progress,
                                step_name,
                                f"{VISUAL_PROGRESS}… {provider_label} повтор",
                            )
                            video_payload = _make_payload("std")
                            video_create = agent.create_video_task(video_payload, kie_key)
                            video_task_id = video_create.get("data", {}).get("taskId", "")
                            if not video_task_id:
                                raise wait_exc
                            video_result = _run_with_progress_pulse(
                                on_progress,
                                step_name,
                                f"{VISUAL_PROGRESS} ({provider_label})",
                                lambda: agent.wait_for_any_video_result(
                                    video_task_id, kie_key, provider, timeout_sec=900
                                ),
                            )
                            _append_error(result, f"Повтор после: {wait_exc}")

                        agent.write_video_outputs(
                            video_vd, video_payload, video_create, video_result
                        )
                        video_urls = agent.extract_result_urls(video_result)
                        if video_urls:
                            result["video_url"] = video_urls[0]
                            result["video_provider"] = provider
                            soft = (result.get("error") or "").strip()
                            if soft and "не создано" not in soft.lower():
                                result["warning"] = soft
                            result["error"] = ""
                        else:
                            _append_error(result, "Видео готово, но ссылка не получена.")
            except Exception as vid_exc:  # noqa: BLE001
                _append_error(result, f"Ошибка видео ({provider_label}): {vid_exc}")

    if generate_video and not result.get("video_url"):
        if not (result.get("error") or "").strip():
            _append_error(result, "Видео не сгенерировано. Проверьте галочку «Видео» и ключ API.")

    if generate_image and not generate_video and not result.get("image_url"):
        if visual_data and visual_data.get("visual_type") not in ("image", "video", "unknown"):
            _append_error(
                result,
                f"Модель выбрала другой тип визуала ({visual_data.get('visual_type')}), картинка не создана.",
            )
        elif not (result.get("error") or "").strip():
            _append_error(result, "Картинка не сгенерирована. Проверьте галочку «Картинка» и ключ API.")


def run_visual_for_draft(
    *,
    post_text: str,
    topic: str,
    agent_answer: str = "",
    generate_image: bool = True,
    generate_video: bool = False,
    video_provider: str = "kling",
    video_brief: dict | None = None,
    brand_site: str = "",
    visual_style_prompt: str = "",
    reference_image_urls: list[str] | None = None,
    reference_image_names: list[str] | None = None,
    reference_local_files: list[dict] | None = None,
    on_progress=None,
) -> dict:
    """Догенерация визуала для готового черновика — текст не трогаем."""
    result: dict = {
        "ok": False,
        "image_url": "",
        "video_url": "",
        "error": "",
        "warning": "",
        "agent_answer": agent_answer or "",
        "steps": [],
    }
    if not (post_text or "").strip():
        result["error"] = "В черновике нет текста поста."
        return result
    if not generate_image and not generate_video:
        result["error"] = "Выберите картинку или видео."
        return result

    visual_data, new_answer = _resolve_visual_data(
        agent_answer=agent_answer,
        post_text=post_text,
        topic=topic or "пост",
        generate_image=generate_image,
        generate_video=generate_video,
        brand_site=brand_site,
        visual_style_prompt=visual_style_prompt,
        reference_image_urls=reference_image_urls,
        reference_image_names=reference_image_names,
        video_brief=video_brief,
        on_progress=on_progress,
    )
    if new_answer:
        result["agent_answer"] = new_answer

    _generate_visuals(
        result,
        visual_data,
        generate_image=generate_image,
        generate_video=generate_video,
        video_provider=video_provider,
        video_brief=video_brief,
        topic=topic or "",
        brand_site=brand_site,
        visual_style_prompt=visual_style_prompt,
        reference_image_urls=reference_image_urls or [],
        reference_image_names=reference_image_names or [],
        reference_local_files=reference_local_files or [],
        on_progress=on_progress,
    )
    result["ok"] = bool(result.get("image_url") or result.get("video_url"))
    return result


def _coerce_visual_for_video(visual_data: dict, video_provider: str = "kling") -> dict:
    """Если модель вернула image вместо video — готовим данные под выбранный провайдер."""
    provider = agent.normalize_video_provider(video_provider, default="kling")
    vd = dict(visual_data)
    vd["visual_type"] = "video"
    vd["video_model"] = provider

    image_prompt = (
        (vd.get("image_prompt_text") or "").strip()
        or (vd.get("prompt_text") or "").strip()
    )
    video_prompt = (vd.get("video_prompt_text") or "").strip()

    if not video_prompt and image_prompt:
        video_prompt = (
            "Анимация того же кадра: лёгкое приближение камеры, мягкое движение элементов, "
            "текст в кадре остаётся читаемым, без новых надписей, вертикальный формат 9:16."
        )
    if not image_prompt and video_prompt:
        image_prompt = video_prompt

    vd["image_prompt_text"] = image_prompt
    vd["prompt_text"] = image_prompt or vd.get("prompt_text", "")
    vd["video_prompt_text"] = video_prompt or image_prompt
    # Текст в инфографике почти всегда есть → image_to_video
    has_text = bool(image_prompt) and (
        "«" in image_prompt
        or '"' in image_prompt
        or "заголовок" in image_prompt.lower()
        or "текст" in image_prompt.lower()
        or "кириллиц" in image_prompt.lower()
    )
    vd["video_has_text_overlay"] = bool(vd.get("video_has_text_overlay")) or has_text
    if has_text:
        vd["video_route"] = "image_to_video"
    elif not vd.get("video_route"):
        vd["video_route"] = "text_to_video"
    vd.setdefault("image_prompt_aspect_ratio", "9:16")
    vd.setdefault("image_prompt_resolution", "1K")
    vd.setdefault("image_prompt_output_format", "png")
    vd.setdefault("aspect_ratio", "9:16")
    vd.setdefault("resolution", "1K")
    return vd


# Совместимость со старым именем
def _coerce_visual_for_kling(visual_data: dict) -> dict:
    return _coerce_visual_for_video(visual_data, "kling")
