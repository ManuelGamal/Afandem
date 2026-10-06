"""Import a real store's catalog from its public Shopify product feed into Afandem's shop format.

    uv run python -m moderator.store.importer https://your-store.com --out data/my-shop.json
    MODERATOR_SEED=data/my-shop.json uv run uvicorn --factory moderator.server:create_app

Every Shopify store publishes /products.json: names, prices, colours, sizes and whether each
variant is available. Exact stock counts are private, so a size the store shows as available gets
an estimated count and a sold-out size gets 0. Delivery zones and size charts stay Afandem's own.
Use it on your own store, or with the owner's permission.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import time
from collections import Counter
from pathlib import Path

import httpx

from moderator.store.catalog import SEED_PATH

USER_AGENT = "Afandem-catalog-import/1.0 (+https://github.com/; one-off catalog import)"
DEFAULT_STOCK_ESTIMATE = 8
MAX_PRODUCTS = 80

_COLOR_OPTION = re.compile(r"colou?r|اللون|لون", re.I)
_SIZE_OPTION = re.compile(r"size|مقاس", re.I)
_ONE_SIZE = {"ONE SIZE", "ONESIZE", "OS", "FREE SIZE", "FREESIZE", "DEFAULT TITLE"}
# Checked in this order: "sweatshirt" is outerwear, not a shirt; "short sleeve" is not shorts.
_CATEGORIES = [
    # The agent's search tool has four categories; shoes go with accessories.
    ("accessories", r"\b(bags?|totes?|caps?|hats?|belts?|socks?|scarf|scarves|wallets?|sunglasses|"
                    r"jewel\w*|accessor\w*|beanies?|shoes?|sneakers?|runners?|boots?|sandals?|"
                    r"slippers?|slides?|flip.?flops?|loafers?|footwear)\b|شنط|كاب|حذاء|جزم|كوتشي|صندل"),
    ("bottoms", r"\b(pants|jeans|trousers|shorts|skirts?|joggers?|cargos?|leggings|denim|sweatpants)\b"
                r"|بنطلون|جينز|شورت"),
    ("outerwear", r"\b(hoodies?|jackets?|coats?|sweatshirts?|cardigans?|blazers?|sweaters?|puffers?|"
                  r"zip.?ups?|pullovers?)\b|هودي|جاكيت|سويت"),
]


def fetch_products(store_url: str, get=httpx.get, max_pages: int = 10, delay_s: float = 0.5,
                   enough: int = 2 * MAX_PRODUCTS) -> list[dict]:
    """Products from a store's public feed, page by page until an empty page or `enough`."""
    base = store_url.rstrip("/")
    products: list[dict] = []
    for page in range(1, max_pages + 1):
        if page > 1:
            time.sleep(delay_s)  # be gentle with the store
        r = get(f"{base}/products.json", params={"limit": 250, "page": page},
                headers={"User-Agent": USER_AGENT}, timeout=20)
        r.raise_for_status()
        batch = r.json().get("products", [])
        if not batch:
            break
        products.extend(batch)
        if len(products) >= enough:
            break
    return products


def _category(product: dict) -> str:
    text = " ".join([product.get("product_type") or "", " ".join(product.get("tags") or []),
                     product.get("title") or ""]).lower()
    for name, pattern in _CATEGORIES:
        if re.search(pattern, text):
            return name
    return "tops"


def _option_position(product: dict, pattern: re.Pattern) -> int | None:
    for i, opt in enumerate(product.get("options") or [], start=1):
        if pattern.search(str(opt.get("name", ""))):
            return opt.get("position") or i
    return None


def _chart(sizes: list[str], charts: dict) -> str:
    for name in ("letters", "waist"):
        if any(s in charts.get(name, {}) for s in sizes):
            return name
    return "one"


def _product(product: dict, pid: str, stock_estimate: int, charts: dict,
             egp_per_unit: float = 1.0) -> dict | None:
    variants = product.get("variants") or []
    prices = [float(v.get("price") or 0) for v in variants]
    if not variants or not prices or min(prices) <= 0:
        return None  # gift cards and free items are not for sale in a chat
    color_at = _option_position(product, _COLOR_OPTION)
    size_at = _option_position(product, _SIZE_OPTION)
    colors: list[str] = []
    stock: dict[str, int] = {}
    for v in variants:
        if color_at:
            color = str(v.get(f"option{color_at}") or "").strip()
            if color and color not in colors:
                colors.append(color)
        size = str(v.get(f"option{size_at}") or "").strip().upper() if size_at else "ONE"
        size = "ONE" if not size or size in _ONE_SIZE else size
        in_stock = stock_estimate if v.get("available", True) else 0
        stock[size] = max(stock.get(size, 0), in_stock)  # in stock if any colour of that size is
    title = str(product.get("title") or "").strip()
    kind = str(product.get("product_type") or "").strip()
    name_en = title  # keep the type in the name when the title does not say it ("Runner (Shoes)")
    if kind and kind.lower().rstrip("s") not in title.lower():
        name_en = f"{title} ({kind})"
    return {"id": pid, "name_ar": title, "name_en": name_en, "category": _category(product),
            "price": int(math.floor(min(prices) * egp_per_unit + 0.5)), "colors": colors or ["standard"], "stock": stock,
            "chart": "one" if list(stock) == ["ONE"] else _chart(list(stock), charts),
            "pairs_with": []}


def _description(types: list[str]) -> str:
    """What the shop sells, for the agent's prompt (it would otherwise assume clothes only)."""
    if not types:
        return "a fashion shop"
    listed = types[0] if len(types) == 1 else f"{', '.join(types[:-1])} and {types[-1]}"
    return f"a shop selling {listed}"


def to_seed(products: list[dict], source: str, stock_estimate: int = DEFAULT_STOCK_ESTIMATE,
            shop_name: str | None = None, base_path: Path = SEED_PATH,
            egp_per_unit: float = 1.0) -> dict:
    """A seed file like seed_data.json: the store's products, Afandem's zones and size charts."""
    base = json.loads(Path(base_path).read_text(encoding="utf-8"))
    shop = dict(base["shop"])
    if shop_name:
        shop["name_ar"] = shop["name_en"] = shop_name
    shop["catalog_source"] = source
    shop["stock_note"] = (f"Stock counts are estimates: {stock_estimate} per size the store shows as "
                          "available, 0 when it shows the size as sold out.")
    out, types = [], Counter()
    for product in products:
        if len(out) >= MAX_PRODUCTS:
            break
        item = _product(product, f"P{len(out) + 1:03d}", stock_estimate, base["charts"], egp_per_unit)
        if item is not None:
            out.append(item)
            if (product.get("product_type") or "").strip():
                types[product["product_type"].strip().lower()] += 1
    shop["description"] = _description([t for t, _ in types.most_common(5)])
    return {"shop": shop, "charts": base["charts"], "products": out, "zones": base["zones"]}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("store_url", help="the store's address, e.g. https://your-store.com")
    ap.add_argument("--out", type=Path, default=Path("data/imported-shop.json"))
    ap.add_argument("--stock", type=int, default=DEFAULT_STOCK_ESTIMATE,
                    help="estimated count for each size the store shows as available")
    ap.add_argument("--name", help="shop name the agent uses (default: Hodoom)")
    ap.add_argument("--egp-per-unit", type=float, default=1.0,
                    help="for a store priced in another currency: EGP per unit of its prices")
    args = ap.parse_args(argv)
    seed = to_seed(fetch_products(args.store_url), args.store_url, args.stock, args.name,
                   egp_per_unit=args.egp_per_unit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(seed, ensure_ascii=False, indent=1), encoding="utf-8")
    sold_out = sum(1 for p in seed["products"] for n in p["stock"].values() if n == 0)
    print(f"{len(seed['products'])} products, {sold_out} sold-out sizes -> {args.out}")
    print(f"Run the shop on it:  MODERATOR_SEED={args.out} uv run uvicorn --factory moderator.server:create_app")


if __name__ == "__main__":
    main()
