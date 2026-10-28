"""Промпты перегенерации и возврат просроченного поста в план."""
from datetime import date, timedelta

from webapp.models import ContentPlanBatch, Draft, Workspace, db
from webapp.services.draft_schedule import is_overdue, return_draft_to_active_plan

from tests.conftest import login, make_user, make_workspace


def test_overdue_post_moves_into_active_plan(app):
    owner = make_user(app, "agency-a")
    ws_id = make_workspace(app, owner, name="Кофейня")
    with app.app_context():
        plan = ContentPlanBatch(
            workspace_id=ws_id,
            user_id=owner,
            title="Текущий план",
            items_json="[]",
            client_status="approved",
        )
        draft = Draft(
            user_id=owner,
            workspace_id=ws_id,
            topic="Старый пост",
            post_text="Текст, который нельзя потерять.",
            status="ready",
            scheduled_for="2020-01-02T10:00:00+10:00",
            image_url="https://cdn.example/old.png",
            publish_format="image",
        )
        db.session.add(plan)
        db.session.add(draft)
        db.session.commit()
        assert is_overdue(draft)
        label = return_draft_to_active_plan(draft, chosen_date="")
        assert "2020" not in (draft.scheduled_for or "")
        assert draft.status == "ready"
        assert "нельзя потерять" in draft.post_text
        assert draft.image_url.startswith("https://")
        assert draft.content_plan_id == plan.id
        assert label
        saved = db.session.get(ContentPlanBatch, plan.id)
        assert "Старый пост" in (saved.items_json or "")


def test_return_without_plan_explains(app):
    owner = make_user(app, "agency-a")
    ws_id = make_workspace(app, owner, name="Йога")
    with app.app_context():
        draft = Draft(
            user_id=owner,
            workspace_id=ws_id,
            topic="Без плана",
            post_text="Текст поста достаточно длинный.",
            status="ready",
            scheduled_for="2020-05-01T10:00:00+10:00",
        )
        db.session.add(draft)
        db.session.commit()
        try:
            return_draft_to_active_plan(draft)
            failed = False
        except ValueError as exc:
            failed = True
            assert "нет активного контент-плана" in str(exc)
            assert "Йога" in str(exc)
        assert failed
        assert draft.post_text.startswith("Текст поста")


def test_chosen_date_is_kept(app):
    owner = make_user(app, "agency-a")
    ws_id = make_workspace(app, owner)
    tomorrow = (date.today() + timedelta(days=3)).isoformat()
    with app.app_context():
        plan = ContentPlanBatch(
            workspace_id=ws_id,
            user_id=owner,
            title="План",
            items_json="[]",
            client_status="pending",
        )
        draft = Draft(
            user_id=owner,
            workspace_id=ws_id,
            topic="Перенос",
            post_text="",
            status="planned",
            scheduled_for="2020-01-02T10:00:00+10:00",
        )
        db.session.add_all([plan, draft])
        db.session.commit()
        return_draft_to_active_plan(draft, chosen_date=tomorrow)
        assert draft.scheduled_for.startswith(tomorrow)
        assert draft.status == "planned"


def test_text_regen_sends_wish_and_keeps_picture(app, monkeypatch):
    owner = make_user(app, "agency-a")
    ws_id = make_workspace(app, owner)
    captured = {}

    def fake_pipeline(**kwargs):
        captured.update(kwargs)
        return {"post_text": "Короче и с призывом.", "agent_answer": "ok", "relevance_report": ""}

    monkeypatch.setattr("webapp.smm.run_pipeline", fake_pipeline)
    with app.app_context():
        draft = Draft(
            user_id=owner,
            workspace_id=ws_id,
            topic="Запись",
            post_text="Длинный исходный текст поста для переписывания.",
            image_url="https://cdn.example/keep.png",
            publish_format="image",
            status="ready",
        )
        db.session.add(draft)
        db.session.commit()
        from webapp.smm import _run_text_regen_job

        _run_text_regen_job(
            app,
            "job-1",
            {
                "user_id": owner,
                "draft_id": draft.id,
                "workspace_id": ws_id,
                "topic": "Запись",
                "post_type": "expert",
                "rubric_title": "Эксперт",
                "custom_prompt": "Промпт рубрики",
                "materials": "Текущий текст",
                "tone": "",
                "sources_note": "материалы",
                "enable_relevance": False,
                "workspace_theme": "",
                "workspace_knowledge": "",
                "brand_site": "",
                "search_hint": "",
                "text_revision": "короче, добавь призыв записаться",
                "current_post": draft.post_text,
            },
        )
        db.session.expire_all()
        saved = db.session.get(Draft, draft.id)
        assert captured["text_revision"] == "короче, добавь призыв записаться"
        assert "исходный текст" in captured["current_post"]
        assert saved.post_text == "Короче и с призывом."
        assert saved.image_url == "https://cdn.example/keep.png"


def test_dashboard_groups_channels(app, client):
    owner = make_user(app, "agency-a")
    first = make_workspace(app, owner, name="Кофейня")
    second = make_workspace(app, owner, name="Студия йоги")
    with app.app_context():
        db.session.add(
            Draft(
                user_id=owner,
                workspace_id=first,
                topic="Пост кофе",
                post_text="Текст кофейни для списка.",
                status="published",
                publish_format="image",
            )
        )
        db.session.add(
            Draft(
                user_id=owner,
                workspace_id=second,
                topic="Пост йоги",
                post_text="Текст студии для списка.",
                status="ready",
                scheduled_for="2020-03-01T10:00:00+10:00",
                publish_format="text",
            )
        )
        db.session.commit()
    login(client, "agency-a")
    page = client.get("/")
    body = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "Кофейня" in body
    assert "Студия йоги" in body
    assert "Включить в текущий план" in body
    assert "Промпт для текста" not in body
