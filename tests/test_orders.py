from datetime import date, datetime

import pytest

from moderator.store.catalog import Catalog
from moderator.store.orders import OrderBook, OrderError, summary_ar

NOW = datetime(2026, 10, 8, 12, 0)
ITEM = {"product_id": "T01", "size": "M", "color": "أسود", "qty": 2}


def book():
    cat = Catalog.load()
    return cat, OrderBook(cat)


def make(b, conv="c1", **kw):
    args = dict(conversation_id=conv, customer_name="منى", phone="01012345678",
                address="12 شارع مكرم عبيد، الدور 3", area="مدينة نصر", items=[ITEM], now=NOW)
    args.update(kw)
    return b.create(**args)


def test_create_computes_totals_and_zone():
    _, b = book()
    o = make(b)
    assert (o.status, o.zone_id, o.subtotal, o.delivery_fee, o.total) == ("draft", "cairo", 700, 60, 760)
    assert o.items[0]["name_ar"] == "تيشيرت قطن سادة"


def test_create_is_idempotent_per_conversation_while_draft():
    _, b = book()
    first = make(b)
    second = make(b, items=[{**ITEM, "qty": 1}])
    assert second.id == first.id and second.total == 410
    assert len(b.all()) == 1


def test_create_rejects_bad_input():
    _, b = book()
    with pytest.raises(OrderError) as e:
        make(b, items=[{**ITEM, "product_id": "T02", "size": "XL"}])
    assert e.value.code == "out_of_stock" and "XL" not in e.value.details["available"]
    with pytest.raises(OrderError) as e:
        make(b, conv="c2", area="الغردقة")
    assert e.value.code == "area_not_served"
    with pytest.raises(OrderError) as e:
        make(b, conv="c3", items=[{**ITEM, "color": "بنفسجي"}])
    assert e.value.code == "unknown_color"
    with pytest.raises(OrderError) as e:
        make(b, conv="c4", items=[{**ITEM, "qty": 9}])
    assert e.value.code == "bad_quantity"


def test_status_transitions_enforced():
    _, b = book()
    o = make(b)
    o, old = b.set_status(o.id, "confirmed")
    assert (old, o.status) == ("draft", "confirmed")
    b.set_status(o.id, "shipped")
    with pytest.raises(OrderError) as e:
        b.set_status(o.id, "cancelled")
    assert e.value.code == "bad_transition"


def test_update_recomputes_and_locks_after_confirm():
    _, b = book()
    o = make(b)
    o = b.update(o.id, {"items": [{**ITEM, "size": "L", "qty": 1}], "area": "سموحة"})
    assert (o.total, o.zone_id) == (415, "alex")
    b.set_status(o.id, "confirmed")
    with pytest.raises(OrderError) as e:
        b.update(o.id, {"address": "x"})
    assert e.value.code == "order_locked"


def test_schedule_window():
    _, b = book()
    o = make(b)
    today = date(2026, 10, 8)
    assert b.schedule(o.id, date(2026, 10, 10), today).delivery_date == "2026-10-10"
    with pytest.raises(OrderError) as e:
        b.schedule(o.id, date(2026, 10, 8), today)
    assert e.value.code == "date_out_of_window"


def test_summary_contains_total_and_lines():
    cat, b = book()
    o = make(b)
    text = summary_ar(o, cat.find_zone("مدينة نصر"))
    assert "760 جنيه" in text and "تيشيرت قطن سادة" in text and "مدينة نصر" in text


def test_by_phone_and_open_for():
    _, b = book()
    o = make(b, phone="+20 101 234 5678")
    assert [x.id for x in b.by_phone("01012345678")] == [o.id]
    assert b.open_for("c1").id == o.id
    b.set_status(o.id, "cancelled", "customer_declined")
    assert b.open_for("c1") is None


def test_summary_does_not_repeat_an_area_already_in_the_address():
    cat, b = book()
    o = make(b, address="14 شارع الطيران الدور 4، مدينة نصر")
    text = summary_ar(o, cat.find_zone("مدينة نصر"))
    assert text.count("مدينة نصر") == 1
