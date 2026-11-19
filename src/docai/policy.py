"""Turn verification checks into an accept / review / not_found decision."""

from __future__ import annotations

from pydantic import BaseModel

from docai.schema import Decision, FieldExtraction, FieldOutcome, FieldSpec
from docai.verify import Checks


class PolicyConfig(BaseModel):
    # Quote exists, but on a different page than cited: fix the page instead of asking a human.
    repair_page: bool = False
    # "not_found" on a field every agreement must state goes to a human.
    review_missing_required: bool = False
    # The quote must mention the field itself (e.g. "terminat" for the notice period).
    require_anchor_in_quote: bool = False


STRICT = PolicyConfig()
DEFAULT_POLICY = PolicyConfig(repair_page=True, review_missing_required=True, require_anchor_in_quote=True)


def review_reasons(spec: FieldSpec, checks: Checks, config: PolicyConfig = DEFAULT_POLICY) -> list[str]:
    if checks.abstained:
        if checks.candidates:
            return ["abstained_but_candidates_found"]
        if config.review_missing_required and spec.required:
            return ["required_field_missing"]
        return []

    reasons: list[str] = []
    if not checks.quote_present:
        reasons.append("missing_quote")
    elif checks.quote_match == "none":
        if checks.quote_on_other_page is None:
            reasons.append("quote_not_in_document")
        elif not config.repair_page:
            reasons.append("quote_on_different_page")
    if checks.normalized_value is None:
        reasons.append("value_unparseable")
    elif checks.quote_present and checks.value_in_quote is False:
        reasons.append("value_not_in_quote")
    if config.require_anchor_in_quote and checks.anchor_in_quote is False:
        reasons.append("quote_does_not_mention_field")
    if checks.ambiguous:
        reasons.append("ambiguous_value")
    if checks.conflict:
        reasons.append("conflicting_candidates")
    if checks.quote_in_suspected_injection:
        reasons.append("quote_from_suspected_injection")
    return reasons


def decide_grounded(
    spec: FieldSpec, extraction: FieldExtraction, checks: Checks, config: PolicyConfig = DEFAULT_POLICY
) -> FieldOutcome:
    reasons = review_reasons(spec, checks, config)
    if checks.abstained and not reasons:
        decision = Decision.NOT_FOUND
    elif reasons:
        decision = Decision.REVIEW
    else:
        decision = Decision.ACCEPT
    page = extraction.page
    if config.repair_page and checks.quote_match == "none" and checks.quote_on_other_page is not None:
        page = checks.quote_on_other_page
    return FieldOutcome(
        field=spec.name,
        decision=decision,
        value=checks.normalized_value,
        raw_value=extraction.value,
        evidence_quote=extraction.evidence_quote,
        page=page,
        confidence=extraction.confidence,
        reasons=reasons,
        checks=checks.model_dump(),
    )


def decide_baseline(spec: FieldSpec, extraction: FieldExtraction, normalized_value: str | None) -> FieldOutcome:
    """The naive policy: whatever the model returns is accepted."""
    abstained = extraction.value is None
    return FieldOutcome(
        field=spec.name,
        decision=Decision.NOT_FOUND if abstained else Decision.ACCEPT,
        value=normalized_value,
        raw_value=extraction.value,
        evidence_quote=None,
        page=None,
        confidence=extraction.confidence,
    )
