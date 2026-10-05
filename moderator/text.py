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
    "aiwa", "ah", "akid", "akeed",
}
_BLOCK = {
    "بس", "لا", "مش", "غير", "غيري", "بدل", "ولا", "لسه", "استني",
    "no", "not", "but", "change", "la", "la2", "msh", "mesh", "bas", "wait",
}
_YES_EMOJI = {"👍", "👌", "✅"}


def is_explicit_yes(message: str) -> bool:
    """A short, unconditional yes. Anything with a change or a negation is not a yes."""
    if message.strip() in _YES_EMOJI:
        return True
    words = fold_text(message).split()
    if not words or len(words) > 6:
        return False
    if any(w in _BLOCK for w in words):
        return False
    return any(w in _YES for w in words)


_MONEY = re.compile(
    r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*"
    r"(?:ج\.م|جنيهات|جنيه|جنية|ج(?![\u0600-\u06ff])|egp|l\.e|le\b|pounds?)",
    re.I,
)


def money_mentions(text: str) -> list[Decimal]:
    s = clean_digits(text)
    return [Decimal(m.group(1).replace(",", "")) for m in _MONEY.finditer(s)]


_LATIN = re.compile(r"[A-Za-z]")
_ARABIC = re.compile(r"[\u0621-\u064a]")


def is_latin_script(text: str) -> bool:
    """True when a message is written mainly in Latin letters (Arabizi or English)."""
    latin = len(_LATIN.findall(text))
    return latin >= 3 and latin > 2 * len(_ARABIC.findall(text))
