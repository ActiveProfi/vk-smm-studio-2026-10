"""Общее окружение тестов. Секреты задаём до импорта приложения."""
import os

os.environ["FLASK_SECRET_KEY"] = "test-secret-key-please-32b-long!!"
os.environ["APP_ENCRYPTION_KEY"] = "test-encryption-key-please-32b!!"
os.environ["WEBAPP_DEV_SKIP_AUTH"] = "0"
os.environ["WEBAPP_DEBUG"] = "0"
os.environ["TRUST_PROXY"] = "0"
os.environ["SESSION_COOKIE_SECURE"] = "0"
os.environ.pop("VK_USER_TOKEN", None)
os.environ.pop("VK_COMMUNITY_TOKEN", None)
os.environ.pop("VK_GROUP_ID", None)

import pytest

from webapp import create_app
from webapp.config import PRIVACY_POLICY_VERSION
from webapp.models import Draft, TeamMember, User, Workspace, db
from webapp.services.secrets_box import _fernet

_fernet.cache_clear()


@pytest.fixture
def app():
    application = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
            "DEV_SKIP_AUTH": False,
        }
    )
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


def make_user(app, username, password="password-123", *, plan="agency"):
    with app.app_context():
        user = User(username=username, plan_code=plan, plan_status="active")
        user.set_password(password)
        user.privacy_accepted_at = "2026-10-28 12:00"
        user.privacy_policy_version = PRIVACY_POLICY_VERSION
        db.session.add(user)
        db.session.commit()
        return user.id


def make_workspace(app, owner_id, name="Канал", token="vk-token-secret"):
    from webapp.services.secrets_box import seal

    with app.app_context():
        ws = Workspace(
            user_id=owner_id,
            name=name,
            theme="тест",
            vk_group_id="100",
            vk_token=seal(token),
            is_active=True,
        )
        db.session.add(ws)
        db.session.commit()
        return ws.id


def add_member(app, agency_id, member_id, role):
    with app.app_context():
        db.session.add(
            TeamMember(
                agency_user_id=agency_id,
                user_id=member_id,
                role=role,
                is_active=True,
            )
        )
        db.session.commit()


def login(client, username, password="password-123"):
    return client.post(
        "/auth/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
