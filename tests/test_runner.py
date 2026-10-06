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


def test_sim_strips_model_thoughts():
    sim = CustomerSim(ScriptedProvider([text_raw("<thought>planning...\n- option A</thought>تمام، بكام الشحن؟")]),
                      SALES)
    assert sim.next_message([{"role": "customer", "text": "x"}, {"role": "agent", "text": "y"}]) \
        == "تمام، بكام الشحن؟"


def test_runner_uses_its_own_simulator_provider_config():
    from moderator.bench.runner import SIM_CONFIG
    from moderator.providers.config import load_specs
    assert [s.model for s in load_specs(SIM_CONFIG)][:2] == ["gemini-3.1-flash-lite",
                                                             "gemma-4-26b-a4b-it"]


def test_sim_is_nudged_once_when_it_quits_on_an_open_question():
    sim_provider = ScriptedProvider([text_raw("[DONE]"), text_raw("تمام")])
    sim = CustomerSim(sim_provider, SALES)
    asked = [{"role": "customer", "text": "x"}, {"role": "agent", "text": "الإجمالي 950 جنيه. أأكد الطلب؟ 😊"}]
    assert sim.next_message(asked) == "تمام"
    assert len(sim_provider.requests) == 2


def test_sim_may_end_when_the_shop_asked_nothing():
    sim_provider = ScriptedProvider([text_raw("[DONE]")])
    sim = CustomerSim(sim_provider, SALES)
    done = [{"role": "customer", "text": "x"}, {"role": "agent", "text": "تم تأكيد طلبك 🎉"}]
    assert sim.next_message(done) is None and len(sim_provider.requests) == 1


def test_run_with_retries_waits_and_retries_aborted_cards():
    from moderator.bench.runner import run_with_retries
    calls, slept = [], []

    def flaky(card, agent, sim):
        calls.append(1)
        if len(calls) < 3:
            raise RunAborted("busy")
        return {"card_id": card.id}

    assert run_with_retries(SALES, None, None, attempts=3, wait_s=60, sleep=slept.append,
                            run=flaky) == {"card_id": "t-1"}
    assert slept == [60, 60]
    with pytest.raises(RunAborted):
        run_with_retries(SALES, None, None, attempts=2, wait_s=1, sleep=lambda s: None,
                         run=lambda *a: (_ for _ in ()).throw(RunAborted("down")))


def test_human_sim_shows_the_card_and_reads_replies():
    from moderator.bench.simulator import HumanSim
    shown = []
    replies = iter(["تمام، أكده", "/done"])
    sim = HumanSim(SALES, input_fn=lambda prompt="": next(replies), output=shown.append)
    transcript = [{"role": "customer", "text": "بكام الهودي؟"}, {"role": "agent", "text": "890 جنيه"}]
    assert sim.next_message(transcript) == "تمام، أكده"
    assert sim.next_message(transcript) is None
    assert any("goal" in s.lower() for s in shown) and any("890 جنيه" in s for s in shown)


def test_run_card_accepts_a_given_simulator():
    class Scripted:
        def __init__(self):
            self.lines = iter(["غالي شوية، شكراً"])

        def next_message(self, transcript):
            return next(self.lines, None)

    agent = ScriptedProvider([text_raw("أهلاً بيك يا فندم"), text_raw("ولا يهمك")])
    out = run_card(SALES, agent, None, sim=Scripted())
    assert out["turns"] == 2 and out["ended_by"] == "done"


def test_sim_prompt_keeps_the_customer_on_its_goal():
    from moderator.bench.simulator import PROMPT
    assert "Never start buying" in PROMPT


def test_simulator_ends_on_done_in_any_case():
    """Some models write the end marker as [done] or [Done]; it must end the chat, not be sent."""
    from moderator.bench.cards import load_cards
    from pathlib import Path

    from moderator.bench.simulator import CustomerSim

    card = load_cards(Path("bench/cards-heldout"))[0]
    for marker in ("[done]", "[Done]", "شكراً [done]"):
        sim = CustomerSim(ScriptedProvider([text_raw(marker)]), card)
        assert sim.next_message([]) is None, marker
