"""The shop's database: products, stock per size, size charts and delivery zones in SQLite.

Every read is a query, so stock is always live: orders reserve and release it, and the owner
can edit it. Each `Catalog.load()` is its own shop (one per browser sandbox or bench card).
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from moderator.text import fold_text

SEED_PATH = Path(__file__).with_name("seed_data.json")
SIZE_ORDER = ["S", "M", "L", "XL", "XXL", "30", "32", "34", "36", "38", "ONE"]
LOW_STOCK = 3  # at or below this, the owner's inventory view flags a size

# Shopping words customers use (Arabic, Franco, English; fold_text form, matched as prefixes) and the
# words the catalog uses for them, in Arabic and English, so "tshirt", "pantalonat eswed" or "شوزات"
# find the right products whether a catalog is named in Arabic or in English.
_ALIAS_WORDS = {
    ("tshirt", "tishirt", "teshirt", "tshert", "tee", "تيشيرت", "تيشرت"): ["tee", "تيشيرت"],
    ("pantalon", "bantalon", "bantaloon", "pants", "trouser", "بنطلون"):
        ["pant", "بنطلون", "jean", "جينز", "jogger", "chino"],
    ("jeans", "jean", "geenz", "jeenz", "جينز"): ["jean", "جينز", "denim"],
    ("hoodie", "hoody", "hody", "هودي"): ["hoodie", "هودي"],
    ("sweatshirt", "sweet", "swet", "سويت"): ["sweatshirt", "سويت"],
    ("2amees", "amees", "qamees", "قميص"): ["shirt", "قميص"],
    ("short", "شورت"): ["short", "شورت"],
    ("jacket", "jaket", "jakit", "جاكيت", "جاكت"): ["jacket", "جاكيت"],
    ("skirt", "jupe", "جيب"): ["skirt", "جيبة"],
    ("dress", "fostan", "فستان"): ["dress", "فستان"],
    ("bag", "tote", "shanta", "شنط"): ["bag", "شنطة"],
    ("cap", "كاب"): ["cap", "كاب"],
    ("sock", "sharab", "شراب"): ["sock", "شراب"],
    ("shoe", "sneaker", "شوز", "جزم", "حذا", "كوتشي", "shoz", "shooz", "gazma", "kotchy"):
        ["shoe", "sneaker", "runner", "trainer"],
    ("رجالي", "regali", "rgali"): ["men"],
    ("حريمي", "harimi", "7arimi"): ["women"],
    ("eswed", "iswed", "aswad", "swed", "black"): ["أسود", "black"],
    ("abyad", "abiad", "white"): ["أبيض", "white"],
    ("ramady", "ramadi", "grey", "gray"): ["رمادي", "grey", "gray"],
    ("kohly", "ko7ly", "navy"): ["كحلي", "navy"],
    ("beige", "bej"): ["بيج", "beige"],
    ("zeity", "zity", "olive"): ["زيتي", "olive"],
    ("azra2", "azrak", "blue"): ["أزرق", "blue"],
    ("ahmar", "a7mar", "red"): ["أحمر", "red"],
    ("bonni", "brown"): ["بني", "brown"],
    ("akhdar", "a5dar", "green"): ["أخضر", "green"],
    ("wardy", "pink"): ["وردي", "pink"],
}
_ALIASES = {fold_text(stem): [fold_text(t) for t in terms]
            for stems, terms in _ALIAS_WORDS.items() for stem in stems}
_LATIN = re.compile("[a-z]")


def _query_groups(query: str) -> list[list[str]]:
    """One group per query word: the word itself and the words the catalog may use for it."""
    q = re.sub("t[ -]?shirt", "tshirt", query.lower()).replace("تي شيرت", "تيشيرت")
    groups = []
    for w in (w for w in fold_text(q).split() if len(w) > 1):
        group = [w]
        if w.startswith("ال") and len(w) > 4:  # the Arabic definite article
            group.append(w[2:])
        group += [t for stem, terms in _ALIASES.items() if w.startswith(stem) for t in terms]
        groups.append(group)
    return groups


def _matches(term: str, hay: str) -> bool:
    """Latin words match at the start of a word ("tshirt" is not in "sweatshirt"); Arabic words
    match anywhere, so prefixes such as و or ب don't hide them."""
    return f" {term}" in hay if _LATIN.search(term) else term in hay


SCHEMA = """
CREATE TABLE shop (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE products (
  id TEXT PRIMARY KEY, name_ar TEXT NOT NULL, name_en TEXT NOT NULL, category TEXT NOT NULL,
  price INTEGER NOT NULL CHECK (price > 0), colors TEXT NOT NULL, chart TEXT NOT NULL,
  pairs_with TEXT NOT NULL);
CREATE TABLE inventory (
  product_id TEXT NOT NULL REFERENCES products(id), size TEXT NOT NULL,
  stock INTEGER NOT NULL CHECK (stock >= 0), PRIMARY KEY (product_id, size));
CREATE TABLE size_charts (
  chart TEXT NOT NULL, size TEXT NOT NULL, h_min REAL, h_max REAL, w_min REAL, w_max REAL,
  PRIMARY KEY (chart, size));
CREATE TABLE delivery_zones (
  id TEXT PRIMARY KEY, name_ar TEXT NOT NULL, fee INTEGER NOT NULL, days_min INTEGER NOT NULL,
  days_max INTEGER NOT NULL, aliases TEXT NOT NULL);
CREATE TABLE orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT, status TEXT, phone TEXT,
  data TEXT);
CREATE TABLE stock_movements (
  id INTEGER PRIMARY KEY AUTOINCREMENT, product_id TEXT NOT NULL, size TEXT NOT NULL,
  delta INTEGER NOT NULL, stock_after INTEGER NOT NULL, reason TEXT NOT NULL, order_id INTEGER);
"""


class ShopDB:
    """One SQLite connection plus the lock every writer holds."""

    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.RLock()


@dataclass
class Product:
    id: str
    name_ar: str
    name_en: str
    category: str
    price: int
    colors: list[str]
    stock: dict[str, int]
    chart: str
    pairs_with: list[str]

    def available_sizes(self) -> list[str]:
        return [s for s, n in self.stock.items() if n > 0]

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name_ar, "name_en": self.name_en,
                "category": self.category, "price": self.price, "colors": self.colors,
                "stock_by_size": self.stock,
                "sizes_in_stock": self.available_sizes(),
                "sizes_out_of_stock": [s for s, n in self.stock.items() if n <= 0]}


@dataclass
class Zone:
    id: str
    name_ar: str
    aliases: list[str]
    fee: int
    days_min: int
    days_max: int


class Catalog:
    def __init__(self, db: ShopDB):
        self.db = db
        q = db.conn.execute
        self.shop: dict = json.loads(q("SELECT value FROM shop WHERE key='meta'").fetchone()[0])
        self.charts: dict[str, dict] = {}
        for chart, size, h0, h1, w0, w1 in q("SELECT chart, size, h_min, h_max, w_min, w_max FROM size_charts"):
            self.charts.setdefault(chart, {})[size] = {"h": [h0, h1], "w": [w0, w1]}
        for (chart,) in q("SELECT DISTINCT chart FROM products"):
            self.charts.setdefault(chart, {})  # one-size products have no chart rows
        self.zones: list[Zone] = [
            Zone(id=r[0], name_ar=r[1], fee=r[2], days_min=r[3], days_max=r[4],
                 aliases=json.loads(r[5]))
            for r in q("SELECT id, name_ar, fee, days_min, days_max, aliases FROM delivery_zones ORDER BY rowid")]

    # --- creation ------------------------------------------------------------------
    @classmethod
    def load(cls, path: Path = SEED_PATH, db_path: str = ":memory:") -> Catalog:
        """A fresh shop database seeded from seed_data.json."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        db = ShopDB(db_path)
        c = db.conn
        c.executescript(SCHEMA)
        c.execute("INSERT INTO shop VALUES ('meta', ?)", (json.dumps(data["shop"], ensure_ascii=False),))
        for chart, sizes in data["charts"].items():
            for size, rng in sizes.items():
                c.execute("INSERT INTO size_charts VALUES (?, ?, ?, ?, ?, ?)",
                          (chart, size, rng["h"][0], rng["h"][1], rng["w"][0], rng["w"][1]))
        for p in data["products"]:
            c.execute("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                      (p["id"], p["name_ar"], p["name_en"], p["category"], p["price"],
                       json.dumps(p["colors"], ensure_ascii=False), p["chart"],
                       json.dumps(p["pairs_with"])))
            for size, n in p["stock"].items():
                c.execute("INSERT INTO inventory VALUES (?, ?, ?)", (p["id"], size, n))
        for z in data["zones"]:
            c.execute("INSERT INTO delivery_zones VALUES (?, ?, ?, ?, ?, ?)",
                      (z["id"], z["name_ar"], z["fee"], z["days_min"], z["days_max"],
                       json.dumps(z["aliases"], ensure_ascii=False)))
        c.commit()
        return cls(db)

    # --- reads (always live) ---------------------------------------------------------
    def _stock(self, product_id: str) -> dict[str, int]:
        rows = self.db.conn.execute("SELECT size, stock FROM inventory WHERE product_id=?",
                                    (product_id,)).fetchall()
        return dict(sorted(rows, key=lambda r: SIZE_ORDER.index(r[0]) if r[0] in SIZE_ORDER else 99))

    def _product(self, row) -> Product:
        pid, name_ar, name_en, category, price, colors, chart, pairs = row
        return Product(pid, name_ar, name_en, category, price, json.loads(colors),
                       self._stock(pid), chart, json.loads(pairs))

    @property
    def products(self) -> dict[str, Product]:
        rows = self.db.conn.execute("SELECT * FROM products ORDER BY rowid").fetchall()
        return {r[0]: self._product(r) for r in rows}

    def get(self, product_id: str) -> Product | None:
        row = self.db.conn.execute("SELECT * FROM products WHERE id=?",
                                   (str(product_id).strip().upper(),)).fetchone()
        return self._product(row) if row else None

    def search(self, query: str, category: str | None = None, max_price: int | None = None,
               limit: int = 5) -> list[Product]:
        """Products ranked by how many query words they match (a word's alternatives count once),
        then in stock first, then cheapest."""
        groups = _query_groups(query)
        found = self._rank(groups, category, max_price, limit)
        if category and not found:  # the category was a guess that matches nothing: search them all
            found = self._rank(groups, None, max_price, limit)
        return found

    def _rank(self, groups: list[list[str]], category: str | None, max_price: int | None,
              limit: int) -> list[Product]:
        scored = []
        for p in self.products.values():
            if category and p.category != category:
                continue
            if max_price is not None and p.price > max_price:
                continue
            hay = " " + fold_text(f"{p.name_ar} {p.name_en} {p.category} {' '.join(p.colors)}")
            score = sum(1 for g in groups if any(_matches(t, hay) for t in g))
            if score or not groups:
                scored.append((score, p))
        scored.sort(key=lambda sp: (-sp[0], not sp[1].available_sizes(), sp[1].price))
        return [p for _, p in scored[:limit]]

    def recommend_size(self, product_id: str, height_cm: float, weight_kg: float,
                       fit: str | None = None) -> dict:
        product = self.get(product_id)
        if product is None:
            raise KeyError(product_id)
        chart = self.charts[product.chart]
        if not chart and "ONE" not in product.stock:  # sized, but no chart (e.g. imported shoes)
            return {"size": None, "between": None, "in_stock": None,
                    "available": product.available_sizes(),
                    "note": "no size chart for this product; ask the customer's usual size"}
        if not chart:
            return {"size": "ONE", "between": None, "in_stock": product.stock.get("ONE", 0) > 0,
                    "available": product.available_sizes()}

        def score(rng: dict) -> float:
            mid_h = sum(rng["h"]) / 2
            mid_w = sum(rng["w"]) / 2
            return abs(height_cm - mid_h) / 10 + abs(weight_kg - mid_w) / 5

        ranked = sorted(chart, key=lambda s: score(chart[s]))
        best = ranked[0]
        between = None
        if len(ranked) > 1 and score(chart[ranked[1]]) - score(chart[best]) < 0.5:
            between = sorted(ranked[:2], key=SIZE_ORDER.index)
        sizes = sorted(chart, key=SIZE_ORDER.index)
        if fit in ("loose", "واسع"):
            best = between[1] if between else sizes[min(sizes.index(best) + 1, len(sizes) - 1)]
        elif fit in ("tight", "fitted", "ضيق"):
            best = between[0] if between else sizes[max(sizes.index(best) - 1, 0)]
        return {"size": best, "between": between, "in_stock": product.stock.get(best, 0) > 0,
                "available": product.available_sizes()}

    def find_zone(self, area: str) -> Zone | None:
        folded = fold_text(area)
        if not folded:
            return None
        pairs = [(fold_text(a), z) for z in self.zones for a in z.aliases]
        for alias, zone in pairs:
            if alias == folded:
                return zone
        for alias, zone in sorted(pairs, key=lambda az: -len(az[0])):
            if f" {alias} " in f" {folded} ":
                return zone
        return None

    def inventory(self) -> list[dict]:
        rows = self.db.conn.execute(
            "SELECT p.id, p.name_ar, p.name_en, i.size, i.stock FROM inventory i "
            "JOIN products p ON p.id = i.product_id ORDER BY p.rowid").fetchall()
        out = [{"product_id": r[0], "name": r[1], "name_en": r[2], "size": r[3], "stock": r[4],
                "low": r[4] <= LOW_STOCK} for r in rows]
        return sorted(out, key=lambda r: (r["product_id"], SIZE_ORDER.index(r["size"])
                                          if r["size"] in SIZE_ORDER else 99))

    def stock_movements(self, limit: int = 50) -> list[dict]:
        rows = self.db.conn.execute(
            "SELECT product_id, size, delta, stock_after, reason, order_id FROM stock_movements "
            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"product_id": r[0], "size": r[1], "delta": r[2], "stock_after": r[3],
                 "reason": r[4], "order_id": r[5]} for r in rows]

    # --- writes ------------------------------------------------------------------------
    def move_stock(self, product_id: str, size: str, delta: int, reason: str,
                   order_id: int | None = None) -> int:
        """Change stock by `delta` inside the caller's transaction; returns the new stock.
        Raises ValueError if it would go below zero."""
        with self.db.lock:
            row = self.db.conn.execute("SELECT stock FROM inventory WHERE product_id=? AND size=?",
                                       (product_id, size)).fetchone()
            if row is None:
                raise KeyError(f"{product_id}/{size}")
            after = row[0] + delta
            if after < 0:
                raise ValueError(f"only {row[0]} left of {product_id}/{size}")
            self.db.conn.execute("UPDATE inventory SET stock=? WHERE product_id=? AND size=?",
                                 (after, product_id, size))
            self.db.conn.execute(
                "INSERT INTO stock_movements (product_id, size, delta, stock_after, reason, order_id) "
                "VALUES (?, ?, ?, ?, ?, ?)", (product_id, size, delta, after, reason, order_id))
            return after

    def set_stock(self, product_id: str, size: str, stock: int) -> dict:
        """The owner sets a size's stock (e.g. after a delivery from the workshop)."""
        if stock < 0:
            raise ValueError("stock cannot be negative")
        pid, size = str(product_id).strip().upper(), str(size).strip().upper()
        with self.db.lock:
            row = self.db.conn.execute("SELECT stock FROM inventory WHERE product_id=? AND size=?",
                                       (pid, size)).fetchone()
            if row is None:
                raise KeyError(f"{pid}/{size}")
            if stock != row[0]:
                self.move_stock(pid, size, stock - row[0], "owner_update")
            self.db.conn.commit()
            return {"product_id": pid, "size": size, "stock": stock, "previous": row[0]}
