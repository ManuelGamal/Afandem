"""One sandbox: a fresh shop, order book, event bus, clock and agent."""

from __future__ import annotations

import os
import threading
from pathlib import Path

from moderator.agent.loop import Agent, Conversation
from moderator.agent.risk import score_order
from moderator.agent.tools import iso
from moderator.clock import Clock
from moderator.events import EventBus, impact
from moderator.store.catalog import SEED_PATH, Catalog
from moderator.store.orders import Order, OrderBook, OrderError

CHECKOUT_PRESETS = [
    {"customer_name": "سارة محمود", "phone": "01223456789",
     "address": "22 شارع عباس العقاد الدور 5 شقة 12", "area": "مدينة نصر",
     "items": [{"product_id": "T09", "size": "M", "color": "وردي", "qty": 1},
               {"product_id": "B08", "size": "M", "color": "أسود", "qty": 1}]},
    {"customer_name": "نورهان علي", "phone": "01534567890", "address": "جنب الجامع الكبير",
     "area": "فيصل", "items": [{"product_id": "B03", "size": "30", "color": "أزرق فاتح", "qty": 1}]},
    {"customer_name": "أحمد سمير", "phone": "01145678901", "address": "8 شارع النصر الدور 2",
     "area": "المعادي", "items": [{"product_id": "O02", "size": "L", "color": "أسود", "qty": 1}]},
    {"customer_name": "م", "phone": "0100000", "address": "عند المحطة", "area": "الهرم",
     "items": [{"product_id": "O03", "size": "M", "color": "أسود", "qty": 2}]},
    {"customer_name": "يوسف خالد", "phone": "01067890123", "address": "3 شارع سموحة الدور 6",
     "area": "سموحة", "items": [{"product_id": "T06", "size": "XL", "color": "كحلي", "qty": 1}]},
]


def seed_path() -> Path:
    """The shop's seed: Hodoom by default, or a store imported with moderator.store.importer."""
    return Path(os.environ.get("MODERATOR_SEED") or SEED_PATH)


def preset_items(catalog: Catalog, items: list[dict], n: int) -> list[dict]:
    """A preset's items, or in-stock items from the shop's own catalog when it is not Hodoom's."""
    if all(catalog.get(i["product_id"]) is not None for i in items):
        return items
    stocked = [p for p in catalog.products.values() if p.available_sizes()]
    if not stocked:
        return items  # nothing to sell; create() reports it
    out = []
    for k, item in enumerate(items):
        p = stocked[(n + k) % len(stocked)]
        out.append({"product_id": p.id, "size": p.available_sizes()[0], "color": p.colors[0],
                    "qty": 1})
    return out


_STATUS_WORDS = {"pending_confirmation": "awaiting confirmation", "needs_human": "held for a person"}


class Session:
    def __init__(self, provider, clock: Clock | None = None):
        self.catalog = Catalog.load(seed_path())
        self.clock = clock or Clock()
        self.bus = EventBus(self.clock)
        self.book = OrderBook(self.catalog)
        self.agent = Agent(self.catalog, self.book, self.bus, self.clock, provider)
        self.conversations: dict[str, Conversation] = {}
        self.lock = threading.Lock()
        self.last_state: dict | None = None  # served while a reply is being written
        self.message_count = 0
        self._checkouts = 0

    def conversation(self, conv_id: str) -> Conversation:
        if conv_id not in self.conversations:
            self.conversations[conv_id] = Conversation(conv_id)
        return self.conversations[conv_id]

    def chat(self, conv_id: str, text: str) -> list[str]:
        return self.agent.reply(self.conversation(conv_id), text)

    def checkout(self, preset: int | None = None) -> tuple[str, int, list[str]]:
        n = self._checkouts if preset is None else preset
        data = CHECKOUT_PRESETS[n % len(CHECKOUT_PRESETS)]
        return self.checkout_order({**data, "items": preset_items(self.catalog, data["items"], n)})

    def checkout_order(self, data: dict) -> tuple[str, int, list[str]]:
        self._checkouts += 1
        conv_id = f"checkout-{self._checkouts}"
        order = self.book.create(conv_id, **data, source="checkout", now=self.clock.now())
        order, old = self.book.set_status(order.id, "pending_confirmation")
        self.bus.publish("order_status", conv_id, order_id=order.id, old=old, new=order.status,
                         reason=None, total=order.total, source=order.source)
        replies = self.agent.start_confirmation(self.conversation(conv_id), order.id)
        return conv_id, order.id, replies

    def advance(self, hours: float) -> dict[str, list[str]]:
        self.clock.advance(hours)
        sent = {}
        for conv in list(self.conversations.values()):
            out = self.agent.remind(conv)
            if out:
                sent[conv.id] = out
        return sent

    def ship(self, order_id: int) -> Order:
        order = self.book.get(order_id)
        if order.status != "confirmed":
            raise OrderError("bad_transition", "only confirmed orders can be shipped")
        order, old = self.book.set_status(order_id, "shipped")
        self.bus.publish("order_status", order.conversation_id, order_id=order.id, old=old,
                         new="shipped", reason=None, total=order.total, source=order.source)
        return order

    def _with_notes(self, conv: Conversation) -> list[dict]:
        """The visible chat, each agent message carrying the database reads and writes behind it."""
        messages = conv.visible()
        agent = [m for m in messages if m["role"] == "agent"]
        pending: list[dict] = []
        i = 0
        for e in self.bus.events:
            if e.conversation_id != conv.id:
                continue
            note = self._note(e)
            if note:
                pending.append(note)
            elif e.kind == "message_out":
                while i < len(agent) and agent[i]["text"] != e.data.get("text"):
                    i += 1
                if i < len(agent):
                    if pending:
                        agent[i]["notes"] = pending
                    pending, i = [], i + 1
        return messages

    def _note(self, e) -> dict | None:
        if e.kind == "tool_call":
            return e.data.get("db")
        if e.kind == "stock":
            p = self.catalog.get(e.data["product_id"])
            after, delta = e.data["stock_after"], e.data["delta"]
            why = e.data["reason"].replace("_", " ")
            return {"kind": "write", "text": f"stock {iso(p.name_ar) if p else e.data['product_id']} "
                                             f"{e.data['size']}: {after - delta} → {after} ({why})"}
        if e.kind == "order_status" and e.data.get("old") and e.data["old"] != e.data["new"]:
            old, new = (_STATUS_WORDS.get(x, x) for x in (e.data["old"], e.data["new"]))
            return {"kind": "write", "text": f"order #{e.data['order_id']}: {old} → {new}"}
        return None

    def state(self, failed_delivery_cost: float) -> dict:
        orders = self.book.all()
        return {
            "now": self.clock.now().isoformat(timespec="minutes"),
            "orders": [o.to_dict() | {"risk": score_order(self.book, o).to_dict()} for o in orders],
            "conversations": [{"id": c.id, "handed_off": c.handed_off,
                               "awaiting_reply": c.awaiting_reply, "messages": self._with_notes(c)}
                              for c in self.conversations.values()],
            "impact": impact(self.bus.events, orders, self.catalog, failed_delivery_cost),
            "events": [e.to_dict() for e in self.bus.events[-40:]],
        }
