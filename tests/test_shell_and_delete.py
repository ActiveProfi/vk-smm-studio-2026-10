"""Удаление черновика и каркас кабинета."""
from webapp.models import Draft, db

from tests.conftest import login, make_user, make_workspace


def test_delete_only_this_draft(app, client):
    owner = make_user(app, "agency-a")
    ws_id = make_workspace(app, owner, name="Кофейня")
    with app.app_context():
        keep = Draft(
            user_id=owner,
            workspace_id=ws_id,
            topic="Оставить",
            post_text="Этот пост должен остаться.",
            status="ready",
        )
        drop = Draft(
            user_id=owner,
            workspace_id=ws_id,
            topic="Убрать",
            post_text="Этот черновик удаляем.",
            status="draft",
        )
        db.session.add_all([keep, drop])
        db.session.commit()
        drop_id = drop.id
        keep_id = keep.id
    login(client, "agency-a")
    page = client.get("/")
    assert "Удалить черновик" in page.get_data(as_text=True)
    gone = client.post(f"/drafts/{drop_id}/delete", follow_redirects=True)
    assert "удалён" in gone.get_data(as_text=True).lower() or "удален" in gone.get_data(as_text=True).lower()
    with app.app_context():
        assert db.session.get(Draft, drop_id) is None
        assert db.session.get(Draft, keep_id) is not None


def test_delete_published_keeps_note_about_vk(app, client):
    owner = make_user(app, "agency-a")
    ws_id = make_workspace(app, owner)
    with app.app_context():
        draft = Draft(
            user_id=owner,
            workspace_id=ws_id,
            topic="Уже в ленте",
            post_text="Опубликованный текст.",
            status="published",
            vk_post_id="99",
        )
        db.session.add(draft)
        db.session.commit()
        draft_id = draft.id
    login(client, "agency-a")
    body = client.get("/").get_data(as_text=True)
    assert "Пост во ВКонтакте останется" in body
    done = client.post(f"/drafts/{draft_id}/delete", follow_redirects=True)
    text = done.get_data(as_text=True)
    assert "ВКонтакте" in text
    with app.app_context():
        assert db.session.get(Draft, draft_id) is None


def test_preview_has_vk_screen_and_sidebar(app, client):
    owner = make_user(app, "agency-a")
    ws_id = make_workspace(app, owner, name="Кофейня")
    with app.app_context():
        draft = Draft(
            user_id=owner,
            workspace_id=ws_id,
            topic="Макет",
            post_text="Так пост увидят в ленте.",
            status="draft",
            publish_format="image",
        )
        db.session.add(draft)
        db.session.commit()
        draft_id = draft.id
    login(client, "agency-a")
    page = client.get(f"/preview/{draft_id}")
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "vk-card" in html
    assert "Промпт для текста" in html
    assert "Сгенерировать" in html
    assert 'data-studio="calendar"' in html
    home = client.get("/manager")
    assert "Дашборд" in home.get_data(as_text=True)
    assert "crm-side" in home.get_data(as_text=True)
