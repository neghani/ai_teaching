"""Append fields that need a human to a JSONL review queue."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from docai.schema import Decision, FieldOutcome


def review_items(doc_id: str, outcomes: list[FieldOutcome], model: str) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "doc_id": doc_id,
            "field": o.field,
            "suggested_value": o.value,
            "evidence_quote": o.evidence_quote,
            "page": o.page,
            "reasons": o.reasons,
            "other_values_in_document": o.checks.get("candidates", []),
            "model": model,
            "queued_at": now,
        }
        for o in outcomes
        if o.decision == Decision.REVIEW
    ]


def append(path: str | Path, items: list[dict]) -> None:
    if not items:
        return
    with Path(path).open("a", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item) + "\n")
