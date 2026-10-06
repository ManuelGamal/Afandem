import json

import pytest

from moderator.bench.report import build_report, impact_model, load_assumptions

A = {k: {"low": v, "base": v, "high": v, "source": "t"} for k, v in {
    "cod_orders_per_day": 40, "chat_order_share": 0.5, "dms_per_day": 150,
    "average_order_egp": 700, "working_days_per_month": 26, "moderator_salary_egp_month": 7000,
    "moderator_hours_month": 208, "minutes_per_dm": 1.5, "minutes_per_confirmation_call": 3,
    "refusal_rate_without_confirmation": 0.25, "refusal_rate_with_confirmation": 0.125,
    "outbound_shipping_egp": 60, "return_shipping_egp": 60, "buying_intent_share_of_dms": 0.4,
    "conversion_uplift_from_fast_replies": 0.05, "llm_usd_per_mtok_in": 0.10,
    "llm_usd_per_mtok_out": 0.40, "usd_to_egp": 50}.items()}
BENCH = {"self_service_rate": 0.9, "median_turns": 5, "mean_tokens_in": 20000,
         "mean_tokens_out": 1000, "upsell_share": 0.1, "mean_upsell_egp": 500}


def test_impact_model_hand_computed():
    m = impact_model(A, BENCH, "base")
    assert m["dm_hours"] == pytest.approx(87.75)          # 150*1.5/60*0.9*26
    assert m["call_hours"] == pytest.approx(46.8)         # 40*3/60*0.9*26
    assert m["hours_saved_week"] == pytest.approx(134.55 / 4.33)
    assert m["moderator_cost_saved"] == pytest.approx(134.55 * 7000 / 208)
    assert m["refusals_prevented"] == pytest.approx(130)  # 40*26*(0.25-0.125)
    assert m["delivery_cost_saved"] == pytest.approx(15600)
    assert m["llm_cost_egp"] == pytest.approx(1820 * 0.0024 * 50)  # (150/5+40)*26 convs
    assert m["revenue_speed"] == pytest.approx(49140)     # 150*0.4*0.05*0.9*700*26
    assert m["revenue_upsell"] == pytest.approx(26000)    # 40*26*0.5*0.1*500
    assert m["net_cost_saved"] == pytest.approx(m["moderator_cost_saved"] + 15600 - 218.4)


def test_real_assumptions_file_is_complete():
    a = load_assumptions(__import__("pathlib").Path("bench/assumptions.yaml"))
    assert set(A) <= set(a)
    for name, row in a.items():
        assert row["source"], name
        for s in ("low", "base", "high"):
            assert isinstance(row[s], (int, float)), (name, s)


def test_build_report_end_to_end(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    order = {"id": 1, "conversation_id": "bench-price-1", "status": "draft", "source": "chat",
             "customer_name": "x", "phone": "01011112222", "address": "a", "area": "مدينة نصر",
             "zone_id": "cairo", "items": [], "delivery_fee": 60, "subtotal": 0, "total": 60,
             "delivery_date": None, "cancel_reason": None, "risk_notes": [], "created_at": ""}
    (results / "price-1.json").write_text(json.dumps({
        "card_id": "price-1", "category": "price_shopper", "script": "arabic", "flow": "sales",
        "turns": 2, "ended_by": "done",
        "transcript": [{"role": "customer", "text": "بكام؟"}, {"role": "agent", "text": "1650 جنيه"}],
        "raw_messages": [{"role": "user", "content": "بكام؟"},
                         {"role": "tool", "tool_call_id": "1", "content": "{\"price\": 1650}"},
                         {"role": "assistant", "content": "1650 جنيه"}],
        "orders": [order], "events": [
            {"seq": 1, "ts": "", "kind": "llm_call", "conversation_id": "x",
             "data": {"provider": "p", "tokens_in": 1000, "tokens_out": 50, "latency_s": 1}},
            {"seq": 2, "ts": "", "kind": "message_out", "conversation_id": "x",
             "data": {"text": "1650 جنيه", "latency_s": 1.4}}]}, ensure_ascii=False),
        encoding="utf-8")
    out = build_report(results, __import__("pathlib").Path("bench/assumptions.yaml"),
                       tmp_path / "report")
    text = out.read_text(encoding="utf-8")
    assert "price_shopper" in text and "Hours saved" in text and "simulation" in text
    for f in ("summary.json", "grades.jsonl", "success_by_category.png", "impact.png"):
        assert (tmp_path / "report" / f).exists()


def test_confirmation_never_raises_refusals_in_any_scenario():
    a = load_assumptions(__import__("pathlib").Path("bench/assumptions.yaml"))
    for s in ("low", "base", "high"):
        assert a["refusal_rate_with_confirmation"][s] <= a["refusal_rate_without_confirmation"][s], s


def test_build_report_grades_against_a_given_card_set(tmp_path):
    from pathlib import Path

    from moderator.bench.heldout import HELDOUT_DIR
    results = tmp_path / "results"
    results.mkdir()
    (results / "h-price-1.json").write_text(json.dumps({
        "card_id": "h-price-1", "category": "price_shopper", "script": "arabic", "flow": "sales",
        "turns": 1, "ended_by": "done", "transcript": [{"role": "customer", "text": "بكام؟"}],
        "raw_messages": [], "orders": [], "events": []}, ensure_ascii=False), encoding="utf-8")
    out = build_report(results, Path("bench/assumptions.yaml"), tmp_path / "r", cards_dir=HELDOUT_DIR)
    assert "| price_shopper | 100% |" in out.read_text(encoding="utf-8")


def test_impact_model_running_cost_payback_and_roi():
    a = {**A, "hosting_egp_month": {"low": 250, "base": 250, "high": 250, "source": "t"}}
    m = impact_model(a, BENCH, "base")
    running = 218.4 + 250
    gross = m["moderator_cost_saved"] + 15600
    assert m["running_cost_egp"] == pytest.approx(running)
    assert m["payback_days"] == pytest.approx(running / (gross / 30))
    assert m["roi_multiple"] == pytest.approx((gross - running) / running)
    assert m["net_cost_saved"] == pytest.approx(gross - running)


def test_real_assumptions_include_hosting():
    a = load_assumptions(__import__("pathlib").Path("bench/assumptions.yaml"))
    assert a["hosting_egp_month"]["low"] >= a["hosting_egp_month"]["high"]


def test_report_uses_readable_writing_style_names():
    from moderator.bench.report import SCRIPT_LABELS
    assert SCRIPT_LABELS == {"arabic": "Egyptian Arabic", "arabizi": "Franco (Arabic in English letters)",
                             "mixed": "Mixed Arabic and English"}


def test_reply_time_cell_says_how_it_was_measured():
    from moderator.bench.grader import Grade, summarize
    from moderator.bench.report import reply_time_cell

    def g(median):
        return Grade("c", "clear_buyer", "arabic", True, [], [], True, 2, median, 1, 1, 1, 0)

    s = summarize([g(2.0), g(3.0), g(None)])
    assert s["timed_conversations"] == 2
    assert reply_time_cell(s) == "2.5 s (2 conversations that called the live model)"
    assert "cache" in reply_time_cell(summarize([g(None)]))
