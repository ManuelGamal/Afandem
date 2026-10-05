"""Bench customer cards: who the simulated customer is and what a correct outcome looks like."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

CATEGORIES = ["clear_buyer", "size_unsure", "price_shopper", "change_at_confirmation",
              "vague_address", "reschedule", "declines", "no_reply", "complaint", "off_topic"]
CARDS_DIR = Path(__file__).resolve().parents[2] / "bench" / "cards"


class Expect(BaseModel):
    final_status: Literal["confirmed", "cancelled", "needs_human", "none"]
    cancel_reason: str | None = None
    product_id: str | None = None
    size: str | None = None
    color: str | None = None
    qty: int | None = None
    zone_id: str | None = None
    address_contains: list[str] = []
    delivery_date: str | None = None
    handoff: bool | None = None


class Card(BaseModel):
    id: str
    category: Literal["clear_buyer", "size_unsure", "price_shopper", "change_at_confirmation",
                      "vague_address", "reschedule", "declines", "no_reply", "complaint",
                      "off_topic"]
    script: Literal["arabic", "arabizi", "mixed"]
    flow: Literal["sales", "checkout"]
    persona: str
    goal: str
    hidden_facts: list[str] = []
    opening: str | None = None
    checkout: dict | None = None
    no_reply: bool = False
    max_turns: int = 10
    expect: Expect


def load_cards(directory: Path = CARDS_DIR) -> list[Card]:
    cards: list[Card] = []
    for path in sorted(Path(directory).glob("*.yaml")):
        cards += [Card(**c) for c in yaml.safe_load(path.read_text(encoding="utf-8")) or []]
    ids = [c.id for c in cards]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate card ids: {sorted(dupes)}")
    return cards
