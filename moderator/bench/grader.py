"""Grade bench results from the database state and the transcript. No LLM judges."""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass
from decimal import Decimal

from moderator.bench.cards import Card
from moderator.events import upsell_value
from moderator.store.catalog import Catalog
from moderator.store.orders import Order
from moderator.text import clean_digits, fold_text, is_explicit_yes, money_mentions

_NUM = re.compile(r"\d+(?:\.\d+)?")


@dataclass
class Grade:
    card_id: str
    category: str
    script: str
    success: bool
    failures: list[str]
    violations: list[str]
    self_served: bool
    turns: int
    median_reply_s: float | None
    tokens_in: int
    tokens_out: int
    llm_calls: int
    upsell_egp: int

    def to_dict(self) -> dict:
        return asdict(self)


def _numbers(text: str) -> set[Decimal]:
    return {Decimal(n) for n in _NUM.findall(clean_digits(text).replace(",", ""))}


def allowed_amounts(result: dict) -> set[Decimal]:
    allowed: set[Decimal] = set()
    for m in result["raw_messages"]:
        if m["role"] == "tool" or (m["role"] == "user" and isinstance(m.get("content"), str)):
            allowed |= _numbers(m["content"])
    return allowed


def _conv_orders(result: dict) -> list[dict]:
    return result["orders"]


def grade(card: Card, result: dict, catalog: Catalog) -> Grade:
    e = card.expect
    failures, violations = [], []
    orders = _conv_orders(result)
    events = result["events"]
    handoffs = [ev for ev in events if ev["kind"] == "handoff"]

    if e.final_status == "any":
        pass  # e.g. off-topic: an off-topic visitor who ends up buying is fine
    elif e.final_status == "none":
        live = [o for o in orders if o["status"] in ("confirmed", "needs_human", "shipped")]
        if live:
            failures.append(f"expected no order, got {live[-1]['status']}")
    elif not orders:
        failures.append(f"expected {e.final_status}, no order")
    else:
        o = orders[-1]
        item = o["items"][0] if o["items"] else {}
        checks = [("status", e.final_status, o["status"]),
                  ("cancel_reason", e.cancel_reason, o["cancel_reason"]),
                  ("product_id", e.product_id, item.get("product_id")),
                  ("size", e.size, item.get("size")), ("color", e.color, item.get("color")),
                  ("qty", e.qty, item.get("qty")), ("zone_id", e.zone_id, o["zone_id"]),
                  ("delivery_date", e.delivery_date, o["delivery_date"])]
        for name, want, got in checks:
            if want is not None and want != got:
                failures.append(f"{name}: expected {want}, got {got}")
        folded = fold_text(o["address"]).split()
        for token in e.address_contains:
            if fold_text(token) not in folded:
                failures.append(f"address missing '{token}': {o['address']}")
    if e.handoff is True and not handoffs:
        failures.append("expected a handoff")
    if e.handoff is False and handoffs:
        failures.append("unexpected handoff")

    allowed = allowed_amounts(result)
    for m in result["transcript"]:
        if m["role"] != "agent":
            continue
        for amount in money_mentions(m["text"]):
            if amount not in allowed:
                violations.append(f"unsupported amount {amount} EGP in: {m['text'][:80]}")
    customer = [m["text"] for m in result["transcript"] if m["role"] == "customer"]
    if any(o["status"] == "confirmed" for o in orders) and not any(map(is_explicit_yes, customer)):
        violations.append("order confirmed without an explicit yes from the customer")
    if card.no_reply and orders and orders[-1]["status"] != "cancelled":
        violations.append(f"no-reply order ended {orders[-1]['status']}, not cancelled")

    # Time only replies that called the live model: a reply served from the cache takes ~0 s.
    latencies, live = [], False
    for ev in events:
        if ev["kind"] == "llm_call":
            live = live or ev["data"].get("provider") != "cache"
        elif ev["kind"] == "message_out":
            if live and ev["data"].get("latency_s") is not None:
                latencies.append(ev["data"]["latency_s"])
            live = False
    llm = [ev for ev in events if ev["kind"] == "llm_call"]
    upsell = sum(upsell_value(Order(**o), catalog) for o in orders
                 if o["status"] in ("confirmed", "shipped"))
    return Grade(card.id, card.category, card.script, not failures and not violations, failures,
                 violations, not handoffs, result["turns"],
                 statistics.median(latencies) if latencies else None,
                 sum(ev["data"].get("tokens_in", 0) for ev in llm),
                 sum(ev["data"].get("tokens_out", 0) for ev in llm), len(llm), upsell)


def _rate(grades: list[Grade]) -> float:
    return round(sum(g.success for g in grades) / len(grades), 3) if grades else 0.0


def summarize(grades: list[Grade], self_service_pool: list[Grade] | None = None) -> dict:
    by_cat, by_script = defaultdict(list), defaultdict(list)
    for g in grades:
        by_cat[g.category].append(g)
        by_script[g.script].append(g)
    pool = self_service_pool if self_service_pool is not None else grades
    latencies = [g.median_reply_s for g in grades if g.median_reply_s is not None]
    examples = [v for g in grades for v in g.violations][:5]
    n = len(grades) or 1
    return {
        "cards": len(grades),
        "success_rate": _rate(grades),
        "by_category": {k: _rate(v) for k, v in sorted(by_cat.items())},
        "by_script": {k: _rate(v) for k, v in sorted(by_script.items())},
        "violations": sum(len(g.violations) for g in grades),
        "violation_examples": examples,
        "self_service_rate": round(sum(g.self_served for g in pool) / len(pool), 3) if pool else 0.0,
        "median_turns": statistics.median([g.turns for g in grades]) if grades else 0,
        "median_reply_s": round(statistics.median(latencies), 2) if latencies else None,
        "timed_conversations": len(latencies),
        "mean_tokens_in": round(sum(g.tokens_in for g in grades) / n),
        "mean_tokens_out": round(sum(g.tokens_out for g in grades) / n),
        "mean_llm_calls": round(sum(g.llm_calls for g in grades) / n, 1),
        "upsell_orders": sum(1 for g in grades if g.upsell_egp > 0),
        "upsell_egp": sum(g.upsell_egp for g in grades),
    }
