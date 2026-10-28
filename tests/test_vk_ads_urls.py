"""Кабинет и API VK Рекламы смотрят на ads.vk.ru, адрес можно сменить."""
from pathlib import Path

from webapp.services import vk_ads_client as ads


def test_default_urls_use_vk_ru(monkeypatch):
    monkeypatch.delenv("VK_ADS_BASE_URL", raising=False)
    monkeypatch.delenv("VK_ADS_OAUTH_URL", raising=False)
    assert ads.ads_base_url() == "https://ads.vk.ru/api/v2"
    assert ads.oauth_token_url() == "https://ads.vk.ru/api/v2/oauth2/token.json"
    assert ads.cabinet_url() == "https://ads.vk.ru/"
    assert "ads.vk.com" not in ads.ads_base_url()
    assert "ads.vk.com" not in ads.oauth_token_url()
    assert "ads.vk.com" not in ads.cabinet_url()


def test_base_url_and_oauth_are_configurable(monkeypatch):
    monkeypatch.setenv("VK_ADS_BASE_URL", "https://example.test/api/v2/")
    monkeypatch.delenv("VK_ADS_OAUTH_URL", raising=False)
    assert ads.ads_base_url() == "https://example.test/api/v2"
    assert ads.oauth_token_url() == "https://example.test/api/v2/oauth2/token.json"
    monkeypatch.setenv("VK_ADS_OAUTH_URL", "https://example.test/oauth")
    assert ads.oauth_token_url() == "https://example.test/oauth"


def test_templates_do_not_link_old_ads_host():
    root = Path(__file__).resolve().parents[1] / "webapp" / "templates"
    offenders = []
    for path in root.rglob("*.html"):
        if "ads.vk.com" in path.read_text(encoding="utf-8"):
            offenders.append(str(path))
    assert offenders == []
