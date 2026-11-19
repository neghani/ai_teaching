"""Raw model output -> verified, policy-decided field outcomes."""

from __future__ import annotations

import time

from pydantic import BaseModel

from docai.extract import Mode, parse_response
from docai.normalize import normalize_value
from docai.policy import DEFAULT_POLICY, PolicyConfig, decide_baseline, decide_grounded
from docai.schema import FIELDS, Document, FieldOutcome
from docai.verify import DEFAULT_FUZZY_THRESHOLD, suspected_injections, verify_field


class DocResult(BaseModel):
    doc_id: str
    mode: Mode
    outcomes: list[FieldOutcome]
    suspected_injections: list[tuple[int, str]]
    verify_ms: float


def decide(
    doc: Document,
    raw: dict,
    mode: Mode,
    threshold: float = DEFAULT_FUZZY_THRESHOLD,
    policy: PolicyConfig = DEFAULT_POLICY,
) -> DocResult:
    extractions = parse_response(raw)
    start = time.perf_counter()
    outcomes = []
    for spec in FIELDS:
        ex = extractions[spec.name]
        if mode == "baseline":
            outcomes.append(decide_baseline(spec, ex, normalize_value(spec.type, ex.value)))
        else:
            outcomes.append(decide_grounded(spec, ex, verify_field(doc, spec, ex, threshold), policy))
    return DocResult(
        doc_id=doc.doc_id,
        mode=mode,
        outcomes=outcomes,
        suspected_injections=suspected_injections(doc),
        verify_ms=round((time.perf_counter() - start) * 1000, 2),
    )
