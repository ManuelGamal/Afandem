import pytest

from moderator.bench.cards import Card
from moderator.bench.runner import RunAborted, run_card
from moderator.bench.simulator import CustomerSim
from moderator.providers.client import ProviderError
from tests.fakes import ScriptedProvider, text_raw, tool_raw

SALES = Card(id="t-1", category="price_shopper", script="arabic", flow="sales",
             persona="p", goal="g", opening="بكام الهودي؟",
             expect={"final_status": "none", "handoff": False})
NO_REPLY = Card(id="t-2", category="no_reply", script="arabic", flow="checkout", persona="p",
                goal="g", no_reply=True,
                checkout={"customer_name": "منى", "phone": "01011112222",
                          "address": "14 شارع الطيران الدور 4", "area": "مدينة نصر",
                          "items": [{"product_id": "T01", "size": "S", "color": "كحلي", "qty": 1}]},
                expect={"final_status": "cancelled", "cancel_reason": "unreachable"})


def test_sim_flips_roles_and_detects_done():
    sim_provider = ScriptedProvider([text_raw("غالي أوي، شكراً"), text_raw("[DONE]")])
    sim = CustomerSim(sim_provider, SALES)
    transcript = [{"role": "customer", "text": "بكام الهودي؟"}, {"role": "agent", "text": "890 جنيه"}]
    assert sim.next_message(transcript) == "غالي أوي، شكراً"
    sent = sim_provider.requests[0]
    assert sent[0]["role"] == "system" and "Egyptian Arabic" in sent[0]["content"]
    assert [m["role"] for m in sent[1:]] == ["user", "assistant", "user"]
    assert sim.next_message(transcript) is None


def test_run_sales_card_until_done():
    agent = ScriptedProvider([tool_raw(("search_products", {"query": "هودي"})),
                              text_raw("الهودي بـ 890 جنيه"), text_raw("ولا يهمك، نورتنا")])
    sim = ScriptedProvider([text_raw("غالي، شكراً"), text_raw("[DONE]")])
    out = run_card(SALES, agent, sim)
    assert out["ended_by"] == "done" and out["turns"] == 2
    assert any(m["role"] == "tool" for m in out["raw_messages"])
    assert out["transcript"][0] == {"role": "customer", "text": "بكام الهودي؟"}


def test_run_no_reply_card_makes_no_sim_calls():
    agent = ScriptedProvider([text_raw("أهلاً منى، الإجمالي 410 جنيه. أأكد؟"),
                              text_raw("فكرتك بالطلب، 410 جنيه")])
    sim = ScriptedProvider([])
    out = run_card(NO_REPLY, agent, sim)
    assert out["ended_by"] == "no_reply" and sim.requests == []
    assert out["orders"][0]["cancel_reason"] == "unreachable"


def test_provider_failure_aborts_instead_of_saving_a_fake_result():
    with pytest.raises(RunAborted):
        run_card(SALES, ScriptedProvider([ProviderError("quota")]), ScriptedProvider([]))
    agent = ScriptedProvider([text_raw("890 جنيه")])
    with pytest.raises(RunAborted):
        run_card(SALES, agent, ScriptedProvider([ProviderError("quota")]))
