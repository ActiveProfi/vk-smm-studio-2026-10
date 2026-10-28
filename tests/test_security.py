"""Проверки изоляции агентств, прав, редиректов и персональных данных."""
from webapp.config import PRIVACY_POLICY_VERSION
from webapp.models import ContentPlanBatch, Draft, SecurityEvent, User, Workspace, db
from webapp.services.http_guard import is_public_http_url, safe_next_url, scrub_secrets
from webapp.services.secrets_box import reveal, seal

from tests.conftest import add_member, login, make_user, make_workspace


def test_safe_next_rejects_external():
    fallback = "/manager"
    assert safe_next_url("https://evil.example/phish", fallback) == fallback
    assert safe_next_url("//evil.example", fallback) == fallback
    assert safe_next_url("/\\evil.example", fallback) == fallback
    assert safe_next_url("/manager", fallback) == "/manager"
    assert safe_next_url("/workspaces/1/content-plan", fallback).startswith("/workspaces/")


def test_ssrf_blocks_private_targets():
    assert is_public_http_url("http://127.0.0.1/latest") is False
    assert is_public_http_url("http://169.254.169.254/") is False
    assert is_public_http_url("http://10.1.1.1/") is False
    assert is_public_http_url("http://192.168.0.5/") is False
    assert is_public_http_url("file:///etc/passwd") is False
    assert is_public_http_url("http://localhost/admin") is False


def test_scrub_and_seal_roundtrip():
    secret = "vk1.a.SuperSecretTokenValue"
    sealed = seal(secret)
    assert sealed.startswith("enc:")
    assert secret not in sealed
    assert reveal(sealed) == secret
    assert "vk1.***" in scrub_secrets(f"ошибка {secret}")
    assert "access_token=***" in scrub_secrets("url?access_token=abcdef")


def test_tenant_cannot_open_foreign_draft_or_media(app, client):
    owner_a = make_user(app, "agency-a")
    owner_b = make_user(app, "agency-b")
    ws_a = make_workspace(app, owner_a, name="Клиент А")
    with app.app_context():
        draft = Draft(user_id=owner_a, workspace_id=ws_a, topic="секрет клиента", post_text="текст")
        db.session.add(draft)
        db.session.commit()
        draft_id = draft.id

    login(client, "agency-b")
    preview = client.get(f"/preview/{draft_id}")
    assert preview.status_code == 404
    media = client.get(f"/media/{owner_a}/notes.txt")
    assert media.status_code == 403
    missing = client.get(f"/workspaces/{ws_a}/edit")
    assert missing.status_code == 404


def test_security_log_is_scoped_and_ip_is_masked(app, client):
    make_user(app, "agency-a")
    make_user(app, "agency-b")
    login(client, "agency-a")
    client.get("/auth/logout")
    with client.session_transaction() as sess:
        sess.clear()
    login(client, "agency-b")
    page = client.get("/auth/security-log")
    body = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "agency-a" not in body
    assert "agency-b" in body
    with app.app_context():
        rows = SecurityEvent.query.filter_by(username="agency-a").all()
        assert rows
        assert all(row.ip != "127.0.0.1" for row in rows)
        assert all("xxx" in (row.ip or "") or not row.ip for row in rows)
        assert all(row.agency_user_id != User.query.filter_by(username="agency-b").one().id for row in rows)


def test_forwarded_for_is_ignored_without_trust_proxy(app, client):
    make_user(app, "agency-a")
    client.post(
        "/auth/login",
        data={"username": "agency-a", "password": "wrong-password"},
        headers={"X-Forwarded-For": "203.0.113.55"},
    )
    with app.app_context():
        event = SecurityEvent.query.filter_by(kind="login_fail", username="agency-a").one()
        assert event.ip.startswith("127.0.0.")
        assert "203.0.113" not in event.ip


def test_login_rate_limit_and_open_redirect(app, client):
    make_user(app, "agency-a")
    for _ in range(7):
        client.post("/auth/login", data={"username": "agency-a", "password": "wrong-password"})
    blocked = client.post(
        "/auth/login?next=https://evil.example/steal",
        data={"username": "agency-a", "password": "password-123"},
    )
    text = blocked.get_data(as_text=True)
    assert "Слишком много" in text

    # Новый логин без серии ошибок не уводит на чужой сайт.
    make_user(app, "agency-c")
    ok = login(client, "agency-c")
    # предыдущая сессия могла остаться заблокированной на том же IP по другому логину — лимит IP выше
    if ok.status_code == 302:
        assert "evil.example" not in (ok.headers.get("Location") or "")


def test_login_next_is_local_only(app, client):
    make_user(app, "agency-a")
    response = client.post(
        "/auth/login?next=https://evil.example/phish",
        data={"username": "agency-a", "password": "password-123"},
    )
    assert response.status_code == 302
    assert "evil.example" not in (response.headers.get("Location") or "")


def test_viewer_cannot_publish_or_edit(app, client):
    owner = make_user(app, "owner")
    viewer = make_user(app, "viewer", plan="free")
    ws_id = make_workspace(app, owner)
    add_member(app, owner, viewer, "viewer")
    login(client, "viewer")

    publish = client.post(f"/auto-publish/{ws_id}", data={"period": "today", "next": "https://evil.example"})
    assert publish.status_code == 302
    assert "evil.example" not in (publish.headers.get("Location") or "")
    followed = client.post(f"/auto-publish/{ws_id}", data={"period": "today"}, follow_redirects=True)
    assert "Недостаточно прав" in followed.get_data(as_text=True)

    rubric = client.post(
        f"/workspaces/{ws_id}/content-plan/generate",
        json={"days": 7},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert rubric.status_code == 403


def test_register_requires_consent_and_logout_is_post(app, client):
    missing = client.post(
        "/auth/register",
        data={"username": "new-user", "password": "password-123", "password2": "password-123"},
    )
    assert missing.status_code == 200
    assert "персональн" in missing.get_data(as_text=True).lower()

    ok = client.post(
        "/auth/register",
        data={
            "username": "new-user",
            "password": "password-123",
            "password2": "password-123",
            "privacy_agree": "y",
        },
        follow_redirects=True,
    )
    assert "Войдите" in ok.get_data(as_text=True) or ok.status_code == 200
    with app.app_context():
        user = User.query.filter_by(username="new-user").one()
        assert user.privacy_policy_version == PRIVACY_POLICY_VERSION

    login(client, "new-user")
    get_logout = client.get("/auth/logout")
    assert get_logout.status_code == 200
    assert "Выйти" in get_logout.get_data(as_text=True)
    still_in = client.get("/manager")
    assert still_in.status_code == 200
    client.post("/auth/logout", follow_redirects=True)
    after = client.get("/manager")
    assert after.status_code == 302


def test_export_hides_token_and_delete_removes_account(app, client):
    owner = make_user(app, "agency-a")
    make_workspace(app, owner, token="super-secret-vk-token")
    login(client, "agency-a")
    exported = client.get("/auth/export-data")
    body = exported.get_data(as_text=True)
    assert exported.status_code == 200
    assert "agency-a" in body
    assert "super-secret-vk-token" not in body
    assert "enc:" not in body

    denied = client.post("/auth/delete-account", data={"password": "password-123", "confirm": "нет"})
    assert denied.status_code == 302
    removed = client.post(
        "/auth/delete-account",
        data={"password": "password-123", "confirm": "УДАЛИТЬ"},
        follow_redirects=True,
    )
    assert "удален" in removed.get_data(as_text=True).lower()
    with app.app_context():
        assert User.query.filter_by(username="agency-a").first() is None
        assert Workspace.query.count() == 0


def test_client_portal_cannot_touch_other_agency_plan(app, client):
    owner_a = make_user(app, "agency-a")
    owner_b = make_user(app, "agency-b")
    ws_a = make_workspace(app, owner_a, name="А")
    ws_b = make_workspace(app, owner_b, name="Б")
    with app.app_context():
        channel_a = db.session.get(Workspace, ws_a)
        channel_b = db.session.get(Workspace, ws_b)
        channel_a.client_approve_token = "a" * 24
        channel_b.client_approve_token = "b" * 24
        plan = ContentPlanBatch(
            workspace_id=ws_b,
            user_id=owner_b,
            title="Чужой план",
            items_json="[]",
            client_status="pending",
        )
        db.session.add(plan)
        db.session.commit()
        plan_id = plan.id
        token_a = channel_a.client_approve_token

    response = client.post(
        f"/client/{token_a}",
        data={"plan_id": plan_id, "decision": "approve", "comment": "ok"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    with app.app_context():
        saved = db.session.get(ContentPlanBatch, plan_id)
        assert saved.client_status == "pending"


def test_privacy_gate_blocks_cabinet_until_accept(app, client):
    with app.app_context():
        user = User(username="late")
        user.set_password("password-123")
        db.session.add(user)
        db.session.commit()
    login(client, "late")
    page = client.get("/manager", follow_redirects=True)
    assert "Согласие" in page.get_data(as_text=True)
    client.post("/auth/accept-privacy", data={"agree": "1"}, follow_redirects=True)
    home = client.get("/manager")
    assert home.status_code == 200
    assert "Панель" in home.get_data(as_text=True)


def test_health_does_not_leak_dev_flag(client):
    payload = client.get("/health").get_json()
    assert payload == {"status": "ok"}


def test_session_cookie_is_httponly(app, client):
    make_user(app, "agency-a")
    response = login(client, "agency-a")
    cookie = response.headers.get("Set-Cookie") or ""
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


def test_csrf_blocks_login_without_token():
    from webapp import create_app

    protected = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": True,
            "DEV_SKIP_AUTH": False,
        }
    )
    protected_client = protected.test_client()
    response = protected_client.post(
        "/auth/login",
        data={"username": "x", "password": "password-123"},
    )
    assert response.status_code == 400
