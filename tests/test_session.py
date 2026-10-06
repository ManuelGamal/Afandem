import pytest

from moderator.session import CHECKOUT_PRESETS, Session
from moderator.store.orders import OrderError
from tests.fakes import ScriptedProvider, text_raw


def test_presets_are_valid_orders():
    s = Session(ScriptedProvider([text_raw("x")] * 5))
    for i in range(len(CHECKOUT_PRESETS)):
        s.checkout(i)
    assert [o.status for o in s.book.all()] == ["pending_confirmation"] * 5
    levels = [o["risk"]["level"] for o in s.state(120)["orders"]]
    assert levels[3] == "high"  # preset 3 is the high-risk one


def test_checkout_starts_confirmation_conversation():
    s = Session(ScriptedProvider([]))
    conv_id, order_id, replies = s.checkout(0)
    assert conv_id == "checkout-1" and order_id == 1 and replies[0].startswith("أهلاً")
    assert "1330 جنيه" in replies[0]
    assert s.conversations[conv_id].awaiting_reply
    assert ("order_status", "pending_confirmation") in [(e.kind, e.data.get("new"))
                                                         for e in s.bus.events]


def test_advance_sends_one_reminder_then_cancels():
    s = Session(ScriptedProvider([]))
    conv_id, order_id, _ = s.checkout(4)
    sent = s.advance(2)
    assert list(sent) == [conv_id] and "955 جنيه" in sent[conv_id][0]
    assert s.advance(2) == {}
    assert s.book.get(order_id).cancel_reason == "unreachable"
    assert s.state(120)["impact"]["refusals_prevented"] == 1


def test_ship_requires_confirmed():
    s = Session(ScriptedProvider([text_raw("x")]))
    _, order_id, _ = s.checkout(0)
    with pytest.raises(OrderError):
        s.ship(order_id)


def test_state_shape():
    s = Session(ScriptedProvider([text_raw("أهلاً")]))
    s.chat("c1", "السلام عليكم")
    st = s.state(120)
    assert set(st) == {"now", "orders", "conversations", "impact", "events"}
    assert st["conversations"][0]["messages"] == [
        {"role": "customer", "text": "السلام عليكم"}, {"role": "agent", "text": "أهلاً"}]


def test_chat_shows_what_each_reply_read_from_and_wrote_to_the_database():
    from tests.fakes import tool_raw
    order = {"customer_name": "منى", "phone": "01012345678", "address": "12 شارع مكرم عبيد الدور 3",
             "area": "مدينة نصر", "items": [{"product_id": "T06", "size": "L", "color": "كحلي", "qty": 1}]}
    s = Session(ScriptedProvider([
        tool_raw(("get_product", {"product_id": "T06"})), text_raw("متوفر يا فندم"),
        tool_raw(("create_order", order)), text_raw("ده ملخص طلبك. أأكد الطلب؟"),
    ]))
    s.chat("c1", "عندكم قميص؟")
    s.chat("c1", "منى 01012345678 ...")
    msgs = s.state(120)["conversations"][0]["messages"]
    agent = [m for m in msgs if m["role"] == "agent"]
    assert [n["kind"] for n in agent[0]["notes"]] == ["read"]
    assert agent[1]["notes"][0]["kind"] == "write" and "order #1 saved" in agent[1]["notes"][0]["text"]
    assert all("notes" not in m for m in msgs if m["role"] == "customer")


def test_a_confirmed_order_shows_the_stock_change_in_the_chat():
    from tests.fakes import tool_raw
    s = Session(ScriptedProvider([tool_raw(("confirm_order", {"order_id": 1})), text_raw("تم تأكيد طلبك")]))
    conv_id, order_id, _ = s.checkout(4)  # preset 4: T06 XL كحلي
    before = s.catalog.get("T06").stock["XL"]
    s.chat(conv_id, "تمام")
    agent = [m for m in s.state(120)["conversations"][0]["messages"] if m["role"] == "agent"]
    texts = [n["text"] for n in agent[-1]["notes"]]
    assert any(f"XL: {before} → {before - 1}" in t for t in texts), texts
    assert any("order #1: awaiting confirmation → confirmed" in t for t in texts), texts
