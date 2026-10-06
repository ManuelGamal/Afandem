import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from moderator.providers.client import ProviderError
from moderator.server import create_app
from tests.fakes import ScriptedProvider, text_raw


def client_with(responses):
    provider = ScriptedProvider(responses)
    return TestClient(create_app(provider_factory=lambda: provider, mode="live")), provider


def test_index_and_info():
    c, _ = client_with([])
    assert c.get("/").status_code == 200
    info = c.get("/api/info").json()
    assert info["mode"] == "live" and len(info["demo_scripts"]) == 7


def test_chat_and_state():
    c, _ = client_with([text_raw("أهلاً بيك")])
    r = c.post("/api/chat", json={"conversation_id": "c1", "text": "السلام عليكم"})
    assert r.json() == {"replies": ["أهلاً بيك"]}
    st = c.get("/api/state").json()
    assert st["impact"]["messages_handled"] == 1 and st["messages_left"] == 59


def test_rejects_empty_long_and_bad_ids():
    c, _ = client_with([])
    assert c.post("/api/chat", json={"conversation_id": "c1", "text": "   "}).status_code == 422
    assert c.post("/api/chat", json={"conversation_id": "c1", "text": "x" * 1001}).status_code == 422
    assert c.post("/api/chat", json={"conversation_id": "../x", "text": "hi"}).status_code == 422


def test_message_cap(monkeypatch):
    monkeypatch.setenv("MODERATOR_MAX_MESSAGES", "2")
    provider = ScriptedProvider([text_raw("a"), text_raw("b")])
    c = TestClient(create_app(provider_factory=lambda: provider, mode="live"))
    for _ in range(2):
        assert c.post("/api/chat", json={"conversation_id": "c1", "text": "hi"}).status_code == 200
    assert c.post("/api/chat", json={"conversation_id": "c1", "text": "hi"}).status_code == 429


def test_requests_in_one_session_are_serialized():
    active, peak = [0], [0]
    lock = threading.Lock()

    class Slow(ScriptedProvider):
        def complete(self, messages, tools):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.2)
            with lock:
                active[0] -= 1
            return {**text_raw("ok"), "_provider": "slow"}

    provider = Slow([])
    c = TestClient(create_app(provider_factory=lambda: provider, mode="live"))
    c.get("/api/state")  # sets the session cookie
    with ThreadPoolExecutor(2) as pool:
        codes = list(pool.map(lambda i: c.post(
            "/api/chat", json={"conversation_id": f"c{i}", "text": "hi"}).status_code, [1, 2]))
    assert codes == [200, 200] and peak[0] == 1


def test_checkout_advance_ship_and_reset():
    c, _ = client_with([text_raw("أأكد؟ 1330 جنيه")])
    out = c.post("/api/checkout", json={"preset": 0}).json()
    assert out["conversation_id"] == "checkout-1" and out["order_id"] == 1
    assert c.post("/api/orders/1/ship").status_code == 409
    assert c.post("/api/advance", json={"hours": 0}).status_code == 422
    c.post("/api/reset")
    assert c.get("/api/state").json()["orders"] == []


def test_no_key_falls_back_to_replay():
    def broken():
        raise ProviderError("No model API key found")
    c = TestClient(create_app(provider_factory=broken, mode="live"))
    info = c.get("/api/info").json()
    assert info["mode"] == "replay" and "API key" in info["notice"]


def test_inventory_read_and_owner_edit():
    c, _ = client_with([])
    inv = c.get("/api/inventory").json()
    row = next(r for r in inv["rows"] if r["product_id"] == "T06" and r["size"] == "L")
    assert row["stock"] == 12
    r = c.post("/api/inventory", json={"product_id": "T06", "size": "L", "stock": 0})
    assert r.status_code == 200 and r.json()["previous"] == 12
    inv = c.get("/api/inventory").json()
    assert inv["movements"][0]["reason"] == "owner_update"
    assert c.post("/api/inventory", json={"product_id": "T06", "size": "XS", "stock": 1}).status_code == 404
    assert c.post("/api/inventory", json={"product_id": "T06", "size": "L", "stock": -1}).status_code == 422
    events = c.get("/api/state").json()["events"]
    assert any(e["kind"] == "stock" for e in events)


def test_reset_does_not_refill_the_message_cap(monkeypatch):
    monkeypatch.setenv("MODERATOR_MAX_MESSAGES", "2")
    provider = ScriptedProvider([text_raw("a"), text_raw("b"), text_raw("c")])
    c = TestClient(create_app(provider_factory=lambda: provider, mode="live"))
    for _ in range(2):
        assert c.post("/api/chat", json={"conversation_id": "c1", "text": "hi"}).status_code == 200
    c.post("/api/reset")
    assert c.post("/api/chat", json={"conversation_id": "c1", "text": "hi"}).status_code == 429
    assert c.get("/api/state").json()["messages_left"] == 0


def test_recorded_demo_conversations_do_not_use_the_cap(monkeypatch):
    monkeypatch.setenv("MODERATOR_MAX_MESSAGES", "1")
    provider = ScriptedProvider([text_raw("a"), text_raw("b")])
    c = TestClient(create_app(provider_factory=lambda: provider, mode="live"))
    assert c.post("/api/chat", json={"conversation_id": "demo-sale", "text": "hi"}).status_code == 200
    assert c.post("/api/chat", json={"conversation_id": "c1", "text": "hi"}).status_code == 200


def test_spent_daily_budget_turns_live_chat_away_but_not_the_demo():
    from moderator.providers.client import CachedProvider, DailyBudget
    from tests.test_providers import Fake

    budget = DailyBudget(Fake("live", [text_raw("live")]), limit=0)
    provider = CachedProvider(budget, "unused-cache.jsonl")
    provider._data["k"] = text_raw("x")  # stands in for the recorded demo
    c = TestClient(create_app(provider_factory=lambda: provider, mode="live"))
    r = c.post("/api/chat", json={"conversation_id": "c1", "text": "hi"})
    assert r.status_code == 429 and "Play demo" in r.json()["detail"]
    assert c.post("/api/chat", json={"conversation_id": "demo-sale", "text": "hi"}).status_code == 200
