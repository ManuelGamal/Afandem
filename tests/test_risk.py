from datetime import datetime

from moderator.agent.risk import address_complete, score_order
from moderator.store.catalog import Catalog
from moderator.store.orders import OrderBook

NOW = datetime(2026, 10, 8, 12, 0)
TEE = {"product_id": "T01", "size": "M", "color": "أسود", "qty": 1}
JACKET = {"product_id": "O03", "size": "M", "color": "أسود", "qty": 1}


def test_address_complete():
    assert address_complete("12 شارع مكرم عبيد الدور 3 شقة 5")
    assert address_complete("عمارة البنك جنب صيدلية العزبي شارع التسعين")
    assert not address_complete("جنب الجامع")
    assert not address_complete("مدينة نصر")


def test_repeat_customer_with_clean_order_is_low():
    b = OrderBook(Catalog.load())
    old = b.create("c0", "منى", "01012345678", "12 شارع مكرم عبيد الدور 3", "مدينة نصر",
                   [TEE], now=NOW)
    b.set_status(old.id, "confirmed")
    new = b.create("c1", "منى", "01012345678", "12 شارع مكرم عبيد الدور 3", "مدينة نصر",
                   [TEE], now=NOW)
    r = score_order(b, new)
    assert (r.score, r.level) == (0, "low")


def test_new_customer_bad_phone_vague_address_is_high():
    b = OrderBook(Catalog.load())
    o = b.create("c1", "x", "0123", "جنب الجامع", "فيصل", [JACKET], now=NOW)
    r = score_order(b, o)
    assert r.level == "high"
    assert any("Egyptian mobile" in s for s in r.reasons)
    assert any("address" in s for s in r.reasons)
    assert any("high value" in s for s in r.reasons)


def test_past_cancellations_and_agent_notes_add_points():
    b = OrderBook(Catalog.load())
    for i in range(2):
        o = b.create(f"c{i}", "علي", "01112345678", "5 شارع النصر الدور 2", "المعادي",
                     [TEE], now=NOW)
        b.set_status(o.id, "cancelled", "customer_declined")
    o = b.create("c9", "علي", "01112345678", "5 شارع النصر الدور 2", "المعادي", [TEE], now=NOW)
    b.add_risk_note(o.id, "hesitant about paying")
    r = score_order(b, b.get(o.id))
    assert r.score == 5 and r.level == "high"
