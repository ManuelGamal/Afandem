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


def test_franco_and_english_item_words_find_the_right_products():
    cat = Catalog.load()
    tees = {"T01", "T02", "T08"}
    for q in ("tshirt", "t-shirt", "tishirt", "tee", "تيشيرت"):
        found = {p.id for p in cat.search(q)}
        assert tees <= found and "T07" not in found, (q, found)  # a sweatshirt is not a t-shirt
    black_bottoms = {p.id for p in cat.search("pantalonat eswed")}
    assert {"B07", "B05"} <= black_bottoms, black_bottoms


def test_search_lists_matching_items_before_colour_only_matches():
    cat = Catalog.load()
    first = cat.search("بنطلون أسود")[0]
    assert first.category == "bottoms" and "أسود" in first.colors


def test_arabic_words_with_the_definite_article_still_match():
    cat = Catalog.load()
    assert cat.search("الهودي")[0].id == "T06"


def test_a_wrong_category_guess_does_not_hide_the_product():
    """Shops file items differently (is a hoodie a top or outerwear?); a category that matches
    nothing must not hide the product the customer named."""
    cat = Catalog.load()
    assert cat.search("هودي تقيل", category="outerwear")[0].id == "T06"
    assert all(p.category == "bottoms" for p in cat.search("أسود", category="bottoms"))  # still narrows when it can


def test_franco_spellings_of_areas_find_their_zone():
    cat = Catalog.load()
    cases = {"madinet nasr": "cairo", "le el tagamo3 el 5ames": "cairo", "masr el gedida": "cairo",
             "shobra": "cairo", "mohandseen": "giza", "el agouza": "giza", "6th of october": "giza",
             "sheikh zayed": "giza", "eskendereya": "alex", "sidi bishr": "alex",
             "esma3eleya": "canal", "beni suef": "upper", "العجوزة": "giza"}
    for text, zone in cases.items():
        found = cat.find_zone(text)
        assert found is not None and found.id == zone, (text, found and found.id)


def test_a_category_guess_never_beats_a_better_match_elsewhere():
    cat = Catalog.load()
    assert cat.search("hoodie اسود", category="outerwear")[0].id == "T06"
