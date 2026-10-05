"""Impact model + report: measured bench quality x cited business assumptions.

    uv run python -m moderator.bench.report --results bench/results/run1 --out bench/report
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import yaml  # noqa: E402

from moderator.bench.cards import CARDS_DIR, load_cards  # noqa: E402
from moderator.bench.grader import Grade, grade, summarize  # noqa: E402
from moderator.store.catalog import Catalog  # noqa: E402

SCENARIOS = ("low", "base", "high")
WEEKS_PER_MONTH = 4.33
PURCHASE_CATEGORIES = {"clear_buyer", "size_unsure"}


def load_assumptions(path: Path) -> dict[str, dict]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def bench_inputs(summary: dict, grades: list[Grade]) -> dict:
    purchases = [g for g in grades if g.category in PURCHASE_CATEGORIES]
    upsells = [g for g in grades if g.upsell_egp > 0]
    return {
        "self_service_rate": summary["self_service_rate"],
        "median_turns": max(summary["median_turns"], 1),
        "mean_tokens_in": summary["mean_tokens_in"],
        "mean_tokens_out": summary["mean_tokens_out"],
        "upsell_share": len(upsells) / len(purchases) if purchases else 0.0,
        "mean_upsell_egp": (sum(g.upsell_egp for g in upsells) / len(upsells)) if upsells else 0.0,
    }


def impact_model(a: dict, bench: dict, scenario: str) -> dict:
    v = {k: row[scenario] for k, row in a.items()}
    days = v["working_days_per_month"]
    ss = bench["self_service_rate"]
    dm_hours = v["dms_per_day"] * v["minutes_per_dm"] / 60 * ss * days
    call_hours = v["cod_orders_per_day"] * v["minutes_per_confirmation_call"] / 60 * ss * days
    hours = dm_hours + call_hours
    moderator_saved = hours * v["moderator_salary_egp_month"] / v["moderator_hours_month"]
    refusals = v["cod_orders_per_day"] * days * (v["refusal_rate_without_confirmation"]
                                                 - v["refusal_rate_with_confirmation"])
    failed_cost = v["outbound_shipping_egp"] + v["return_shipping_egp"]
    conversations = (v["dms_per_day"] / bench["median_turns"] + v["cod_orders_per_day"]) * days
    usd_per_conv = (bench["mean_tokens_in"] * v["llm_usd_per_mtok_in"]
                    + bench["mean_tokens_out"] * v["llm_usd_per_mtok_out"]) / 1e6
    llm_cost = conversations * usd_per_conv * v["usd_to_egp"]
    revenue_speed = (v["dms_per_day"] * v["buying_intent_share_of_dms"]
                     * v["conversion_uplift_from_fast_replies"] * ss * v["average_order_egp"] * days)
    revenue_upsell = (v["cod_orders_per_day"] * days * v["chat_order_share"]
                      * bench["upsell_share"] * bench["mean_upsell_egp"])
    return {
        "dm_hours": dm_hours, "call_hours": call_hours, "hours_saved_month": hours,
        "hours_saved_week": hours / WEEKS_PER_MONTH, "moderator_cost_saved": moderator_saved,
        "refusals_prevented": refusals, "failed_delivery_cost": failed_cost,
        "delivery_cost_saved": refusals * failed_cost, "conversations_month": conversations,
        "llm_cost_egp": llm_cost,
        "net_cost_saved": moderator_saved + refusals * failed_cost - llm_cost,
        "revenue_speed": revenue_speed, "revenue_upsell": revenue_upsell,
        "revenue_total": revenue_speed + revenue_upsell,
    }


def _grade_all(results_dir: Path, cards_dir: Path = CARDS_DIR) -> tuple[list[Grade], list]:
    cards = {c.id: c for c in load_cards(cards_dir)}
    catalog = Catalog.load()
    grades, used = [], []
    for path in sorted(Path(results_dir).glob("*.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        card = cards[result["card_id"]]
        grades.append(grade(card, result, catalog))
        used.append(card)
    return grades, used


def _charts(summary: dict, models: dict, out_dir: Path) -> None:
    cats = list(summary["by_category"])
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.barh(cats, [summary["by_category"][c] * 100 for c in cats], color="#0f766e")
    ax.set_xlim(0, 100)
    ax.set_xlabel("task success (%)")
    ax.set_title("Bench: success by customer type (simulation)")
    fig.tight_layout()
    fig.savefig(out_dir / "success_by_category.png", dpi=160)
    plt.close(fig)

    metrics = [("hours_saved_week", "Hours saved / week"),
               ("net_cost_saved", "Net cost saved / month (EGP)"),
               ("revenue_total", "Extra sales / month (EGP, gross)")]
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.6))
    for ax, (key, title) in zip(axes, metrics):
        vals = [models[s][key] for s in SCENARIOS]
        ax.bar(SCENARIOS, vals, color=["#99c5c0", "#0f766e", "#0b4f4a"])
        ax.set_title(title, fontsize=10)
        for i, val in enumerate(vals):
            ax.text(i, val, f"{val:,.0f}", ha="center", va="bottom", fontsize=9)
    fig.suptitle("Impact for one typical shop (low = conservative)")
    fig.tight_layout()
    fig.savefig(out_dir / "impact.png", dpi=160)
    plt.close(fig)


def build_report(results_dir: Path, assumptions_path: Path, out_dir: Path,
                 cards_dir: Path = CARDS_DIR) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    grades, cards = _grade_all(results_dir, cards_dir)
    pool = [g for g, c in zip(grades, cards) if c.expect.handoff is not True]
    summary = summarize(grades, self_service_pool=pool)
    a = load_assumptions(assumptions_path)
    bench = bench_inputs(summary, grades)
    models = {s: impact_model(a, bench, s) for s in SCENARIOS}
    (out_dir / "summary.json").write_text(json.dumps(
        {"bench": summary, "bench_inputs": bench, "impact": models}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    (out_dir / "grades.jsonl").write_text(
        "\n".join(json.dumps(g.to_dict(), ensure_ascii=False) for g in grades) + "\n",
        encoding="utf-8")
    _charts(summary, models, out_dir)

    def row(label, key, fmt="{:,.0f}"):
        return f"| {label} | " + " | ".join(fmt.format(models[s][key]) for s in SCENARIOS) + " |"

    lines = [
        "# Bench and impact report",
        "",
        "The shop is fictional. **Measured** numbers come from the simulation bench "
        f"({summary['cards']} simulated customer conversations, graded by fixed rules). "
        "**Business** numbers combine those measurements with the cited assumptions below; "
        "`low` is always the conservative case.",
        "",
        "## Measured in simulation",
        "",
        "| Metric | Value |", "|---|---|",
        f"| Task success | {summary['success_rate']:.0%} |",
        f"| Safety violations (made-up prices, confirming without a yes, shipping to unreachable) | {summary['violations']} |",
        f"| Self-service rate (no human needed) | {summary['self_service_rate']:.0%} |",
        f"| Median agent reply time | {summary['median_reply_s']} s |",
        f"| Median customer turns | {summary['median_turns']} |",
        f"| Mean model calls / tokens in / tokens out per conversation | {summary['mean_llm_calls']} / {summary['mean_tokens_in']:,} / {summary['mean_tokens_out']:,} |",
        f"| Suggested-item purchases (simulation) | {summary['upsell_orders']} orders, {summary['upsell_egp']:,} EGP |",
        "",
        "| Customer type | Success |", "|---|---|",
        *[f"| {k} | {v:.0%} |" for k, v in summary["by_category"].items()],
        "",
        "| Writing style | Success |", "|---|---|",
        *[f"| {k} | {v:.0%} |" for k, v in summary["by_script"].items()],
        "",
        "![success by category](success_by_category.png)",
        "",
        "## Impact for one typical shop (per month unless noted)",
        "",
        "| | low | base | high |", "|---|---|---|---|",
        row("Hours saved / week", "hours_saved_week", "{:,.1f}"),
        row("Moderator cost saved (EGP)", "moderator_cost_saved"),
        row("Refused COD deliveries prevented", "refusals_prevented"),
        row("Failed-delivery cost saved (EGP)", "delivery_cost_saved"),
        row("Model cost (EGP)", "llm_cost_egp"),
        row("**Net cost saved (EGP)**", "net_cost_saved"),
        row("Extra sales from faster replies (EGP, gross)", "revenue_speed"),
        row("Extra sales from suggested items (EGP, gross; simulation rate)", "revenue_upsell"),
        row("**Extra sales total (EGP, gross)**", "revenue_total"),
        "",
        "![impact](impact.png)",
        "",
        "## Assumptions",
        "",
        "| Parameter | low | base | high | Source |", "|---|---|---|---|---|",
        *[f"| {k} | {r['low']} | {r['base']} | {r['high']} | {r['source']} |" for k, r in a.items()],
        "",
        "## Formulas",
        "",
        "- Hours saved = DMs/day x minutes per DM x self-service rate x days + orders/day x "
        "minutes per confirmation call x self-service rate x days.",
        "- Moderator cost saved = hours saved x monthly salary / monthly hours.",
        "- Refusals prevented = orders/day x days x (refusal rate without - with confirmation); "
        "each costs outbound + return shipping.",
        "- Model cost = (DMs/day / median turns + orders/day) x days x tokens per conversation x "
        "paid price.",
        "- Extra sales = DMs/day x buying share x conversion uplift x self-service x average order x "
        "days + orders/day x days x chat share x suggested-item rate x mean suggested value.",
        "",
    ]
    if summary["violation_examples"]:
        lines += ["## Violation examples", "", *[f"- {v}" for v in summary["violation_examples"]], ""]
    path = out_dir / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--assumptions", default="bench/assumptions.yaml")
    ap.add_argument("--out", default="bench/report")
    ap.add_argument("--cards", default=str(CARDS_DIR), help="card set the results were run on")
    args = ap.parse_args()
    print(build_report(Path(args.results), Path(args.assumptions), Path(args.out), Path(args.cards)))


if __name__ == "__main__":
    main()
