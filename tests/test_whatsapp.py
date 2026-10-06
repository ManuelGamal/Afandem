import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from moderator.server import create_app
from moderator.session import Session
from moderator.whatsapp import WhatsAppBridge, parse_messages, verify_signature
from tests.fakes import ScriptedProvider, text_raw, tool_raw

ME = "201012345678"


def payload(text, msg_id="wamid.1", sender=ME):
    return {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp",
        "contacts": [{"profile": {"name": "Manuel"}, "wa_id": sender}],
        "messages": [{"from": sender, "id": msg_id, "type": "text", "text": {"body": text}}]}}]}]}


class FakeSender:
    def __init__(self):
        self.sent = []

    def send_text(self, to, text):
        self.sent.append((to, text))


def sign(secret, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_verify_signature():
    body = b'{"a":1}'
    assert verify_signature("s3cret", body, sign("s3cret", body))
    assert not verify_signature("s3cret", body, sign("other", body))
    assert not verify_signature("s3cret", body, None)


def test_parse_messages_keeps_text_and_ignores_statuses():
    status = {"entry": [{"changes": [{"value": {"statuses": [{"id": "x", "status": "read"}]}}]}]}
    assert parse_messages(status) == []
    assert parse_messages(payload("بكام؟")) == [{"id": "wamid.1", "from": ME, "text": "بكام؟",
                                                 "name": "Manuel"}]


def test_bridge_replies_and_ignores_duplicates():
    sender = FakeSender()
    bridge = WhatsAppBridge(Session(ScriptedProvider([text_raw("أهلاً بيك يا فندم")])), sender)
    bridge.handle(payload("السلام عليكم"))
    bridge.handle(payload("السلام عليكم"))  # Meta retries the same message id
    assert sender.sent == [(ME, "أهلاً بيك يا فندم")]


def test_checkout_command_sends_a_confirmation_template_to_the_sender():
    sender = FakeSender()
    s = Session(ScriptedProvider([tool_raw(("confirm_order", {"order_id": 1})),
                                  text_raw("تم تأكيد طلبك")]))
    bridge = WhatsAppBridge(s, sender)
    bridge.handle(payload("/checkout 0", "wamid.1"))
    assert "أأكد الطلب؟" in sender.sent[0][1] and s.book.get(1).phone == "01012345678"
    bridge.handle(payload("تمام", "wamid.2"))
    assert s.book.get(1).status == "confirmed" and sender.sent[-1] == (ME, "تم تأكيد طلبك")


def wa_client(monkeypatch, provider):
    monkeypatch.setenv("WHATSAPP_TOKEN", "t")
    monkeypatch.setenv("WHATSAPP_PHONE_ID", "123")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "s3cret")
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "verify-me")
    monkeypatch.setenv("WHATSAPP_VIEW_KEY", "owner-key")
    sender = FakeSender()
    app = create_app(provider_factory=lambda: provider, mode="live", whatsapp_sender=sender)
    return TestClient(app), sender


def test_webhook_verification_handshake(monkeypatch):
    c, _ = wa_client(monkeypatch, ScriptedProvider([]))
    ok = c.get("/webhook/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me",
                                            "hub.challenge": "42"})
    assert ok.status_code == 200 and ok.text == "42"
    bad = c.get("/webhook/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "nope",
                                             "hub.challenge": "42"})
    assert bad.status_code == 403


def test_webhook_rejects_unsigned_and_handles_signed(monkeypatch):
    c, sender = wa_client(monkeypatch, ScriptedProvider([text_raw("أهلاً")]))
    body = json.dumps(payload("اهلا"), ensure_ascii=False).encode()
    assert c.post("/webhook/whatsapp", content=body).status_code == 403
    r = c.post("/webhook/whatsapp", content=body,
               headers={"X-Hub-Signature-256": sign("s3cret", body), "Content-Type": "application/json"})
    assert r.status_code == 200 and sender.sent == [(ME, "أهلاً")]
    state = c.get("/api/state", params={"view": "whatsapp", "key": "owner-key"}).json()
    assert state["conversations"][0]["id"] == f"wa-{ME}"


def test_webhook_disabled_without_credentials():
    c = TestClient(create_app(provider_factory=lambda: ScriptedProvider([]), mode="live"))
    assert c.get("/webhook/whatsapp").status_code == 404


def test_whatsapp_view_needs_the_owner_key(monkeypatch):
    """Real customers' numbers and addresses are never shown to a visitor without the key."""
    c, _ = wa_client(monkeypatch, ScriptedProvider([]))
    for params in ({"view": "whatsapp"}, {"view": "whatsapp", "key": "guess"}):
        assert c.get("/api/state", params=params).status_code == 403
        assert c.get("/api/inventory", params=params).status_code == 403
        assert c.get("/api/events", params=params).status_code == 403
        assert c.post("/api/inventory", params=params,
                      json={"product_id": "T01", "size": "M", "stock": 0}).status_code == 403
    assert c.get("/api/state", params={"view": "whatsapp", "key": "owner-key"}).status_code == 200


def test_whatsapp_view_is_off_without_a_view_key(monkeypatch):
    c, _ = wa_client(monkeypatch, ScriptedProvider([]))
    monkeypatch.delenv("WHATSAPP_VIEW_KEY")
    assert c.get("/api/state", params={"view": "whatsapp", "key": ""}).status_code == 403


def test_each_number_has_a_daily_message_limit():
    """One person spamming the line must not use up the day's model calls for everyone."""
    from datetime import date

    day = [date(2026, 10, 8)]
    sender = FakeSender()
    provider = ScriptedProvider([text_raw(f"رد {i}") for i in range(4)])
    bridge = WhatsAppBridge(Session(provider), sender, daily_limit=2, today=lambda: day[0])
    for i in range(5):
        bridge.handle(payload(f"رسالة {i}", f"wamid.{i}"))
    texts = [t for _, t in sender.sent]
    assert texts[:2] == ["رد 0", "رد 1"] and len(texts) == 3  # two answers, then one notice, then silence
    assert "النهاردة" in texts[2] and len(provider.requests) == 2
    other = "201099999999"  # another customer is not affected
    bridge.handle(payload("اهلا", "wamid.x", sender=other))
    assert sender.sent[-1] == (other, "رد 2")
    day[0] = date(2026, 10, 9)  # a new day, a new allowance
    bridge.handle(payload("اهلا تاني", "wamid.y"))
    assert sender.sent[-1] == (ME, "رد 3")


def test_an_overlong_whatsapp_message_is_answered_without_a_model_call():
    sender = FakeSender()
    provider = ScriptedProvider([])
    bridge = WhatsAppBridge(Session(provider), sender)
    bridge.handle(payload("ا" * 1001))
    assert len(provider.requests) == 0 and "أقصر" in sender.sent[0][1]


def test_remembered_message_ids_are_bounded():
    bridge = WhatsAppBridge(Session(ScriptedProvider([text_raw("x")] * 3)), FakeSender(), daily_limit=10**6)
    bridge.max_seen = 2
    for i in range(3):
        bridge.handle(payload("/reset", f"wamid.{i}"))
    assert len(bridge._seen) == 2
