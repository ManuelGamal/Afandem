"""Deterministic COD risk score. Every point has a reason the owner can read."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from moderator.store.orders import Order, OrderBook
from moderator.text import fold_text, is_valid_eg_mobile

HIGH_VALUE_EGP = 1500
RISKY_CANCEL_REASONS = {"customer_declined", "unreachable"}
_LANDMARKS = {fold_text(w) for w in [
    "جنب", "قدام", "ورا", "امام", "بجوار", "عمارة", "برج", "الدور", "دور", "شقة", "بلوك",
    "فيلا", "مدخل", "building", "floor", "apt", "flat", "near", "villa", "block",
]}


@dataclass
class RiskResult:
    score: int
    level: str
    reasons: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def address_complete(address: str) -> bool:
    words = fold_text(address).split()
    has_digit = any(ch.isdigit() for w in words for ch in w)
    has_landmark = any(w in _LANDMARKS for w in words)
    return len(words) >= 4 and (has_digit or has_landmark)


def score_order(book: OrderBook, order: Order) -> RiskResult:
    score, reasons = 0, []
    others = [o for o in book.by_phone(order.phone) if o.id != order.id]
    if not others:
        score += 1
        reasons.append("first order from this phone")
    if order.total > HIGH_VALUE_EGP:
        score += 1
        reasons.append(f"high value ({order.total} EGP)")
    if not is_valid_eg_mobile(order.phone):
        score += 3
        reasons.append("phone is not a valid Egyptian mobile")
    if not address_complete(order.address):
        score += 2
        reasons.append("address is incomplete (no building number or landmark)")
    cancels = [o for o in others
               if o.status == "cancelled" and o.cancel_reason in RISKY_CANCEL_REASONS]
    if cancels:
        score += min(4, 2 * len(cancels))
        reasons.append(f"{len(cancels)} past cancellation(s) on this phone")
    for note in order.risk_notes[:2]:
        score += 1
        reasons.append(f"agent note: {note}")
    level = "high" if score >= 4 else "medium" if score >= 2 else "low"
    return RiskResult(score, level, reasons)
