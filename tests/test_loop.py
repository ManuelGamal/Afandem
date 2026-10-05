from moderator.agent.loop import FALLBACK_TEXT, OVERFLOW_TEXT, Agent, Conversation
from moderator.clock import Clock
from moderator.events import EventBus
from moderator.providers.client import ProviderError
from moderator.store.catalog import Catalog
from moderator.store.orders import OrderBook
from tests.fakes import ScriptedProvider, text_raw, tool_raw

ORDER = {"customer_name": "منى", "phone": "01012345678", "address": "12 شارع مكرم عبيد الدور 3",
         "area": "مدينة نصر", "items": [{"product_id": "T01", "size": "M", "color": "أسود", "qty": 2}]}


def make(script):
    cat = Catalog.load()
    clock = Clock()
    bus = EventBus(clock)
    book = OrderBook(cat)
    provider = ScriptedProvider(script)
    return Agent(cat, book, bus, clock, provider), provider


def test_simple_reply_uses_tool_then_answers():
    agent, provider = make([tool_raw(("search_products", {"query": "هودي"})),
                            text_raw("الهودي التقيل بـ 890 جنيه يا فندم")])
    conv = Conversation("c1")
    assert agent.reply(conv, "عندكم هوديز؟") == ["الهودي التقيل بـ 890 جنيه يا فندم"]
    first = provider.requests[0]
    assert first[0]["role"] == "system" and "وصلة" in first[0]["content"]
    assert "2026-10-08" in first[0]["content"]
    assert any(m["role"] == "tool" for m in provider.requests[1])
    kinds = [e.kind for e in agent.bus.events]
    assert kinds.count("llm_call") == 2 and "message_out" in kinds


def test_chat_sale_confirms_only_after_summary_and_yes():
    agent, _ = make([
        tool_raw(("create_order", ORDER)),
        text_raw("طلب رقم 1:\n- 2× تيشيرت قطن سادة\nالإجمالي: 760 جنيه\nأأكد الطلب؟"),
        tool_raw(("confirm_order", {"order_id": 1})),
        text_raw("تم تأكيد طلبك 🎉"),
    ])
    conv = Conversation("c1")
    agent.reply(conv, "عايز 2 تيشيرت اسود M، منى 01012345678، 12 شارع مكرم عبيد الدور 3 مدينة نصر")
    assert agent.book.get(1).status == "draft"
    assert agent.reply(conv, "تمام") == ["تم تأكيد طلبك 🎉"]
    assert agent.book.get(1).status == "confirmed"


def test_provider_failure_hands_off_with_fixed_message():
    agent, _ = make([ProviderError("all providers failed")])
    conv = Conversation("c1")
    assert agent.reply(conv, "بكام؟") == [FALLBACK_TEXT]
    assert conv.handed_off
    assert any(e.kind == "handoff" for e in agent.bus.events)
    assert agent.reply(conv, "؟؟") == []


def test_too_many_tool_calls_hands_off():
    calls = [("search_products", {"query": "تيشيرت"})] * 7
    agent, _ = make([tool_raw(*calls)])
    conv = Conversation("c1")
    assert agent.reply(conv, "عايز اشوف كل حاجة") == [OVERFLOW_TEXT]
    assert conv.handed_off
    tool_msgs = [m for m in conv.messages if m["role"] == "tool"]
    assert len(tool_msgs) == 7  # every tool call is answered, so the history stays valid


def test_empty_model_reply_falls_back():
    agent, _ = make([text_raw("")])
    conv = Conversation("c1")
    assert agent.reply(conv, "hi") == [FALLBACK_TEXT]


def test_confirmation_reminder_then_unreachable():
    agent, provider = make([text_raw("أهلاً منى! ... الإجمالي: 760 جنيه. أأكد الطلب؟"),
                            text_raw("فكرتك بطلبك يا منى، الإجمالي 760 جنيه. نأكده؟")])
    order = agent.book.create("c1", **ORDER, source="checkout", now=agent.clock.now())
    agent.book.set_status(order.id, "pending_confirmation")
    conv = Conversation("c1")
    agent.start_confirmation(conv, order.id)
    assert conv.awaiting_reply and "760 جنيه" in provider.requests[0][-1]["content"]
    assert len(agent.remind(conv)) == 1 and conv.reminders_sent == 1
    assert agent.remind(conv) == []
    o = agent.book.get(order.id)
    assert (o.status, o.cancel_reason) == ("cancelled", "unreachable")
    assert len(provider.requests) == 2  # the final step makes no model call


def test_reply_clears_awaiting_and_visible_hides_internal_notes():
    agent, _ = make([text_raw("أأكد؟ 760 جنيه"), text_raw("تمام، اكدت")])
    order = agent.book.create("c1", **ORDER, source="checkout", now=agent.clock.now())
    agent.book.set_status(order.id, "pending_confirmation")
    conv = Conversation("c1")
    agent.start_confirmation(conv, order.id)
    agent.reply(conv, "مين معايا؟")
    assert not conv.awaiting_reply
    assert [m["role"] for m in conv.visible()] == ["agent", "customer", "agent"]
