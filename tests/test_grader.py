import json

from moderator.bench.cards import Card
from moderator.bench.grader import grade, summarize
from moderator.store.catalog import Catalog

CAT = Catalog.load()
BUY = Card(id="b-1", category="clear_buyer", script="arabic", flow="sales", persona="p", goal="g",
           opening="عايز تيشيرت", expect={"final_status": "confirmed", "product_id": "T01",
                                          "size": "M", "color": "أسود", "qty": 1,
                                          "zone_id": "cairo", "address_contains": ["14"]})
ORDER = {"id": 1, "conversation_id": "bench-b-1", "status": "confirmed", "source": "chat",
         "customer_name": "منى", "phone": "01011112222", "address": "14 شارع الطيران الدور 4",
         "area": "مدينة نصر", "zone_id": "cairo",
         "items": [{"product_id": "T01", "name_ar": "تيشيرت قطن سادة", "size": "M",
                    "color": "أسود", "qty": 1, "unit_price": 350}],
         "delivery_fee": 60, "subtotal": 350, "total": 410, "delivery_date": None,
         "cancel_reason": None, "risk_notes": [], "created_at": "2026-10-08T12:00"}


def result(agent_texts, customer_texts, orders, events=(), tool_payloads=({"total": 410, "price": 350,
                                                                           "fee": 60},)):
    transcript, raw = [], []
    for i, c in enumerate(customer_texts):
        transcript.append({"role": "customer", "text": c})
        raw.append({"role": "user", "content": c})
        if i < len(tool_payloads):
            raw.append({"role": "tool", "tool_call_id": "x",
                        "content": json.dumps(tool_payloads[i], ensure_ascii=False)})
        if i < len(agent_texts):
            transcript.append({"role": "agent", "text": agent_texts[i]})
            raw.append({"role": "assistant", "content": agent_texts[i]})
    return {"card_id": "b-1", "category": "clear_buyer", "script": "arabic", "flow": "sales",
            "turns": len(customer_texts), "ended_by": "done", "transcript": transcript,
            "raw_messages": raw, "orders": orders, "events": list(events)}


def test_correct_purchase_passes():
    r = result(["التيشيرت بـ 350 جنيه والشحن 60 جنيه", "الإجمالي 410 جنيه، أأكد؟", "تم"],
               ["عايز تيشيرت", "منى 01011112222 ...", "تمام"], [ORDER])
    g = grade(BUY, r, CAT)
    assert g.success and g.failures == [] and g.violations == [] and g.self_served


def test_wrong_size_fails_and_made_up_price_is_a_violation():
    wrong = {**ORDER, "items": [{**ORDER["items"][0], "size": "L"}]}
    r = result(["ده بـ 299 جنيه بس النهارده!", "تم"], ["عايز تيشيرت", "تمام"], [wrong])
    g = grade(BUY, r, CAT)
    assert not g.success and any("size" in f for f in g.failures)
    assert any("299" in v for v in g.violations)


def test_amounts_the_customer_wrote_are_allowed():
    r = result(["تمام، ميزانيتك 500 جنيه تكفي", "تم"], ["معايا 500 جنيه", "تمام"], [ORDER])
    assert grade(BUY, r, CAT).violations == []


def test_confirmed_without_yes_is_a_violation():
    r = result(["الإجمالي 410 جنيه"], ["عايز تيشيرت بس مش متأكد"], [ORDER])
    assert any("explicit yes" in v for v in grade(BUY, r, CAT).violations)


def test_none_expectation_and_handoff():
    card = Card(id="c-1", category="complaint", script="arabic", flow="sales", persona="p",
                goal="g", opening="عايز فلوسي", expect={"final_status": "none", "handoff": True})
    r = result(["هحولك لحد من الفريق"], ["عايز فلوسي"], [],
               events=[{"seq": 1, "ts": "", "kind": "handoff", "conversation_id": "x",
                        "data": {"reason": "complaint"}}])
    g = grade(card, r, CAT)
    assert g.success and not g.self_served


def test_summarize():
    good = grade(BUY, result(["الإجمالي 410 جنيه، أأكد؟"], ["تمام"], [ORDER]), CAT)
    bad = grade(BUY, result(["ده بـ 299 جنيه"], ["تمام"], []), CAT)
    s = summarize([good, bad])
    assert s["cards"] == 2 and s["success_rate"] == 0.5 and s["violations"] == 1
    assert s["by_category"]["clear_buyer"] == 0.5 and s["by_script"]["arabic"] == 0.5


def test_any_final_status_is_not_checked():
    card = Card(id="o-1", category="off_topic", script="arabic", flow="sales", persona="p",
                goal="g", opening="essay?", expect={"final_status": "any"})
    r = result(["الإجمالي 410 جنيه، أأكد؟"], ["تمام"], [ORDER])
    assert grade(card, r, CAT).success


def test_reply_time_counts_only_replies_that_called_the_live_model():
    """A reply served from the response cache takes ~0 s; timing it would flatter the agent."""
    def call(provider):
        return {"kind": "llm_call", "data": {"provider": provider, "tokens_in": 1, "tokens_out": 1}}

    def out(s):
        return {"kind": "message_out", "data": {"latency_s": s}}

    r = result(["التيشيرت بـ 350 جنيه والشحن 60 جنيه"], ["عايز تيشيرت"], [ORDER],
               events=[call("cache"), out(0.0), call("cache"), call("gemini"), out(2.5)])
    assert grade(BUY, r, CAT).median_reply_s == 2.5
    cached = result(["التيشيرت بـ 350 جنيه والشحن 60 جنيه"], ["عايز تيشيرت"], [ORDER],
                    events=[call("cache"), out(0.0)])
    assert grade(BUY, cached, CAT).median_reply_s is None
