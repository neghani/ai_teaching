"""Code-based verification of model evidence. No LLM calls."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from docai.normalize import find_candidates, normalize_name, normalize_value, split_sentences
from docai.schema import Document, FieldExtraction, FieldSpec, FieldType

DEFAULT_FUZZY_THRESHOLD = 90.0

INJECTION_RE = re.compile(
    r"ignore (?:all |any )?(?:previous|prior|above) instructions"
    r"|instructions? (?:for|to) (?:ai|automated|language model)"
    r"|system note"
    r"|you must (?:return|report|output)"
    r"|must be (?:returned|reported) as"
    r"|disregard (?:the|all|any|previous)",
    re.I,
)

_QUOTE_CHARS = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-"})


def normalize_for_match(text: str) -> str:
    text = text.replace('\\"', '"').replace("\\'", "'")
    text = re.sub(r"\s+", " ", text.translate(_QUOTE_CHARS)).strip().lower()
    # Models often wrap the quote itself in quotation marks, escape inner quotes, or add ellipses.
    return text.strip("\"'").removeprefix("...").removesuffix("...").strip()


class QuoteMatch(BaseModel):
    method: Literal["exact", "fuzzy", "none"]
    score: float


def match_quote(quote: str, page_text: str, threshold: float) -> QuoteMatch:
    q, p = normalize_for_match(quote), normalize_for_match(page_text)
    if not q:
        return QuoteMatch(method="none", score=0.0)
    if q in p:
        return QuoteMatch(method="exact", score=100.0)
    score = fuzz.partial_ratio(q, p)
    return QuoteMatch(method="fuzzy" if score >= threshold else "none", score=round(score, 1))


def suspected_injections(doc: Document) -> list[tuple[int, str]]:
    return [
        (page.number, sentence)
        for page in doc.pages
        for sentence in split_sentences(page.text)
        if INJECTION_RE.search(sentence)
    ]


def anchored_candidates(doc: Document, spec: FieldSpec) -> list[list[str]]:
    """Every value of this field's type that appears in a sentence mentioning the field."""
    if not spec.anchor:
        return []
    groups: list[list[str]] = []
    for page in doc.pages:
        for sentence in split_sentences(page.text):
            if re.search(spec.anchor, sentence, re.I):
                groups.extend(sorted(g) for g in find_candidates(spec.type, sentence))
    return groups


class Checks(BaseModel):
    abstained: bool
    normalized_value: str | None = None
    quote_present: bool = False
    cited_page_valid: bool = False
    quote_match: Literal["exact", "fuzzy", "none", "n/a"] = "n/a"
    quote_score: float = 0.0
    quote_on_other_page: int | None = None
    value_in_quote: bool | None = None
    anchor_in_quote: bool | None = None
    ambiguous: bool = False
    candidates: list[list[str]] = Field(default_factory=list)
    conflict: bool = False
    quote_in_suspected_injection: bool = False


def _value_in_quote(spec: FieldSpec, value: str, quote: str) -> tuple[bool, bool]:
    """Returns (value can be derived from the quote, the matching reading is ambiguous)."""
    if spec.type == FieldType.TEXT:
        return value in normalize_name(quote), False
    for group in find_candidates(spec.type, quote):
        if value in group:
            return True, len(group) > 1
    return False, False


def verify_field(
    doc: Document,
    spec: FieldSpec,
    extraction: FieldExtraction,
    threshold: float = DEFAULT_FUZZY_THRESHOLD,
) -> Checks:
    candidates = anchored_candidates(doc, spec)
    abstained = extraction.status == "not_found" or extraction.value is None
    if abstained:
        return Checks(abstained=True, candidates=candidates)

    checks = Checks(abstained=False, candidates=candidates)
    checks.normalized_value = normalize_value(spec.type, extraction.value)
    quote = (extraction.evidence_quote or "").strip()
    checks.quote_present = bool(quote)

    page = doc.page(extraction.page) if extraction.page is not None else None
    checks.cited_page_valid = page is not None

    if quote:
        if page is not None:
            match = match_quote(quote, page.text, threshold)
            checks.quote_match, checks.quote_score = match.method, match.score
        else:
            checks.quote_match = "none"
        if checks.quote_match == "none":
            for other in doc.pages:
                if other is not page and match_quote(quote, other.text, threshold).method != "none":
                    checks.quote_on_other_page = other.number
                    break

        if checks.normalized_value is not None:
            checks.value_in_quote, checks.ambiguous = _value_in_quote(spec, checks.normalized_value, quote)
        if spec.anchor:
            checks.anchor_in_quote = re.search(spec.anchor, quote, re.I) is not None

        quote_norm = normalize_for_match(quote)
        checks.quote_in_suspected_injection = any(
            fuzz.partial_ratio(quote_norm, normalize_for_match(s)) >= threshold
            for _, s in suspected_injections(doc)
        )

    if checks.normalized_value is not None and candidates:
        checks.conflict = any(checks.normalized_value not in group for group in candidates)
        checks.ambiguous = checks.ambiguous or any(
            checks.normalized_value in group and len(group) > 1 for group in candidates
        )

    return checks
