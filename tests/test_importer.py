import json

from moderator.store.catalog import SEED_PATH, Catalog
from moderator.store.importer import fetch_products, to_seed

# The shape of a Shopify store's public /products.json (trimmed to the fields we read).
SHOP = [
    {"title": "Oversized Hoodie", "product_type": "Hoodies", "tags": ["winter"],
     "options": [{"name": "Color", "position": 1}, {"name": "Size", "position": 2}],
     "variants": [
         {"option1": "Black", "option2": "M", "price": "1250.00", "available": True},
         {"option1": "Black", "option2": "L", "price": "1250.00", "available": False},
         {"option1": "Olive", "option2": "L", "price": "1300.00", "available": True},
         {"option1": "Olive", "option2": "XL", "price": "1300.00", "available": False}]},
    {"title": "Wide Leg Jeans", "product_type": "", "tags": ["denim", "pants"],
     "options": [{"name": "Size", "position": 1}, {"name": "اللون", "position": 2}],
     "variants": [
         {"option1": "32", "option2": "أزرق", "price": "990", "available": True},
         {"option1": "34", "option2": "أزرق", "price": "990", "available": True}]},
    {"title": "Canvas Tote Bag", "product_type": "Bags", "tags": [],
     "options": [{"name": "Title", "position": 1}],
     "variants": [{"option1": "Default Title", "price": "450.50", "available": True}]},
    {"title": "Gift Card", "product_type": "Gift Card", "tags": [],
     "options": [{"name": "Denominations", "position": 1}],
     "variants": [{"option1": "500", "price": "0.00", "available": True}]},
]


def test_store_products_become_shop_products_with_estimated_stock():
    seed = to_seed(SHOP, source="https://example-store.test", stock_estimate=7)
    hoodie, jeans, tote = seed["products"]
    assert hoodie["name_en"] == "Oversized Hoodie" and hoodie["category"] == "outerwear"
    assert hoodie["price"] == 1250 and hoodie["colors"] == ["Black", "Olive"]
    assert hoodie["stock"] == {"M": 7, "L": 7, "XL": 0}  # a size is in stock if any colour is
    assert hoodie["chart"] == "letters"
    assert jeans["category"] == "bottoms" and jeans["chart"] == "waist"
    assert jeans["colors"] == ["أزرق"] and jeans["stock"] == {"32": 7, "34": 7}
    assert tote["category"] == "accessories" and tote["stock"] == {"ONE": 7}
    assert tote["chart"] == "one" and tote["price"] == 451
    assert [p["id"] for p in seed["products"]] == ["P001", "P002", "P003"]  # the free gift card is skipped


def test_imported_seed_keeps_our_zones_and_says_stock_is_estimated():
    seed = to_seed(SHOP, source="https://example-store.test", stock_estimate=7)
    ours = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    assert seed["zones"] == ours["zones"] and seed["charts"] == ours["charts"]
    assert seed["shop"]["catalog_source"] == "https://example-store.test"
    assert "estimate" in seed["shop"]["stock_note"]


def test_imported_seed_loads_into_the_shop_database(tmp_path):
    path = tmp_path / "shop.json"
    path.write_text(json.dumps(to_seed(SHOP, source="s"), ensure_ascii=False), encoding="utf-8")
    cat = Catalog.load(path)
    assert cat.get("P001").available_sizes() == ["M", "L"]
    assert cat.search("hoodie")[0].id == "P001"
    assert cat.recommend_size("P002", 178, 80)["size"] in ("32", "34", "36")


def test_fetch_reads_every_page_until_an_empty_one():
    calls = []

    def get(url, params, headers, timeout):
        calls.append(params["page"])
        page = {1: SHOP[:2], 2: SHOP[2:]}.get(params["page"], [])

        class R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"products": page}
        return R()

    assert len(fetch_products("https://example-store.test/", get=get)) == 4
    assert calls == [1, 2, 3]


def test_session_runs_on_an_imported_catalog(monkeypatch, tmp_path):
    from moderator.session import Session
    from tests.fakes import ScriptedProvider

    path = tmp_path / "shop.json"
    path.write_text(json.dumps(to_seed(SHOP, source="https://example-store.test"), ensure_ascii=False),
                    encoding="utf-8")
    monkeypatch.setenv("MODERATOR_SEED", str(path))
    s = Session(ScriptedProvider([]))
    assert s.catalog.get("P001").name_en == "Oversized Hoodie" and s.catalog.get("T01") is None
    for preset in range(5):  # website-order presets fall back to the imported shop's in-stock items
        _, order_id, _ = s.checkout(preset)
        for item in s.book.get(order_id).items:
            assert s.catalog.get(item["product_id"]).stock[item["size"]] > 0


def test_inventory_says_where_an_imported_catalog_came_from(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from moderator.server import create_app
    from tests.fakes import ScriptedProvider

    path = tmp_path / "shop.json"
    path.write_text(json.dumps(to_seed(SHOP, source="https://example-store.test"), ensure_ascii=False),
                    encoding="utf-8")
    monkeypatch.setenv("MODERATOR_SEED", str(path))
    c = TestClient(create_app(provider_factory=lambda: ScriptedProvider([]), mode="live"))
    inv = c.get("/api/inventory").json()
    assert inv["catalog_source"] == "https://example-store.test" and "estimate" in inv["stock_note"]
    assert "catalog_source" in c.get("/static/app.js").text


SHOES = {"title": "Canvas Runner", "product_type": "Shoes", "tags": [],
         "options": [{"name": "Size", "position": 1}],
         "variants": [{"option1": "41", "price": "100.00", "available": True},
                      {"option1": "42", "price": "100.00", "available": False}]}


def test_shoes_get_a_category_and_no_made_up_size(tmp_path):
    seed = to_seed([SHOES], source="s")
    shoe = seed["products"][0]
    assert shoe["category"] == "accessories" and shoe["chart"] == "one"
    path = tmp_path / "shop.json"
    path.write_text(json.dumps(seed, ensure_ascii=False), encoding="utf-8")
    rec = Catalog.load(path).recommend_size("P001", 178, 80)
    assert rec["size"] is None and rec["available"] == ["41"] and "usual size" in rec["note"]


def test_prices_in_another_currency_are_converted_to_egp():
    assert to_seed([SHOES], source="s", egp_per_unit=50)["products"][0]["price"] == 5000


def test_imported_shop_describes_what_it_sells_and_the_prompt_uses_it(tmp_path):
    from datetime import datetime

    from moderator.agent.prompt import build_system_prompt

    seed = to_seed(SHOP + [SHOES], source="s")
    assert seed["shop"]["description"] == "a shop selling hoodies, bags and shoes"
    path = tmp_path / "shop.json"
    path.write_text(json.dumps(seed, ensure_ascii=False), encoding="utf-8")
    now = datetime(2026, 10, 8, 12)
    assert "a shop selling hoodies, bags and shoes in" in build_system_prompt(Catalog.load(path), now)
    assert "a casual-wear brand in" in build_system_prompt(Catalog.load(), now)  # Hodoom unchanged


def test_arabic_words_find_english_named_products(tmp_path):
    seed = to_seed(SHOP + [SHOES], source="s")
    assert seed["products"][3]["name_en"] == "Canvas Runner (Shoes)"  # the type, when the title lacks it
    assert seed["products"][0]["name_en"] == "Oversized Hoodie"
    path = tmp_path / "shop.json"
    path.write_text(json.dumps(seed, ensure_ascii=False), encoding="utf-8")
    cat = Catalog.load(path)
    assert [p.id for p in cat.search("عندكم شوزات؟")] == ["P004"]
    assert cat.search("هودي")[0].id == "P001" and cat.search("جينز")[0].id == "P002"
    assert cat.search("shoz")[0].id == "P004"


def test_english_retry_matches_whole_words_and_puts_in_stock_first(tmp_path):
    def shoe(title, price, available):
        return {"title": title, "product_type": "Shoes", "tags": [],
                "options": [{"name": "Size", "position": 1}],
                "variants": [{"option1": "10", "price": str(price), "available": available}]}

    seed = to_seed([shoe("Women's Runner", 80, True), shoe("Men's Runner", 90, False),
                    shoe("Men's Cruiser", 120, True)], source="s")
    path = tmp_path / "shop.json"
    path.write_text(json.dumps(seed, ensure_ascii=False), encoding="utf-8")
    found = Catalog.load(path).search("شوزات رجالي")
    assert [p.name_en for p in found][:2] == ["Men's Cruiser (Shoes)", "Men's Runner (Shoes)"]


# --- spreadsheets (CSV, Excel, Google Sheets) -----------------------------------------
SHEET_CSV = """الاسم,السعر,اللون,المقاس,الكمية,القسم
هودي قطن,850,أسود,M,4,هوديز
هودي قطن,850,أسود,L,0,هوديز
هودي قطن,850,رمادي,L,3,هوديز
بنطلون جينز,700,أزرق,32,6,بنطلونات
شنطة كانفاس,300,بيج,,9,شنط
"""


def test_a_shop_sheet_imports_with_its_real_stock_counts(tmp_path):
    from moderator.store.importer import seed_from_sheet
    path = tmp_path / "stock.csv"
    path.write_text(SHEET_CSV, encoding="utf-8")
    seed = seed_from_sheet(path)
    hoodie, jeans, bag = seed["products"]
    assert hoodie["name_ar"] == "هودي قطن" and hoodie["price"] == 850
    assert hoodie["colors"] == ["أسود", "رمادي"] and hoodie["stock"] == {"M": 4, "L": 3}  # summed over colours
    assert hoodie["chart"] == "letters" and jeans["chart"] == "waist" and jeans["category"] == "bottoms"
    assert bag["stock"] == {"ONE": 9} and bag["category"] == "accessories"
    assert "sheet" in seed["shop"]["stock_note"] and "estimate" not in seed["shop"]["stock_note"]


def test_an_excel_sheet_with_english_headers_imports_too(tmp_path):
    import openpyxl

    from moderator.store.importer import seed_from_sheet
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Product", "Price", "Colour", "Size", "Stock"])
    ws.append(["Linen Shirt", 640, "White", "S", 2])
    ws.append(["Linen Shirt", 640, "White", "M", 5])
    path = tmp_path / "stock.xlsx"
    wb.save(path)
    (shirt,) = seed_from_sheet(path)["products"]
    assert shirt["stock"] == {"S": 2, "M": 5} and shirt["colors"] == ["White"] and shirt["price"] == 640


def test_a_sheet_without_the_needed_columns_is_explained(tmp_path):
    import pytest

    from moderator.store.importer import seed_from_sheet
    path = tmp_path / "x.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="name.*price"):
        seed_from_sheet(path)


def test_google_sheet_links_become_csv_exports():
    from moderator.store.importer import sheet_csv_url
    assert sheet_csv_url("https://docs.google.com/spreadsheets/d/ABC123/edit#gid=77") == \
        "https://docs.google.com/spreadsheets/d/ABC123/export?format=csv&gid=77"
    assert sheet_csv_url("https://docs.google.com/spreadsheets/d/ABC123/edit") == \
        "https://docs.google.com/spreadsheets/d/ABC123/export?format=csv&gid=0"


# --- WooCommerce -----------------------------------------------------------------------
WOO = [
    {"name": "Cargo Pants", "prices": {"price": "79000", "currency_minor_unit": 2},
     "is_in_stock": True, "categories": [{"name": "Pants"}],
     "attributes": [{"name": "Size", "terms": [{"name": "30"}, {"name": "32"}]},
                    {"name": "Color", "terms": [{"name": "Khaki"}, {"name": "Black"}]}]},
    {"name": "Basic Tee", "prices": {"price": "350", "currency_minor_unit": 0},
     "is_in_stock": False, "categories": [{"name": "T-Shirts"}],
     "attributes": [{"name": "المقاس", "terms": [{"name": "M"}, {"name": "L"}]}]},
]


def test_woocommerce_products_become_shop_products():
    from moderator.store.importer import seed_from_woocommerce
    seed = seed_from_woocommerce(WOO, source="https://woo.test", stock_estimate=5)
    cargo, tee = seed["products"]
    assert cargo["price"] == 790 and cargo["colors"] == ["Khaki", "Black"] and cargo["category"] == "bottoms"
    assert cargo["stock"] == {"30": 5, "32": 5} and cargo["chart"] == "waist"
    assert tee["stock"] == {"M": 0, "L": 0} and tee["colors"] == ["standard"]  # sold out
    assert "estimate" in seed["shop"]["stock_note"]


def test_the_source_is_detected_from_the_argument(tmp_path):
    from moderator.store.importer import detect_source

    class R:
        def __init__(self, code, body):
            self.status_code, self._body = code, body

        def json(self):
            return self._body

    def woo_only(url, **kw):
        return R(200, [WOO[0]]) if "wc/store" in url else R(404, {})

    assert detect_source(str(tmp_path / "s.csv")) == "sheet"
    assert detect_source("https://docs.google.com/spreadsheets/d/X/edit") == "sheet"
    assert detect_source("https://shop.test", get=lambda url, **kw: R(200, {"products": []})) == "shopify"
    assert detect_source("https://shop.test", get=woo_only) == "woocommerce"
