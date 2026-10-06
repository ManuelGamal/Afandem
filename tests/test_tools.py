import json

from moderator.agent.tools import TOOL_SCHEMAS, ToolContext, run_tool
from moderator.clock import Clock
from moderator.events import EventBus
from moderator.store.catalog import Catalog
from moderator.store.orders import OrderBook

ORDER_ARGS = {"customer_name": "منى", "phone": "01012345678",
              "address": "12 شارع مكرم عبيد الدور 3", "area": "مدينة نصر",
              "items": [{"product_id": "T01", "size": "M", "color": "أسود", "qty": "2"}]}


def ctx():
    cat = Catalog.load()
    clock = Clock()
    return ToolContext(cat, OrderBook(cat), EventBus(clock), clock, "c1")


def test_schemas_cover_all_tools():
    names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert names == {"search_products", "get_product", "recommend_size", "quote_delivery",
                     "create_order", "update_order", "confirm_order", "cancel_order",
                     "schedule_delivery", "flag_risk", "handoff_to_human"}


def test_bad_json_and_unknown_tool_do_not_raise():
    c = ctx()
    assert run_tool("search_products", "{not json", c)["error"] == "bad_arguments"
    assert run_tool("teleport", {}, c)["error"] == "unknown_tool"


def test_search_and_get_product():
    c = ctx()
    out = run_tool("search_products", json.dumps({"query": "هودي"}), c)
    assert out["ok"] and out["products"][0]["id"] == "T06"
    out = run_tool("get_product", {"product_id": "t02"}, c)
    assert out["ok"] and "XL" in out["product"]["sizes_out_of_stock"]


def test_recommend_size_accepts_arabic_digits_and_meters():
    c = ctx()
    assert run_tool("recommend_size", {"product_id": "T01", "height_cm": "١٧٠",
                                       "weight_kg": "٦٥"}, c)["size"] == "M"
    assert run_tool("recommend_size", {"product_id": "T01", "height_cm": "1.70",
                                       "weight_kg": 65}, c)["size"] == "M"
    assert run_tool("recommend_size", {"product_id": "T01"}, c)["error"] == "bad_arguments"


def test_quote_delivery():
    c = ctx()
    assert run_tool("quote_delivery", {"area": "المهندسين"}, c)["fee"] == 60
    out = run_tool("quote_delivery", {"area": "الغردقة"}, c)
    assert not out["ok"] and out["error"] == "area_not_served"


def test_create_order_out_of_stock_is_structured():
    c = ctx()
    args = {**ORDER_ARGS, "items": [{"product_id": "T02", "size": "XL", "color": "أسود", "qty": 1}]}
    out = run_tool("create_order", args, c)
    assert out["error"] == "out_of_stock" and "XL" not in out["available"]


def test_confirm_requires_summary_then_unconditional_yes():
    c = ctx()
    created = run_tool("create_order", ORDER_ARGS, c)
    assert created["ok"] and created["total"] == 760 and "760 جنيه" in created["summary_ar"]
    oid = created["order_id"]
    c.customer_message = "تمام"
    assert run_tool("confirm_order", {"order_id": oid}, c)["error"] == "summary_not_sent"
    c.last_agent_message = created["summary_ar"] + "\nأأكد الطلب؟"
    c.customer_message = "تمام بس خليه لارج"
    assert run_tool("confirm_order", {"order_id": oid}, c)["error"] == "no_explicit_yes"
    c.customer_message = "تمام"
    out = run_tool("confirm_order", {"order_id": oid}, c)
    assert out["ok"] and out["status"] == "confirmed"
    assert ("order_status", "confirmed") in [(e.kind, e.data.get("new")) for e in c.bus.events]


def test_confirm_with_arabic_digits_in_summary():
    c = ctx()
    created = run_tool("create_order", ORDER_ARGS, c)
    c.last_agent_message = "الإجمالي ٧٦٠ جنيه، أأكد؟"
    c.customer_message = "اه"
    assert run_tool("confirm_order", {"order_id": created["order_id"]}, c)["status"] == "confirmed"


def test_high_risk_goes_to_owner_review():
    c = ctx()
    args = {**ORDER_ARGS, "phone": "0123", "address": "جنب الجامع", "area": "فيصل"}
    created = run_tool("create_order", args, c)
    c.last_agent_message = created["summary_ar"]
    c.customer_message = "ماشي"
    out = run_tool("confirm_order", {"order_id": created["order_id"]}, c)
    assert out["ok"] and out["status"] == "needs_human"


def test_confirm_other_conversations_order_is_refused():
    c = ctx()
    created = run_tool("create_order", ORDER_ARGS, c)
    c.conversation_id = "someone-else"
    c.last_agent_message, c.customer_message = created["summary_ar"], "تمام"
    assert run_tool("confirm_order", {"order_id": created["order_id"]},
                    c)["error"] == "unknown_order"


def test_cancel_schedule_flag_and_handoff():
    c = ctx()
    oid = run_tool("create_order", ORDER_ARGS, c)["order_id"]
    assert run_tool("schedule_delivery", {"order_id": oid, "date": "2026-10-10"}, c)["ok"]
    assert run_tool("schedule_delivery", {"order_id": oid, "date": "بكره"}, c)["ok"]
    assert run_tool("schedule_delivery", {"order_id": oid, "date": "2027-01-01"},
                    c)["error"] == "date_out_of_window"
    assert run_tool("flag_risk", {"order_id": oid, "note": "hesitant"}, c)["ok"]
    assert run_tool("cancel_order", {"order_id": oid, "reason": "whatever"},
                    c)["error"] == "bad_arguments"
    assert run_tool("cancel_order", {"order_id": oid, "reason": "customer_declined"}, c)["ok"]
    out = run_tool("handoff_to_human", {"reason": "complaint"}, c)
    assert out["ok"] and c.handed_off
    assert any(e.kind == "handoff" for e in c.bus.events)


def test_get_product_lists_pairings_with_names_and_prices():
    out = run_tool("get_product", {"product_id": "T06"}, ctx())
    assert out["product"]["pairs_with"] == [{"id": "B05", "name": "جوجر قطن", "price": 560}]


def test_search_results_list_pairings():
    out = run_tool("search_products", {"query": "هودي"}, ctx())
    assert out["products"][0]["pairs_with"] == [{"id": "B05", "name": "جوجر قطن", "price": 560}]


def test_high_risk_message_forbids_saying_confirmed():
    c = ctx()
    args = {**ORDER_ARGS, "phone": "0123", "address": "جنب الجامع", "area": "فيصل"}
    created = run_tool("create_order", args, c)
    c.last_agent_message, c.customer_message = created["summary_ar"], "ماشي"
    out = run_tool("confirm_order", {"order_id": created["order_id"]}, c)
    assert "NOT confirmed" in out["message"] and "تم تأكيد" in out["message"]


def test_confirm_moves_stock_and_publishes_it():
    c = ctx()
    created = run_tool("create_order", ORDER_ARGS, c)
    c.last_agent_message, c.customer_message = created["summary_ar"], "تمام"
    run_tool("confirm_order", {"order_id": created["order_id"]}, c)
    assert c.catalog.get("T01").stock["M"] == 18
    stock = [e.data for e in c.bus.events if e.kind == "stock"]
    assert stock == [{"product_id": "T01", "size": "M", "delta": -2, "stock_after": 18,
                      "reason": "order_confirmed", "order_id": created["order_id"]}]


def test_confirm_reports_sold_out_sizes_to_the_agent():
    c = ctx()
    created = run_tool("create_order", ORDER_ARGS, c)
    c.catalog.set_stock("T01", "M", 0)
    c.last_agent_message, c.customer_message = created["summary_ar"], "تمام"
    out = run_tool("confirm_order", {"order_id": created["order_id"]}, c)
    assert out["error"] == "out_of_stock" and "M" not in out["available"]
