from moderator.store.catalog import Catalog


def test_load_has_30_products_and_6_zones():
    cat = Catalog.load()
    assert len(cat.products) == 30
    assert len(cat.zones) == 6


def test_search_arabic_arabizi_english():
    cat = Catalog.load()
    assert cat.search("جينز")[0].category == "bottoms"
    assert any(p.id == "T06" for p in cat.search("هودي"))
    assert any(p.id == "O01" for p in cat.search("denim jacket"))
    assert all(p.price <= 400 for p in cat.search("تيشيرت", max_price=400))
    assert cat.search("xyzxyz") == []


def test_recommend_size_exact_and_fit():
    cat = Catalog.load()
    rec = cat.recommend_size("T01", 170, 65)
    assert rec["size"] == "M"
    assert cat.recommend_size("T01", 170, 65, fit="loose")["size"] == "L"
    assert cat.recommend_size("B01", 176, 78)["size"] == "34"


def test_recommend_size_reports_stock():
    cat = Catalog.load()
    rec = cat.recommend_size("T02", 185, 92)  # XL is out of stock for T02
    assert rec["size"] == "XL"
    assert rec["in_stock"] is False
    assert "XL" not in rec["available"]


def test_find_zone_loose_and_unserved():
    cat = Catalog.load()
    assert cat.find_zone("التجمع الخامس شارع التسعين").id == "cairo"
    assert cat.find_zone("٦ أكتوبر الحي السابع").id == "giza"
    assert cat.find_zone("Smouha, Alex").id == "alex"
    assert cat.find_zone("الغردقة") is None
    assert cat.find_zone("الساحل الشمالي") is None
