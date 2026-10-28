"""Формат публикации и резерв текста KIE → Anthropic → VseGPT."""
from webapp.models import Draft, Workspace, db
from webapp.services.business import assert_can_use_video, create_planned_drafts_from_items
from webapp.services.publish_formats import apply_to_draft, normalize_format

from tests.conftest import login, make_user, make_workspace


def test_normalize_format_knows_animation_and_free_text():
    assert normalize_format("animation") == "animation"
    assert normalize_format("Видео-анимация") == "animation"
    assert normalize_format("карусель из 3 кадров") == "carousel"
    assert normalize_format("клип") == "clip"
    assert normalize_format("только текст") == "text"
    assert normalize_format("экспертный пост с картинкой") == "image"
    assert normalize_format("") == "image"


def test_format_change_keeps_post_text(app):
    owner = make_user(app, "agency-a")
    ws_id = make_workspace(app, owner)
    with app.app_context():
        draft = Draft(
            user_id=owner,
            workspace_id=ws_id,
            topic="Тема",
            post_text="Готовый текст поста, его нельзя потерять.",
            publish_format="image",
            image_url="https://cdn.example/a.png",
        )
        db.session.add(draft)
        db.session.commit()
        apply_to_draft(draft, "animation")
        db.session.commit()
        assert draft.post_text.startswith("Готовый текст")
        assert draft.publish_format == "animation"
        assert draft.publish_with_video is True
        assert draft.image_url == "https://cdn.example/a.png"


def test_plan_items_keep_chosen_format(app):
    owner = make_user(app, "agency-a")
    ws_id = make_workspace(app, owner)
    with app.app_context():
        ws = db.session.get(Workspace, ws_id)
        ids = create_planned_drafts_from_items(
            ws=ws,
            user_id=owner,
            items=[
                {"topic": "Ролик про пар", "format": "Видео-анимация", "rubric_code": "expert"},
                {"topic": "Три кадра витрины", "format": "carousel", "rubric_code": "expert"},
            ],
        )
        assert len(ids) == 2
        animation = db.session.get(Draft, ids[0])
        carousel = db.session.get(Draft, ids[1])
        assert animation.publish_format == "animation"
        assert carousel.publish_format == "carousel"
        assert animation.post_text == ""


def test_preview_format_switch_and_animation_tariff(app, client):
    owner = make_user(app, "agency-a")
    ws_id = make_workspace(app, owner)
    with app.app_context():
        ws = db.session.get(Workspace, ws_id)
        ws.package_code = "business"
        draft = Draft(
            user_id=owner,
            workspace_id=ws_id,
            topic="Тема",
            post_text="Текст, который должен остаться.",
            publish_format="image",
            status="draft",
        )
        db.session.add(draft)
        db.session.commit()
        draft_id = draft.id
    login(client, "agency-a")
    changed = client.post(
        f"/preview/{draft_id}/format",
        data={"publish_format": "animation"},
        follow_redirects=True,
    )
    assert changed.status_code == 200
    assert "Видео-анимация" in changed.get_data(as_text=True)
    with app.app_context():
        saved = db.session.get(Draft, draft_id)
        assert saved.publish_format == "animation"
        assert "должен остаться" in saved.post_text
        ws = db.session.get(Workspace, ws_id)
        try:
            assert_can_use_video(ws)
            raised = False
        except ValueError as exc:
            raised = True
            assert "Премиум" in str(exc)
        assert raised
    blocked = client.post(
        f"/preview/{draft_id}/animation/start",
        json={},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert blocked.status_code == 400
    assert "Премиум" in blocked.get_json()["error"]


def test_content_plan_page_has_format_dropdown(app, client):
    owner = make_user(app, "agency-a")
    ws_id = make_workspace(app, owner)
    login(client, "agency-a")
    page = client.get(f"/workspaces/{ws_id}/content-plan")
    body = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "Видео-анимация" in body
    assert "plan-bulk-format" in body
    assert "Поставить выбранным" in body


def test_text_fallback_uses_anthropic_before_vsegpt(monkeypatch):
    import run_agent

    calls = []

    def kie(*_args, **_kwargs):
        calls.append("kie")
        raise RuntimeError("kie недоступен")

    def anthropic(_payload, key):
        calls.append(("anthropic", key))
        return {"id": "from-anthropic"}

    monkeypatch.setattr(run_agent, "make_json_request", kie)
    monkeypatch.setattr(run_agent, "make_anthropic_request", anthropic)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anth-test-key")
    result = run_agent.send_claude_request({"messages": []}, "kie-key", "kie")
    assert result["id"] == "from-anthropic"
    assert calls[0] == "kie"
    assert calls[1][0] == "anthropic"


def test_text_fallback_reaches_vsegpt_if_anthropic_fails(monkeypatch):
    import run_agent
    import vsegpt_provider

    monkeypatch.setattr(
        run_agent,
        "make_json_request",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("kie")),
    )
    monkeypatch.setattr(
        run_agent,
        "make_anthropic_request",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("anthropic")),
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anth-test-key")
    monkeypatch.setattr(vsegpt_provider, "is_vsegpt_configured", lambda: True)
    monkeypatch.setattr(vsegpt_provider, "get_vsegpt_api_key", lambda: "vse-key")
    monkeypatch.setattr(
        vsegpt_provider,
        "send_claude_via_vsegpt",
        lambda _payload, key: {"id": "from-vsegpt", "key": key},
    )
    result = run_agent.send_claude_request({}, "kie-key", "kie")
    assert result["id"] == "from-vsegpt"
    assert result["key"] == "vse-key"
