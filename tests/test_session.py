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
