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


def test_confirmation_and_reminder_are_templates_without_model_calls():
    agent, provider = make([])
    order = agent.book.create("c1", **ORDER, source="checkout", now=agent.clock.now())
    agent.book.set_status(order.id, "pending_confirmation")
    conv = Conversation("c1")
    [opening] = agent.start_confirmation(conv, order.id)
    assert "منى" in opening and "760 جنيه" in opening and opening.rstrip().endswith("أأكد الطلب؟")
    assert conv.awaiting_reply
    [reminder] = agent.remind(conv)
    assert "760 جنيه" in reminder and conv.reminders_sent == 1
    assert agent.remind(conv) == []
    o = agent.book.get(order.id)
    assert (o.status, o.cancel_reason) == ("cancelled", "unreachable")
    assert provider.requests == []


def test_yes_after_template_confirms():
    agent, _ = make([tool_raw(("confirm_order", {"order_id": 1})), text_raw("تم تأكيد طلبك")])
    order = agent.book.create("c1", **ORDER, source="checkout", now=agent.clock.now())
    agent.book.set_status(order.id, "pending_confirmation")
    conv = Conversation("c1")
    agent.start_confirmation(conv, order.id)
    agent.reply(conv, "تمام")
    assert agent.book.get(order.id).status == "confirmed"


def test_reply_clears_awaiting_and_visible_hides_internal_notes():
    agent, _ = make([text_raw("تمام، اكدت")])
    order = agent.book.create("c1", **ORDER, source="checkout", now=agent.clock.now())
    agent.book.set_status(order.id, "pending_confirmation")
    conv = Conversation("c1")
    agent.start_confirmation(conv, order.id)
    agent.reply(conv, "مين معايا؟")
    assert not conv.awaiting_reply
    assert [m["role"] for m in conv.visible()] == ["agent", "customer", "agent"]


def test_latin_customer_message_asks_for_latin_reply():
    agent, provider = make([text_raw("el hoodie el ta2eel b 890 geneh")])
    agent.reply(Conversation("c1"), "elhoodie el khafeef bkam")
    assert "Latin letters" in provider.requests[0][0]["content"]


def test_arabic_customer_message_has_no_latin_hint():
    agent, provider = make([text_raw("الهودي بـ 890 جنيه")])
    agent.reply(Conversation("c1"), "الهودي بكام؟")
    assert "Latin letters" not in provider.requests[0][0]["content"]


def test_made_up_amount_is_corrected_before_sending():
    agent, provider = make([tool_raw(("quote_delivery", {"area": "المعادي"})),
                            text_raw("الشحن للمعادي 65 جنيه"),
                            text_raw("الشحن للمعادي 60 جنيه")])
    conv = Conversation("c1")
    assert agent.reply(conv, "الشحن للمعادي بكام؟") == ["الشحن للمعادي 60 جنيه"]
    assert "65" not in " ".join(m["text"] for m in conv.visible())
    assert provider.requests[2][-1]["content"].startswith("[حدث داخلي]")


def test_persistent_made_up_amount_hands_off():
    agent, _ = make([text_raw("ده بـ 299 جنيه")] * 3)
    conv = Conversation("c1")
    assert agent.reply(conv, "بكام؟") == [OVERFLOW_TEXT]
    assert conv.handed_off


def test_amount_the_customer_wrote_is_allowed():
    agent, _ = make([text_raw("تمام، الـ 500 جنيه تكفي")])
    assert agent.reply(Conversation("c1"), "معايا 500 جنيه بس") == ["تمام، الـ 500 جنيه تكفي"]


def test_tool_call_written_as_text_is_stripped_and_executed():
    agent, _ = make([text_raw('هحولك لزميل من الفريق حالاً\n\n[handoff_to_human(reason="refund")]')])
    conv = Conversation("c1")
    assert agent.reply(conv, "عايز فلوسي") == ["هحولك لزميل من الفريق حالاً"]
    assert conv.handed_off
    assert any(e.kind == "handoff" for e in agent.bus.events)


def test_prompt_forbids_internal_ids_and_self_computed_totals():
    agent, provider = make([text_raw("أهلاً")])
    agent.reply(Conversation("c1"), "اهلا")
    system = provider.requests[0][0]["content"]
    assert "internal product ids" in system and "pairs_with" in system
    assert "Never add up prices yourself" in system


def test_one_empty_model_reply_is_retried():
    agent, _ = make([text_raw(""), text_raw("أهلاً بيك")])
    conv = Conversation("c1")
    assert agent.reply(conv, "اهلا") == ["أهلاً بيك"]
    assert not conv.handed_off


def test_claiming_confirmed_while_the_order_is_not_is_corrected():
    agent, provider = make([tool_raw(("create_order", ORDER)), text_raw("تم تأكيد طلبك يا فندم"),
                            text_raw("ده ملخص طلبك والإجمالي 760 جنيه. أأكد الطلب؟")])
    conv = Conversation("c1")
    out = agent.reply(conv, "عايز 2 تيشيرت اسود M")
    assert out == ["ده ملخص طلبك والإجمالي 760 جنيه. أأكد الطلب؟"]
    assert provider.requests[2][-1]["content"].startswith("[حدث داخلي]")
    assert agent.book.get(1).status == "draft"


def test_claiming_cancelled_while_the_order_is_not_is_corrected():
    agent, provider = make([tool_raw(("create_order", ORDER)), text_raw("تم إلغاء الطلب"),
                            tool_raw(("cancel_order", {"order_id": 1, "reason": "customer_declined"})),
                            text_raw("تم إلغاء الطلب يا فندم")])
    conv = Conversation("c1")
    assert agent.reply(conv, "الغي الطلب") == ["تم إلغاء الطلب يا فندم"]
    assert agent.book.get(1).status == "cancelled"


def test_promised_handoff_is_carried_out():
    agent, _ = make([text_raw("آسفين جداً، هحولك لزميل من خدمة العملاء حالاً")])
    conv = Conversation("c1")
    agent.reply(conv, "الطلب وصل مقطوع")
    assert conv.handed_off and any(e.kind == "handoff" for e in agent.bus.events)


def test_prompt_requires_cancel_tool_before_replying():
    agent, provider = make([text_raw("أهلاً")])
    agent.reply(Conversation("c1"), "اهلا")
    assert "call cancel_order before you reply" in provider.requests[0][0]["content"]


def test_prompt_makes_the_single_suggestion_an_explicit_priced_question():
    agent, provider = make([text_raw("أهلاً")])
    agent.reply(Conversation("c1"), "اهلا")
    assert "as its own short question with its name and price" in provider.requests[0][0]["content"]
