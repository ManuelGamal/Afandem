from fastapi.testclient import TestClient

from moderator.server import create_app
from tests.fakes import ScriptedProvider


def test_page_and_assets_are_served():
    c = TestClient(create_app(provider_factory=lambda: ScriptedProvider([]), mode="live"))
    html = c.get("/").text
    assert 'dir="rtl"' in html and "/static/app.js" in html and "/static/style.css" in html
    for asset in ("/static/app.js", "/static/style.css"):
        assert c.get(asset).status_code == 200
    js = c.get("/static/app.js").text
    for endpoint in ("/api/state", "/api/chat", "/api/checkout", "/api/advance", "/api/reset",
                     "/api/events", "/api/info"):
        assert endpoint in js


def test_no_key_notice_is_arabic_with_english_detail():
    c = TestClient(create_app(provider_factory=lambda: ScriptedProvider([]), mode="live"))
    assert 'id="notice" class="notice" dir="auto"' in c.get("/").text
    js = c.get("/static/app.js").text
    assert "مفيش مفتاح للموديل" in js


def test_roi_calculator_panel_is_on_the_page():
    c = TestClient(create_app(provider_factory=lambda: ScriptedProvider([]), mode="live"))
    html = c.get("/").text
    for field in ('id="roi-orders"', 'id="roi-dms"', 'id="roi-salary"', 'id="roi-refusal"',
                  'id="roi-aov"', 'id="roi-out"'):
        assert field in html, field
    assert "/api/roi" in c.get("/static/app.js").text
