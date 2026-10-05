"""Per-shop ROI: the report's impact model, base case, with the owner's own numbers."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from moderator.bench.report import impact_model

ROOT = Path(__file__).resolve().parents[1]
ASSUMPTIONS = ROOT / "bench" / "assumptions.yaml"
BENCH_SUMMARY = ROOT / "bench" / "report-heldout" / "summary.json"
# Used only if the held-out report is missing (e.g. a fresh checkout before the bench ran).
DEFAULT_BENCH = {"self_service_rate": 0.93, "median_turns": 2, "mean_tokens_in": 12205,
                 "mean_tokens_out": 240, "upsell_share": 0.0, "mean_upsell_egp": 0.0}
OWNER_INPUTS = ("cod_orders_per_day", "dms_per_day", "moderator_salary_egp_month",
                "refusal_rate_without_confirmation", "average_order_egp")
RESULT_KEYS = ("hours_saved_week", "moderator_cost_saved", "refusals_prevented",
               "delivery_cost_saved", "running_cost_egp", "net_cost_saved", "payback_days",
               "roi_multiple", "revenue_total")


def load_bench(path: Path = BENCH_SUMMARY) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))["bench_inputs"]
    except (OSError, KeyError, json.JSONDecodeError):
        return dict(DEFAULT_BENCH)


def shop_roi(inputs: dict, assumptions: dict, bench: dict) -> dict:
    a = copy.deepcopy(assumptions)
    base_without = a["refusal_rate_without_confirmation"]["base"]
    base_with = a["refusal_rate_with_confirmation"]["base"]
    for key in OWNER_INPUTS:
        if inputs.get(key) is not None:
            a[key]["base"] = float(inputs[key])
    # Confirmation removes the same share of refusals as in the base case, whatever the shop's rate.
    a["refusal_rate_with_confirmation"]["base"] = (
        a["refusal_rate_without_confirmation"]["base"] * base_with / base_without)
    m = impact_model(a, bench, "base")
    return {k: (None if m[k] is None else round(m[k], 1 if k in ("payback_days", "hours_saved_week") else 0))
            for k in RESULT_KEYS}
