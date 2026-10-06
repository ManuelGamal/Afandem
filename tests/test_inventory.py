from datetime import datetime

import pytest

from moderator.store.catalog import Catalog
from moderator.store.orders import OrderBook, OrderError

NOW = datetime(2026, 10, 8, 12, 0)
TEE_M = {"product_id": "T01", "size": "M", "color": "أسود", "qty": 2}


def order(book, conv="c1", items=None):
    return book.create(conv, "منى", "01012345678", "12 شارع مكرم عبيد الدور 3", "مدينة نصر",
                       items or [TEE_M], now=NOW)


def test_catalog_lives_in_sql_tables():
    cat = Catalog.load()
    tables = {r[0] for r in cat.db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"products", "inventory", "delivery_zones", "size_charts", "orders",
            "stock_movements"} <= tables
    assert cat.db.conn.execute("SELECT stock FROM inventory WHERE product_id='T01' AND size='M'").fetchone()[0] == 20


def test_confirming_reserves_stock_and_cancelling_restores_it():
    cat = Catalog.load()
    book = OrderBook(cat)
    o = order(book)
    book.set_status(o.id, "confirmed")
    assert cat.get("T01").stock["M"] == 18
    book.set_status(o.id, "cancelled", "customer_declined")
    assert cat.get("T01").stock["M"] == 20
    reasons = [r["reason"] for r in cat.stock_movements()]
    assert reasons == ["order_cancelled", "order_confirmed"]  # newest first


def test_cancelling_an_unconfirmed_order_does_not_touch_stock():
    cat = Catalog.load()
    book = OrderBook(cat)
    o = order(book)
    book.set_status(o.id, "cancelled", "customer_declined")
    assert cat.get("T01").stock["M"] == 20 and cat.stock_movements() == []


def test_confirm_fails_cleanly_when_the_last_units_are_gone():
    cat = Catalog.load()
    book = OrderBook(cat)
    o = order(book)
    cat.set_stock("T01", "M", 1)
    with pytest.raises(OrderError) as e:
        book.set_status(o.id, "confirmed")
    assert e.value.code == "out_of_stock"
    assert (e.value.details["in_stock"], e.value.details["requested"]) == (1, 2)
    assert book.get(o.id).status == "draft" and cat.get("T01").stock["M"] == 1


def test_owner_stock_edit_is_recorded_and_seen_immediately():
    cat = Catalog.load()
    row = cat.set_stock("T06", "L", 0)
    assert row == {"product_id": "T06", "size": "L", "stock": 0, "previous": 12}
    assert "L" not in cat.get("T06").available_sizes()
    assert cat.recommend_size("T06", 177, 77)["in_stock"] is False
    m = cat.stock_movements()[0]
    assert (m["product_id"], m["size"], m["delta"], m["reason"]) == ("T06", "L", -12, "owner_update")


def test_set_stock_rejects_unknown_sizes_and_negatives():
    cat = Catalog.load()
    with pytest.raises(KeyError):
        cat.set_stock("T06", "XS", 3)
    with pytest.raises(ValueError):
        cat.set_stock("T06", "L", -1)


def test_each_load_is_an_isolated_shop():
    a, b = Catalog.load(), Catalog.load()
    a.set_stock("T01", "M", 0)
    assert b.get("T01").stock["M"] == 20


def test_inventory_listing_flags_low_stock():
    cat = Catalog.load()
    rows = {(r["product_id"], r["size"]): r for r in cat.inventory()}
    assert rows[("T02", "XL")]["stock"] == 0 and rows[("T02", "XL")]["low"] is True
    assert rows[("T01", "M")]["low"] is False
    assert rows[("T01", "M")]["name"] == "تيشيرت قطن سادة"
