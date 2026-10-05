from decimal import Decimal

from moderator.text import (
    fold_text, is_explicit_yes, is_valid_eg_mobile, money_mentions, norm_phone, to_number,
)


def test_fold_text_unifies_letters_and_digits():
    assert fold_text("أيوة يا فندم!") == "ايوه يا فندم"
    assert fold_text("مقاس ٤٢") == "مقاس 42"


def test_norm_phone_formats():
    assert norm_phone("٠١٠١٢٣٤٥٦٧٨") == "01012345678"
    assert norm_phone("+20 101 234 5678") == "01012345678"
    assert norm_phone("00201012345678") == "01012345678"
    assert norm_phone("1012345678") == "01012345678"


def test_valid_egyptian_mobile():
    assert is_valid_eg_mobile("01012345678")
    assert is_valid_eg_mobile("01512345678")
    assert not is_valid_eg_mobile("01312345678")
    assert not is_valid_eg_mobile("0101234567")
    assert not is_valid_eg_mobile("0223456789")


def test_to_number():
    assert to_number("١٧٥") == Decimal("175")
    assert to_number("1,250 جنيه") == Decimal("1250")
    assert to_number("abc") is None


def test_explicit_yes_accepts_short_confirmations():
    for msg in ["تمام", "أيوة", "اه تمام يا فندم", "ok", "tmam", "Aywa", "ماشي", "👍"]:
        assert is_explicit_yes(msg), msg


def test_explicit_yes_rejects_changes_and_negations():
    for msg in ["تمام بس خليه لارج", "لا", "مش دلوقتي", "ok but change the size",
                "تمام هو ده المقاس المظبوط ولا اللي بعده عشان انا مش متأكد خالص", "", "بكام؟"]:
        assert not is_explicit_yes(msg), msg


def test_money_mentions():
    assert money_mentions("الإجمالي ١٬٠١٠ جنيه والشحن 60ج") == [Decimal("1010"), Decimal("60")]
    assert money_mentions("سعره 950 EGP") == [Decimal("950")]
    assert money_mentions("مقاس 42 وطولك 175") == []


def test_is_latin_script():
    from moderator.text import is_latin_script
    assert is_latin_script("elhoodie el khafeef bkam")
    assert is_latin_script("How much is the denim jacket?")
    assert not is_latin_script("الهودي بكام؟")
    assert not is_latin_script("Hi، عايزة ال hoodie لو available")
    assert not is_latin_script("")


def test_explicit_yes_accepts_natural_arabic_and_arabizi_confirmations():
    for msg in ["el mel5as mazboot, a2ked el orḍer w shokran", "أكده لو سمحت", "مظبوط يلا",
                "yes confirm it please", "تمام كده مظبوط اكد الطلب يا فندم"]:
        assert is_explicit_yes(msg), msg
    for msg in ["مش مظبوط", "اكد بس غير المقاس", "la2 mesh 3ayez", "a2ked bas ghayar el size"]:
        assert not is_explicit_yes(msg), msg


def test_explicit_yes_handles_polite_real_confirmations_from_the_bench():
    for msg in ["تمام، كده العنوان مظبوط جداً. يا ريت تأكدي الطلب، وشكراً ليكي!",
                "أيوة يا فندم، أكد الطلب وشكراً جداً على المتابعة!",
                "Ayooh, aked el talab, el tafaseel kolha mazbota! Shukran gedan :)",
                "aywah a2kedo law sama7t"]:
        assert is_explicit_yes(msg), msg


def test_explicit_yes_rejects_questions_and_conditions():
    for msg in ["ممكن اتأكد من المقاس الأول؟", "تمام يا فندم، بس أنا مسافر ممكن يوصل الحد؟",
                "Ayooh, ya ret t2aked el talab! Bas momken el mandoub ykalemny?",
                "أكد الطلب؟"]:
        assert not is_explicit_yes(msg), msg


def test_explicit_yes_arabizi_variants_from_the_bench():
    assert is_explicit_yes("Aah, ya ret t2aked el talab. Shukran gedan!")
    assert is_explicit_yes("aiwa t2akedo")
    assert not is_explicit_yes("t2aked bas mesh delwa2ty")


def test_explicit_yes_accepts_long_happy_confirmation_with_muakkad():
    assert is_explicit_yes("تمام، شكراً جداً لتفهمكم! كده الطلب تمام ومؤكد يا فندم ومستنياه")
