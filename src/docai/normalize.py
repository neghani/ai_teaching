"""Deterministic normalization of field values found in text or returned by a model.

Every finder returns a list of *candidate groups*: one group per occurrence in the text,
holding every canonical reading of that occurrence. An unambiguous occurrence has one
reading; "03/04/2025" has two.
"""

from __future__ import annotations

import re
from datetime import date

from docai.schema import FieldType

Candidates = list[frozenset[str]]

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_NUMBER_WORD = "|".join(sorted([*_UNITS, *_TENS, "hundred"], key=len, reverse=True))


def words_to_int(text: str) -> int | None:
    tokens = re.split(r"[\s-]+", text.lower().replace(" and ", " ").strip())
    if not tokens or tokens == [""]:
        return None
    total, current = 0, 0
    for tok in tokens:
        if tok in _UNITS:
            current += _UNITS[tok]
        elif tok in _TENS:
            current += _TENS[tok]
        elif tok == "hundred":
            current = max(current, 1) * 100
        else:
            return None
    return total + current


# ---------- durations ----------

_DIGIT_PAREN = r"\((\d{1,4})\)"
_WORDS = rf"((?:(?:{_NUMBER_WORD})[\s-]?)+)"


def _find_duration(text: str, units: dict[str, int]) -> Candidates:
    unit_re = "|".join(units)
    patterns = [
        rf"{_DIGIT_PAREN}\s*({unit_re})\b",
        rf"(?<![\w(])(\d{{1,4}})[\s-]*({unit_re})\b",
        rf"\b{_WORDS}\s+({unit_re})\b",
    ]
    hits: list[tuple[int, int]] = []
    for pat in patterns:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            raw, unit = m.group(1), m.group(2).lower()
            n = int(raw) if raw.isdigit() else words_to_int(raw)
            if n is None:
                continue
            hits.append((m.start(), n * units[unit]))
    hits.sort()
    return [frozenset({str(v)}) for _, v in hits]


def find_months(text: str) -> Candidates:
    # Plural only: "twelve (12) month periods" describes renewal periods, not the term.
    return _find_duration(text, {"months": 1, "years": 12})


def find_days(text: str) -> Candidates:
    return _find_duration(text, {"days": 1, "business days": 1})


# ---------- dates ----------

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9,
    "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))


def _iso(y: int, m: int, d: int) -> str | None:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def find_dates(text: str) -> Candidates:
    hits: list[tuple[int, frozenset[str]]] = []

    for m in re.finditer(rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", text, re.I):
        if iso := _iso(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2))):
            hits.append((m.start(), frozenset({iso})))

    for m in re.finditer(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_RE})\.?,?\s+(\d{{4}})\b", text, re.I):
        if iso := _iso(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1))):
            hits.append((m.start(), frozenset({iso})))

    for m in re.finditer(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text):
        if iso := _iso(int(m.group(1)), int(m.group(2)), int(m.group(3))):
            hits.append((m.start(), frozenset({iso})))

    for m in re.finditer(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b", text):
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        readings = {r for r in (_iso(y, a, b), _iso(y, b, a)) if r}
        if readings:
            hits.append((m.start(), frozenset(readings)))

    hits.sort(key=lambda h: h[0])
    return [g for _, g in hits]


# ---------- money ----------

_AMOUNT = r"(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)"
_CURRENCY_CODES = {"USD": "USD", "US$": "USD", "$": "USD", "EUR": "EUR", "GBP": "GBP", "£": "GBP", "€": "EUR"}


def _money(currency: str, amount: str) -> str:
    return f"{_CURRENCY_CODES[currency.upper() if currency.isalpha() else currency]} {float(amount.replace(',', '')):.2f}"


def find_money(text: str) -> Candidates:
    hits: list[tuple[int, int, str]] = []
    for m in re.finditer(rf"(US\$|USD|EUR|GBP|\$|£|€)\s?{_AMOUNT}", text, re.I):
        hits.append((m.start(), m.end(), _money(m.group(1), m.group(2))))
    for m in re.finditer(rf"{_AMOUNT}\s?(USD|EUR|GBP)\b", text, re.I):
        hits.append((m.start(), m.end(), _money(m.group(2), m.group(1))))
    hits.sort()
    result: Candidates = []
    last_end = -1
    for start, end, value in hits:
        if start < last_end:
            continue
        result.append(frozenset({value}))
        last_end = end
    return result


# ---------- booleans ----------

_AUTO_RENEW = re.compile(r"automatic(?:ally)?\s+renew|renew\w*\s+automatically|auto-?renew", re.I)
_NEGATION = re.compile(r"\b(?:not|no|never)\b", re.I)


def find_auto_renewal(text: str) -> Candidates:
    result: Candidates = []
    for sentence in split_sentences(text):
        if _AUTO_RENEW.search(sentence):
            result.append(frozenset({"false" if _NEGATION.search(sentence) else "true"}))
    return result


# ---------- text ----------


def normalize_name(text: str) -> str:
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# ---------- shared helpers ----------


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    return [s for s in re.split(r"(?<=[.;])\s+(?=[A-Z0-9\"(])", text) if s]


FINDERS = {
    FieldType.DATE: find_dates,
    FieldType.MONTHS: find_months,
    FieldType.DAYS: find_days,
    FieldType.MONEY: find_money,
    FieldType.BOOL: find_auto_renewal,
}


def find_candidates(field_type: FieldType, text: str) -> Candidates:
    finder = FINDERS.get(field_type)
    return finder(text) if finder else []


def normalize_value(field_type: FieldType, raw: object) -> str | None:
    """Canonicalize a model-returned value. Returns None if it cannot be parsed."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.lower() in {"null", "none", "n/a", "not found", "not_found"}:
        return None

    if field_type == FieldType.TEXT:
        return normalize_name(text) or None

    if field_type == FieldType.BOOL:
        low = text.lower()
        if low in {"true", "yes", "y", "1"}:
            return "true"
        if low in {"false", "no", "n", "0"}:
            return "false"
        return None

    if field_type in (FieldType.MONTHS, FieldType.DAYS):
        if re.fullmatch(r"\d+(?:\.0+)?", text):
            return str(int(float(text)))
        groups = (find_months if field_type == FieldType.MONTHS else find_days)(text)
        if groups:
            return sorted(groups[0])[0]
        n = words_to_int(text)
        return str(n) if n is not None else None

    if field_type == FieldType.MONEY:
        groups = find_money(text)
        if groups:
            return sorted(groups[0])[0]
        bare = re.fullmatch(_AMOUNT, text)
        # No currency given: assume USD. The verifier still checks it against the quote.
        return _money("USD", bare.group(1)) if bare else None

    if field_type == FieldType.DATE:
        groups = find_dates(text)
        if groups:
            return sorted(groups[0])[0]
        return None

    return None
