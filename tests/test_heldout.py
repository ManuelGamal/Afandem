from collections import Counter
from datetime import datetime

from moderator.bench.cards import CATEGORIES, Card, load_cards
from moderator.bench.heldout import HELDOUT_DIR, build_heldout_cards
from moderator.bench.make_cards import build_cards
from moderator.store.catalog import Catalog
from moderator.store.orders import OrderBook


def test_heldout_shape():
    cards = [Card(**c) for c in build_heldout_cards(Catalog.load())]
    assert len(cards) == 30
    assert Counter(c.category for c in cards) == {cat: 3 for cat in CATEGORIES}
    assert Counter(c.script for c in cards) == {"arabic": 10, "arabizi": 10, "mixed": 10}
    assert all(c.id.startswith("h-") for c in cards) and len({c.id for c in cards}) == 30


def test_heldout_does_not_reuse_dev_people_or_openings():
    cat = Catalog.load()
    dev = [Card(**c) for c in build_cards(cat)]
    held = [Card(**c) for c in build_heldout_cards(cat)]
    dev_phones = {c.persona.split("mobile is ")[1][:11] for c in dev}
    assert not any(c.persona.split("mobile is ")[1][:11] in dev_phones for c in held)
    dev_openings = {c.opening for c in dev if c.opening}
    assert not any(c.opening in dev_openings for c in held if c.opening)


def test_heldout_cards_are_consistent():
    cat = Catalog.load()
    for c in (Card(**d) for d in build_heldout_cards(cat)):
        if c.flow == "sales":
            assert c.opening and c.checkout is None, c.id
        else:
            assert c.checkout and c.opening is None, c.id
            OrderBook(cat).create("x", **c.checkout, source="checkout",
                                  now=datetime(2026, 10, 8, 12))
        e = c.expect
        if e.product_id:
            p = cat.get(e.product_id)
            assert e.color in p.colors and p.stock.get(e.size, 0) > 0, c.id


def test_heldout_file_matches_builder():
    assert [c.id for c in load_cards(HELDOUT_DIR)] == [d["id"] for d in build_heldout_cards(Catalog.load())]
