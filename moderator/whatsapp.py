"""WhatsApp Cloud API bridge: Meta's webhook in, the same agent, replies out.

Env: WHATSAPP_TOKEN, WHATSAPP_PHONE_ID, WHATSAPP_APP_SECRET, WHATSAPP_VERIFY_TOKEN.
From the phone: any text chats with the agent; "/checkout [n]" sends a website-order
confirmation to that number (for demos); "/reset" starts over.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import threading

import httpx

from moderator.session import CHECKOUT_PRESETS, Session
from moderator.text import norm_phone

log = logging.getLogger(__name__)
GRAPH_URL = "https://graph.facebook.com/v21.0/{phone_id}/messages"
ENV_KEYS = ("WHATSAPP_TOKEN", "WHATSAPP_PHONE_ID", "WHATSAPP_APP_SECRET", "WHATSAPP_VERIFY_TOKEN")


def whatsapp_configured() -> bool:
    return all(os.environ.get(k) for k in ENV_KEYS)


def verify_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    """Meta signs every webhook body with the app secret (X-Hub-Signature-256)."""
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[len("sha256="):])


def parse_messages(payload: dict) -> list[dict]:
    out = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            names = {c.get("wa_id"): c.get("profile", {}).get("name", "")
                     for c in value.get("contacts", [])}
            for m in value.get("messages", []):
                if m.get("type") == "text":
                    out.append({"id": m["id"], "from": m["from"], "text": m["text"]["body"],
                                "name": names.get(m["from"], "")})
    return out


class WhatsAppSender:
    def __init__(self, token: str, phone_id: str, client: httpx.Client | None = None):
        self.url = GRAPH_URL.format(phone_id=phone_id)
        self.headers = {"Authorization": f"Bearer {token}"}
        self.client = client or httpx.Client(timeout=20)

    def send_text(self, to: str, text: str) -> None:
        r = self.client.post(self.url, headers=self.headers, json={
            "messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}})
        r.raise_for_status()


class WhatsAppBridge:
    def __init__(self, session: Session, sender):
        self.session = session
        self.sender = sender
        self.active: dict[str, str] = {}  # phone -> conversation it is currently in
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def handle(self, payload: dict) -> None:
        for m in parse_messages(payload):
            with self._lock:
                if m["id"] in self._seen:
                    continue
                self._seen.add(m["id"])
            for reply in self._replies(m):
                try:
                    self.sender.send_text(m["from"], reply)
                except Exception:  # a failed send must not stop the webhook
                    log.exception("WhatsApp send failed")

    def _replies(self, m: dict) -> list[str]:
        text = m["text"].strip()
        with self.session.lock:
            if text.startswith("/checkout"):
                parts = text.split()
                preset = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
                data = dict(CHECKOUT_PRESETS[preset % len(CHECKOUT_PRESETS)])
                data["phone"] = norm_phone(m["from"]) or m["from"]
                if m["name"]:
                    data["customer_name"] = m["name"]
                conv_id, _, replies = self.session.checkout_order(data)
                self.active[m["from"]] = conv_id
                return replies
            if text == "/reset":
                self.active.pop(m["from"], None)
                return ["تمام، بدأنا من جديد 🌸"]
            conv_id = self.active.get(m["from"], f"wa-{m['from']}")
            return self.session.chat(conv_id, text)
