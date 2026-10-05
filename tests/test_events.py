from datetime import datetime

from moderator.clock import Clock
from moderator.events import EventBus, impact, upsell_value
from moderator.store.catalog import Catalog
from moderator.store.orders import OrderBook

NOW = datetime(2026, 10, 8, 12, 0)


def test_clock_advances():
    c = Clock()
    assert c.now() == datetime(2026, 10, 8, 12, 0)
    c.advance(2.5)
    assert c.now() == datetime(2026, 10, 8, 14, 30)


def test_bus_publish_and_subscribe():
    bus = EventBus(Clock())
    q = bus.subscribe()
    e = bus.publish("message_in", "c1", text="بكام؟")
    assert e.seq == 1 and q.get_nowait().kind == "message_in"
    bus.unsubscribe(q)
    bus.publish("message_in", "c1", text="x")
    assert q.empty()


def test_upsell_value_counts_paired_items_only():
    cat = Catalog.load()
    b = OrderBook(cat)
    o = b.create("c1", "منى", "01012345678", "12 شارع النصر الدور 3", "المعادي",
                 [{"product_id": "T01", "size": "M", "color": "أسود", "qty": 1},
                  {"product_id": "B05", "size": "M", "color": "أسود", "qty": 1},
                  {"product_id": "A02", "size": "ONE", "color": "بيج", "qty": 1}], now=NOW)
    assert upsell_value(o, cat) == 560  # B05 pairs with T01; A02 does not


def test_impact_counters():
    cat = Catalog.load()
    b = OrderBook(cat)
    bus = EventBus(Clock())
    item = [{"product_id": "T01", "size": "M", "color": "أسود", "qty": 1}]
    o1 = b.create("c1", "a", "01012345678", "12 شارع النصر الدور 3", "المعادي", item,
                  source="checkout", now=NOW)
    b.set_status(o1.id, "pending_confirmation")
    b.set_status(o1.id, "cancelled", "customer_declined")
    o2 = b.create("c2", "b", "01112345678", "12 شارع النصر الدور 3", "المعادي", item, now=NOW)
    b.set_status(o2.id, "confirmed")
    bus.publish("message_in", "c1", text="x")
    bus.publish("message_in", "c2", text="y")
    bus.publish("message_out", "c1", text="a", latency_s=2.0)
    bus.publish("message_out", "c2", text="b", latency_s=4.0)
    bus.publish("order_status", "c2", order_id=o2.id, old="draft", new="confirmed",
                reason=None, total=410, source="chat")
    bus.publish("llm_call", "c1", provider="p", tokens_in=1000, tokens_out=100, latency_s=1.0)
    out = impact(bus.events, b.all(), cat, failed_delivery_cost=120)
    assert out["messages_handled"] == 2
    assert out["median_reply_s"] == 3.0
    assert out["orders_confirmed"] == 1
    assert out["refusals_prevented"] == 1
    assert out["egp_saved"] == 120
    assert (out["llm_calls"], out["tokens_in"], out["tokens_out"]) == (1, 1000, 100)
