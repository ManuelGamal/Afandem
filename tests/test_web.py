from fastapi.testclient import TestClient

from moderator.server import create_app
from tests.fakes import ScriptedProvider


def test_page_and_assets_are_served():
    c = TestClient(create_app(provider_factory=lambda: ScriptedProvider([]), mode="live"))
    html = c.get("/").text
    assert 'lang="en" dir="ltr"' in html and "/static/app.js" in html and "/static/style.css" in html
    for asset in ("/static/app.js", "/static/style.css"):
        assert c.get(asset).status_code == 200
    js = c.get("/static/app.js").text
    for endpoint in ("/api/state", "/api/chat", "/api/checkout", "/api/advance", "/api/reset",
                     "/api/events", "/api/info"):
        assert endpoint in js


def test_no_key_notice_and_messages_handle_both_directions():
    c = TestClient(create_app(provider_factory=lambda: ScriptedProvider([]), mode="live"))
    assert 'id="notice" class="notice" dir="auto"' in c.get("/").text
    js = c.get("/static/app.js").text
    assert "No model API key" in js
    assert 'class="bubble" dir="auto"' in js and 'class="text" dir="auto"' in js


def test_roi_calculator_panel_is_on_the_page():
    c = TestClient(create_app(provider_factory=lambda: ScriptedProvider([]), mode="live"))
    html = c.get("/").text
    for field in ('id="roi-orders"', 'id="roi-dms"', 'id="roi-salary"', 'id="roi-refusal"',
                  'id="roi-aov"', 'id="roi-out"'):
        assert field in html, field
    assert "/api/roi" in c.get("/static/app.js").text


def test_page_supports_the_whatsapp_view():
    c = TestClient(create_app(provider_factory=lambda: ScriptedProvider([]), mode="live"))
    js = c.get("/static/app.js").text
    assert 'get("view")' in js and "WhatsApp" in js


def test_inventory_panel_is_on_the_page():
    c = TestClient(create_app(provider_factory=lambda: ScriptedProvider([]), mode="live"))
    assert 'data-panel="inventory"' in c.get("/").text
    js = c.get("/static/app.js").text
    assert "/api/inventory" in js and '"stock"' in js


def test_page_and_assets_are_revalidated_after_deploys():
    c = TestClient(create_app(provider_factory=lambda: ScriptedProvider([]), mode="live"))
    for path in ("/", "/static/app.js", "/static/style.css"):
        assert c.get(path).headers.get("cache-control") == "no-cache", path


def test_asset_urls_carry_a_content_version():
    import re
    c = TestClient(create_app(provider_factory=lambda: ScriptedProvider([]), mode="live"))
    html = c.get("/").text
    assert re.search(r'/static/app\.js\?v=[0-9a-f]{10}"', html)
    assert re.search(r'/static/style\.css\?v=[0-9a-f]{10}"', html)
