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
import csv
import io
import json
import math
import re
import time
from collections import Counter
from pathlib import Path

import httpx

from moderator.store.catalog import SEED_PATH
from moderator.text import clean_digits, to_number

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
    return {"id": pid, "name_ar": title, "name_en": _named(title, kind), "category": _category(product),
            "price": int(math.floor(min(prices) * egp_per_unit + 0.5)), "colors": colors or ["standard"], "stock": stock,
            "chart": "one" if list(stock) == ["ONE"] else _chart(list(stock), charts),
            "pairs_with": []}


def _description(types: list[str]) -> str:
    """What the shop sells, for the agent's prompt (it would otherwise assume clothes only)."""
    if not types:
        return "a fashion shop"
    listed = types[0] if len(types) == 1 else f"{', '.join(types[:-1])} and {types[-1]}"
    return f"a shop selling {listed}"


def _named(title: str, kind: str) -> str:
    """The English name, with the product type when the title does not say it ("Runner (Shoes)")."""
    if kind and kind.lower().rstrip("s") not in title.lower():
        return f"{title} ({kind})"
    return title


def _assemble(items: list[dict], types: Counter, source: str, stock_note: str,
              shop_name: str | None = None, base_path: Path = SEED_PATH) -> dict:
    """A seed file like seed_data.json: the imported products, Afandem's zones and size charts."""
    base = json.loads(Path(base_path).read_text(encoding="utf-8"))
    shop = dict(base["shop"])
    if shop_name:
        shop["name_ar"] = shop["name_en"] = shop_name
    shop["catalog_source"] = source
    shop["stock_note"] = stock_note
    shop["description"] = _description([t for t, _ in types.most_common(5)])
    products = []
    for item in items[:MAX_PRODUCTS]:
        stock = item["stock"]
        products.append({"id": f"P{len(products) + 1:03d}", **item,
                         "chart": "one" if list(stock) == ["ONE"] else _chart(list(stock), base["charts"]),
                         "pairs_with": []})
    return {"shop": shop, "charts": base["charts"], "products": products, "zones": base["zones"]}


def _estimate_note(stock_estimate: int, what: str) -> str:
    return (f"Stock counts are estimates: {stock_estimate} per {what} the store shows as available, "
            "0 when it shows it as sold out.")


# --- Shopify ---------------------------------------------------------------------------------
def to_seed(products: list[dict], source: str, stock_estimate: int = DEFAULT_STOCK_ESTIMATE,
            shop_name: str | None = None, base_path: Path = SEED_PATH,
            egp_per_unit: float = 1.0) -> dict:
    """A seed from a Shopify store's /products.json."""
    charts = json.loads(Path(base_path).read_text(encoding="utf-8"))["charts"]
    items, types = [], Counter()
    for product in products:
        item = _product(product, "", stock_estimate, charts, egp_per_unit)
        if item is not None:
            items.append({k: v for k, v in item.items() if k not in ("id", "chart", "pairs_with")})
            if (product.get("product_type") or "").strip():
                types[product["product_type"].strip().lower()] += 1
    return _assemble(items, types, source, _estimate_note(stock_estimate, "size"), shop_name, base_path)


# --- WooCommerce -----------------------------------------------------------------------------
def fetch_woocommerce(store_url: str, get=httpx.get, max_pages: int = 5, delay_s: float = 0.5) -> list[dict]:
    """Products from a WooCommerce store's public Store API (no key needed)."""
    base = store_url.rstrip("/")
    products: list[dict] = []
    for page in range(1, max_pages + 1):
        if page > 1:
            time.sleep(delay_s)
        r = get(f"{base}/wp-json/wc/store/v1/products", params={"per_page": 100, "page": page},
                headers={"User-Agent": USER_AGENT}, timeout=20)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        products.extend(batch)
        if len(products) >= 2 * MAX_PRODUCTS:
            break
    return products


def seed_from_woocommerce(products: list[dict], source: str, stock_estimate: int = DEFAULT_STOCK_ESTIMATE,
                          shop_name: str | None = None, base_path: Path = SEED_PATH,
                          egp_per_unit: float = 1.0) -> dict:
    """A seed from a WooCommerce store. Its public API says only whether a whole product is in
    stock, so every size of an in-stock product gets the estimate."""
    items, types = [], Counter()
    for p in products:
        prices = p.get("prices") or {}
        price = int(prices.get("price") or 0) / 10 ** int(prices.get("currency_minor_unit") or 0)
        if price <= 0:
            continue
        attrs = {a.get("name", ""): [t.get("name", "") for t in a.get("terms") or []]
                 for a in p.get("attributes") or []}
        colors = next((v for k, v in attrs.items() if _COLOR_OPTION.search(k)), [])
        sizes = next((v for k, v in attrs.items() if _SIZE_OPTION.search(k)), [])
        sizes = [s.strip().upper() for s in sizes if s.strip()] or ["ONE"]
        n = stock_estimate if p.get("is_in_stock", True) else 0
        kind = ((p.get("categories") or [{}])[0].get("name") or "").strip()
        title = str(p.get("name") or "").strip()
        items.append({"name_ar": title, "name_en": _named(title, kind),
                      "category": _category({"product_type": kind, "title": title}),
                      "price": int(math.floor(price * egp_per_unit + 0.5)),
                      "colors": [c for c in colors if c] or ["standard"],
                      "stock": {("ONE" if s in _ONE_SIZE else s): n for s in sizes}})
        if kind:
            types[kind.lower()] += 1
    return _assemble(items, types, source, _estimate_note(stock_estimate, "product"), shop_name, base_path)


# --- Spreadsheets: CSV, Excel, Google Sheets ---------------------------------------------------
_COLUMNS = {
    "name": ("name", "product", "product name", "item", "title", "الاسم", "اسم المنتج", "المنتج"),
    "price": ("price", "السعر", "سعر"),
    "color": ("color", "colour", "اللون", "لون"),
    "size": ("size", "المقاس", "مقاس"),
    "stock": ("stock", "qty", "quantity", "المخزون", "الكمية", "العدد", "الكميه"),
    "category": ("category", "type", "القسم", "النوع", "الفئة"),
}


def sheet_csv_url(url: str) -> str:
    """A Google Sheets link (shared as 'anyone with the link') as its CSV export."""
    sheet = re.search(r"/spreadsheets/d/([\w-]+)", url)
    gid = re.search(r"gid=(\d+)", url)
    return (f"https://docs.google.com/spreadsheets/d/{sheet.group(1)}/export?format=csv"
            f"&gid={gid.group(1) if gid else 0}")


def _sheet_rows(source: str | Path, get=httpx.get) -> list[list]:
    text = str(source)
    if "docs.google.com/spreadsheets" in text:
        r = get(sheet_csv_url(text), headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True)
        r.raise_for_status()
        return list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    path = Path(source)
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        import openpyxl
        ws = openpyxl.load_workbook(path, read_only=True, data_only=True).active
        return [list(r) for r in ws.iter_rows(values_only=True)]
    return list(csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig"))))


def seed_from_sheet(source: str | Path, shop_name: str | None = None, base_path: Path = SEED_PATH,
                    get=httpx.get) -> dict:
    """A seed from the shop's own stock sheet: one row per product, colour and size, with real
    counts. Headers in English or Arabic (name/الاسم, price/السعر, color/اللون, size/المقاس,
    stock/الكمية, optional category/القسم)."""
    rows = [r for r in _sheet_rows(source, get) if any(str(c or "").strip() for c in r)]
    if not rows:
        raise ValueError("the sheet is empty")
    header = [str(c or "").strip().lower() for c in rows[0]]
    col = {key: next((i for i, h in enumerate(header) if h in names), None) for key, names in _COLUMNS.items()}
    if col["name"] is None or col["price"] is None:
        raise ValueError("the sheet needs a name column (name / الاسم) and a price column (price / السعر); "
                         f"found: {', '.join(h for h in header if h)}")

    def cell(row, key):
        i = col[key]
        return str(row[i]).strip() if i is not None and i < len(row) and row[i] is not None else ""

    products: dict[str, dict] = {}
    for row in rows[1:]:
        name = cell(row, "name")
        price = to_number(cell(row, "price"))
        if not name or price is None or price <= 0:
            continue
        kind = cell(row, "category")
        p = products.setdefault(name, {"name_ar": name, "name_en": name, "price": int(price),
                                       "category": _category({"product_type": kind, "title": name}),
                                       "colors": [], "stock": {}})
        p["price"] = min(p["price"], int(price))
        color = cell(row, "color")
        if color and color not in p["colors"]:
            p["colors"].append(color)
        size = clean_digits(cell(row, "size")).upper() or "ONE"
        size = "ONE" if size in _ONE_SIZE else size
        count = to_number(cell(row, "stock")) if col["stock"] is not None else DEFAULT_STOCK_ESTIMATE
        p["stock"][size] = p["stock"].get(size, 0) + max(int(count or 0), 0)
        p.setdefault("_kind", kind)
    types = Counter(p.pop("_kind").lower() for p in products.values() if p.get("_kind"))
    items = [{**p, "colors": p["colors"] or ["standard"]} for p in products.values()]
    label = Path(str(source)).name if "docs.google.com" not in str(source) else "Google Sheet"
    note = "Stock counts come from the shop's own sheet." if col["stock"] is not None else \
        _estimate_note(DEFAULT_STOCK_ESTIMATE, "row")
    return _assemble(items, types, label, note, shop_name, base_path)


# --- one command ----------------------------------------------------------------------------
def detect_source(source: str, get=httpx.get) -> str:
    """'sheet' for a file or a Google Sheet; for a website, 'shopify' or 'woocommerce'."""
    if "docs.google.com/spreadsheets" in source or not source.startswith(("http://", "https://")):
        return "sheet"
    base = source.rstrip("/")
    try:
        r = get(f"{base}/products.json", params={"limit": 1}, headers={"User-Agent": USER_AGENT}, timeout=20)
        if r.status_code == 200 and isinstance(r.json(), dict) and "products" in r.json():
            return "shopify"
    except Exception:
        pass
    try:
        r = get(f"{base}/wp-json/wc/store/v1/products", params={"per_page": 1},
                headers={"User-Agent": USER_AGENT}, timeout=20)
        if r.status_code == 200 and isinstance(r.json(), list):
            return "woocommerce"
    except Exception:
        pass
    raise ValueError(f"no Shopify or WooCommerce catalog found at {source}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="a store's address (Shopify or WooCommerce), a Google Sheets link, "
                                   "or a .csv / .xlsx file")
    ap.add_argument("--out", type=Path, default=Path("data/imported-shop.json"))
    ap.add_argument("--stock", type=int, default=DEFAULT_STOCK_ESTIMATE,
                    help="estimated count for what a store shows as available (stores only)")
    ap.add_argument("--name", help="shop name the agent uses (default: Hodoom)")
    ap.add_argument("--egp-per-unit", type=float, default=1.0,
                    help="for a store priced in another currency: EGP per unit of its prices")
    args = ap.parse_args(argv)
    kind = detect_source(args.source)
    if kind == "sheet":
        seed = seed_from_sheet(args.source, args.name)
    elif kind == "shopify":
        seed = to_seed(fetch_products(args.source), args.source, args.stock, args.name,
                       egp_per_unit=args.egp_per_unit)
    else:
        seed = seed_from_woocommerce(fetch_woocommerce(args.source), args.source, args.stock, args.name,
                                     egp_per_unit=args.egp_per_unit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(seed, ensure_ascii=False, indent=1), encoding="utf-8")
    sold_out = sum(1 for p in seed["products"] for n in p["stock"].values() if n == 0)
    print(f"{kind}: {len(seed['products'])} products, {sold_out} sold-out sizes -> {args.out}")
    print(f"Run the shop on it:  MODERATOR_SEED={args.out} uv run uvicorn --factory moderator.server:create_app")


if __name__ == "__main__":
    main()
