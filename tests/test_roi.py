import pytest
from fastapi.testclient import TestClient

from moderator.bench.report import impact_model, load_assumptions
from moderator.roi import ASSUMPTIONS, load_bench, shop_roi
from moderator.server import create_app
from tests.fakes import ScriptedProvider

A = load_assumptions(ASSUMPTIONS)
BENCH = load_bench()


def test_base_inputs_reproduce_the_report_base_case():
    base = {k: A[k]["base"] for k in ("cod_orders_per_day", "dms_per_day",
                                      "moderator_salary_egp_month",
                                      "refusal_rate_without_confirmation", "average_order_egp")}
    out = shop_roi(base, A, BENCH)
    assert out["net_cost_saved"] == pytest.approx(round(impact_model(A, BENCH, "base")["net_cost_saved"]))


def test_more_orders_save_more_and_confirmation_never_raises_refusals():
    small = shop_roi({"cod_orders_per_day": 10, "refusal_rate_without_confirmation": 0.05}, A, BENCH)
    big = shop_roi({"cod_orders_per_day": 100, "refusal_rate_without_confirmation": 0.05}, A, BENCH)
    assert big["delivery_cost_saved"] > small["delivery_cost_saved"] >= 0
    assert big["payback_days"] < small["payback_days"]


def test_roi_endpoint_and_validation():
    c = TestClient(create_app(provider_factory=lambda: ScriptedProvider([]), mode="live"))
    r = c.get("/api/roi", params={"orders": 40, "dms": 150, "salary": 7000, "refusal": 0.25,
                                  "aov": 700})
    body = r.json()
    assert r.status_code == 200 and body["payback_days"] > 0 and body["hours_saved_week"] > 0
    assert c.get("/api/roi", params={"orders": -5}).status_code == 422
    assert c.get("/api/roi", params={"refusal": 2}).status_code == 422
