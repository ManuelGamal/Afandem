"""Static shop catalog: products, size charts and delivery zones (fictional shop)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from moderator.text import fold_text

SEED_PATH = Path(__file__).with_name("seed_data.json")
SIZE_ORDER = ["S", "M", "L", "XL", "XXL", "30", "32", "34", "36", "38", "ONE"]


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
    def __init__(self, data: dict):
        self.shop: dict = data["shop"]
        self.charts: dict[str, dict] = data["charts"]
        self.products: dict[str, Product] = {p["id"]: Product(**p) for p in data["products"]}
        self.zones: list[Zone] = [Zone(**z) for z in data["zones"]]

    @classmethod
    def load(cls, path: Path = SEED_PATH) -> Catalog:
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def get(self, product_id: str) -> Product | None:
        return self.products.get(str(product_id).strip().upper())

    def search(self, query: str, category: str | None = None, max_price: int | None = None,
               limit: int = 5) -> list[Product]:
        words = [w for w in fold_text(query).split() if len(w) > 1]
        scored = []
        for p in self.products.values():
            if category and p.category != category:
                continue
            if max_price is not None and p.price > max_price:
                continue
            hay = fold_text(f"{p.name_ar} {p.name_en} {p.category} {' '.join(p.colors)}")
            score = sum(1 for w in words if w in hay)
            if score or not words:
                scored.append((score, p))
        scored.sort(key=lambda sp: (-sp[0], sp[1].price))
        return [p for _, p in scored[:limit]]

    def recommend_size(self, product_id: str, height_cm: float, weight_kg: float,
                       fit: str | None = None) -> dict:
        product = self.get(product_id)
        if product is None:
            raise KeyError(product_id)
        chart = self.charts[product.chart]
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
