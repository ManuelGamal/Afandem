"""In-process event bus. The dashboard streams it; impact counters are computed from it."""

from __future__ import annotations

import queue
import statistics
import threading
from dataclasses import asdict, dataclass

from moderator.clock import Clock
from moderator.store.catalog import Catalog
from moderator.store.orders import Order


@dataclass
class Event:
    seq: int
    ts: str
    kind: str
    conversation_id: str | None
    data: dict

    def to_dict(self) -> dict:
        return asdict(self)


class EventBus:
    def __init__(self, clock: Clock):
        self.clock = clock
        self.events: list[Event] = []
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()

    def publish(self, kind: str, conversation_id: str | None = None, **data) -> Event:
        with self._lock:
            event = Event(len(self.events) + 1, self.clock.now().isoformat(timespec="minutes"),
                          kind, conversation_id, data)
            self.events.append(event)
            subs = list(self._subs)
        for q in subs:
            q.put(event)
        return event

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)


def upsell_value(order: Order, catalog: Catalog) -> int:
    """Value of items that pair with the first item (the agent's single suggestion)."""
    if len(order.items) < 2:
        return 0
    first = catalog.get(order.items[0]["product_id"])
    pairs = set(first.pairs_with) if first else set()
    return sum(i["qty"] * i["unit_price"] for i in order.items[1:] if i["product_id"] in pairs)


def impact(events: list[Event], orders: list[Order], catalog: Catalog,
           failed_delivery_cost: float) -> dict:
    latencies = [e.data["latency_s"] for e in events
                 if e.kind == "message_out" and e.data.get("latency_s") is not None]
    llm = [e for e in events if e.kind == "llm_call"]
    prevented = [o for o in orders if o.source == "checkout" and o.status == "cancelled"]
    live = [o for o in orders if o.status in ("confirmed", "shipped")]
    return {
        "messages_handled": sum(1 for e in events if e.kind == "message_in"),
        "median_reply_s": round(statistics.median(latencies), 1) if latencies else None,
        "orders_confirmed": sum(1 for e in events
                                if e.kind == "order_status" and e.data.get("new") == "confirmed"),
        "refusals_prevented": len(prevented),
        "egp_saved": round(len(prevented) * failed_delivery_cost),
        "upsell_revenue": sum(upsell_value(o, catalog) for o in live),
        "handoffs": sum(1 for e in events if e.kind == "handoff"),
        "llm_calls": len(llm),
        "tokens_in": sum(e.data.get("tokens_in", 0) for e in llm),
        "tokens_out": sum(e.data.get("tokens_out", 0) for e in llm),
    }
