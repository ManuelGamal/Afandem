"""Text normalizers for Egyptian Arabic, Arabizi and mixed input.

fold_text / norm_phone / to_number are adapted from the author's amin repo
(amin/scoring/normalizers.py, MIT).
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
# zero-width chars, LRM/RLM, bidi embeddings/isolates, BOM, tatweel
_INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff\u0640]")
_DIACRITICS = re.compile("[\u064b-\u0652\u0670]")
_PUNCT = re.compile(r"[^\w\s]")


def clean_digits(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    return _INVISIBLE.sub("", s).translate(_DIGITS).replace("٬", ",").replace("٫", ".")


def fold_text(s: Any) -> str:
    s = _DIACRITICS.sub("", clean_digits(str(s)))
    s = re.sub("[أإآٱ]", "ا", s).replace("ى", "ي").replace("ة", "ه")
    s = _PUNCT.sub(" ", s.lower())
    return " ".join(s.split())


_CURRENCY_WORDS = re.compile(r"(egp|l\.e\.?|جنيهات|جنيه|جنية|ج\.م|pounds?)", re.I)


def to_number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        n = Decimal(str(value))
        return n if n.is_finite() else None
    if not isinstance(value, str):
        return None
    s = clean_digits(value).replace(",", "").lower()
    s = _CURRENCY_WORDS.sub(" ", s).strip()
    try:
        n = Decimal(s)
    except InvalidOperation:
        return None
    return n if n.is_finite() else None


def norm_phone(value: Any) -> str | None:
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        return None
    digits = re.sub(r"\D", "", clean_digits(value))
    if digits.startswith("0020"):
        digits = "0" + digits[4:]
    elif digits.startswith("20") and len(digits) == 12:
        digits = "0" + digits[2:]
    elif len(digits) == 10 and digits.startswith("1"):
        digits = "0" + digits
    return digits or None


_EG_MOBILE = re.compile(r"^01[0125]\d{8}$")


def is_valid_eg_mobile(value: Any) -> bool:
    phone = norm_phone(value)
    return bool(phone and _EG_MOBILE.match(phone))


# Words are in fold_text form.
_YES = {
    "تمام", "ماشي", "اه", "ايوه", "ايوا", "اكيد", "موافق", "اوكي", "اوك", "طبعا", "تم", "يب",
    "ok", "okay", "okk", "yes", "yep", "sure", "tmam", "tamam", "mashy", "mashi", "aywa",
    "aiwa", "ah", "aah", "akid", "akeed",
    # "confirm it" / "it's right" / "go ahead", Arabic and Arabizi
    "اكد", "اكده", "اكدي", "اكديه", "مظبوط", "مضبوط", "صح", "يلا", "يالا",
    "a2ked", "a2kd", "akked", "akkid", "2aked", "a2kedo", "mazboot", "mazbout", "mazbut",
    "sa7", "yalla", "yala", "confirm", "confirmed", "go",
}
_BLOCK = {
    "بس", "لا", "مش", "غير", "غيري", "بدل", "ولا", "لسه", "استني",
    "no", "not", "but", "change", "la", "la2", "msh", "mesh", "bas", "wait",
}
_YES_EMOJI = {"👍", "👌", "✅"}


# Prefixes (fold_text form) of confirm-words, so اكدوه / تأكدي / ayooh / mazbota count too.
_YES_STEMS = ("اكد", "تاكد", "ايو", "مظبوط", "مضبوط",
              "a2ked", "a2kd", "aked", "akked", "akkid", "2aked", "t2ak", "mazbo", "mazbu",
              "aywa", "ayoo", "aiwa", "confirm")


# A yes that also asks for a change is not a yes: the change is made and shown again first.
# Matched inside words (fold_text form), so خليه / تخليه / 5aleeh / a8ayar all count.
_CHANGE_PARTS = ("خلي", "غير", "عدل", "بدل", "زود", "نقص", "شيل", "ضيف",
                 "5ali", "5ale", "5aly", "khali", "khale", "ghay", "8ay", "3adel", "badel",
                 "zawed", "change", "make", "switch", "instead", "edit")
_SIZE_WORDS = {"s", "m", "l", "xl", "xxl", "لارج", "ميديم", "سمول", "اكس", "اكسترا",
               "30", "32", "34", "36", "38"}
_SEGMENT = re.compile(r"[^.!?؟…\n]+[.!?؟…\n]*")


def _asks_for_change(words: list[str], keep: set[str]) -> bool:
    """A change word, or a size other than the order's own (repeating its size is not a change)."""
    return any((w in _SIZE_WORDS and w not in keep) or any(part in w for part in _CHANGE_PARTS)
               for w in words)


def is_explicit_yes(message: str, order_sizes=()) -> bool:
    """A short, unconditional yes. A change or a negation is not a yes, and neither is a
    question; a clear yes may be followed by an unrelated question ("confirm it! when does
    it arrive?")."""
    if message.strip() in _YES_EMOJI:
        return True
    said: list[str] = []
    asked: list[str] = []
    for segment in _SEGMENT.findall(message):
        is_question = "?" in segment or "؟" in segment
        (asked if is_question else said).extend(fold_text(segment).split())
    if not said or len(said) > 25:
        return False
    if any(w in _BLOCK for w in said + asked) or _asks_for_change(said + asked, {fold_text(z) for z in order_sizes}):
        return False
    return any(w in _YES or w.startswith(_YES_STEMS) for w in said)


_MONEY = re.compile(
    r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*"
    r"(?:ج\.م|جنيهات|جنيه|جنية|ج(?![\u0600-\u06ff])|egp|l\.e|le\b|pounds?|"
    r"g[ei]?n[eia]{0,3}h\b)",  # Franco spellings of جنيه (geneh, gneh, genih…)
    re.I,
)


def money_mentions(text: str) -> list[Decimal]:
    s = clean_digits(text)
    return [Decimal(m.group(1).replace(",", "")) for m in _MONEY.finditer(s)]


_LATIN = re.compile(r"[A-Za-z]")
_ARABIC = re.compile(r"[\u0621-\u064a]")


_ENGLISH_WORDS = {"the", "what", "do", "does", "you", "have", "is", "are", "am", "good", "please",
                  "how", "much", "which", "can", "with", "and", "for", "it", "my", "this", "that",
                  "want", "need", "thanks", "thank", "sizes", "deliver", "colors", "colours", "price"}
_FRANCO_WORDS = {"ana", "enta", "enty", "3ayez", "3ayza", "fe", "fi", "fih", "mesh", "msh", "ezay", "kam",
                 "bkam", "bekam", "tamam", "aywa", "la2", "eh", "ya", "w", "we", "el", "momken", "keda",
                 "leh", "feen", "emta", "3andak", "3andena", "3andoko", "da", "di", "ba2a", "le", "lel"}
_WORD = re.compile("[a-z0-9']+")


def has_franco(text: str) -> bool:
    """Franco markers: Franco words, or digits used as letters (3ayez, 7elw, ta7t)."""
    return any(w in _FRANCO_WORDS or (any(c.isdigit() for c in w) and any(c.isalpha() for c in w))
               for w in _WORD.findall(text.lower()))


def looks_english(text: str) -> bool:
    """An English message rather than Franco: English function words and no Franco markers
    (Franco words, or digits used as letters as in 3ayez / 7elw)."""
    words = _WORD.findall(text.lower())
    return not has_franco(text) and sum(w in _ENGLISH_WORDS or w == "i" for w in words) >= 2


def is_latin_script(text: str) -> bool:
    """True when a message is written mainly in Latin letters (Arabizi or English)."""
    latin = len(_LATIN.findall(text))
    return latin >= 3 and latin > 2 * len(_ARABIC.findall(text))
