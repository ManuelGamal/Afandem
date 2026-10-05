from collections import Counter
from datetime import datetime

from moderator.bench.cards import CATEGORIES, Card, load_cards
from moderator.bench.make_cards import build_cards
from moderator.store.catalog import Catalog
from moderator.store.orders import OrderBook


def test_build_cards_shape():
    cards = [Card(**c) for c in build_cards(Catalog.load())]
    assert len(cards) == 60
    assert Counter(c.category for c in cards) == {cat: 6 for cat in CATEGORIES}
    assert Counter(c.script for c in cards) == {"arabic": 20, "arabizi": 20, "mixed": 20}
    assert len({c.id for c in cards}) == 60


def test_cards_are_internally_consistent():
    cat = Catalog.load()
    for c in (Card(**d) for d in build_cards(cat)):
        if c.flow == "sales":
            assert c.opening and c.checkout is None, c.id
        else:
            assert c.checkout and c.opening is None, c.id
            OrderBook(cat).create("x", **c.checkout, source="checkout",
                                  now=datetime(2026, 10, 8, 12))  # raises if invalid
        e = c.expect
        if e.product_id:
            p = cat.get(e.product_id)
            assert e.color in p.colors and p.stock.get(e.size, 0) > 0, c.id


def test_generated_file_matches_builder():
    assert [c.id for c in load_cards()] == [d["id"] for d in build_cards(Catalog.load())]


def test_openings_use_natural_arabic():
    cards = [Card(**d) for d in build_cards(Catalog.load())]
    for c in cards:
        if c.opening:
            assert "لال" not in c.opening, c.opening
    women = [c for c in cards if c.opening and c.persona.startswith(("Your name is منى",
                                                                      "Your name is هبة",
                                                                      "Your name is ياسمين"))]
    for c in women:
        assert "عايز " not in c.opening and "3ayez" not in c.opening, (c.id, c.opening)
        assert "مش عارف " not in c.opening and "3aref" not in c.opening, (c.id, c.opening)
