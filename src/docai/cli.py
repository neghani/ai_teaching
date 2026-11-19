"""docai extract contract.pdf [--mode grounded] [--review-queue review.jsonl]"""

from __future__ import annotations

import argparse
import json

from docai import review_queue
from docai.extract import extract
from docai.llm import DEFAULT_MODEL, OllamaClient
from docai.parse import parse_pdf
from docai.pipeline import decide
from docai.verify import DEFAULT_FUZZY_THRESHOLD


def main() -> None:
    parser = argparse.ArgumentParser(prog="docai")
    sub = parser.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("extract", help="Extract fields from a PDF")
    ex.add_argument("pdf")
    ex.add_argument("--mode", choices=["baseline", "grounded"], default="grounded")
    ex.add_argument("--model", default=DEFAULT_MODEL)
    ex.add_argument("--threshold", type=float, default=DEFAULT_FUZZY_THRESHOLD)
    ex.add_argument("--review-queue", default="review.jsonl")
    args = parser.parse_args()

    doc = parse_pdf(args.pdf)
    raw, usage = extract(doc, args.mode, OllamaClient(args.model))
    result = decide(doc, raw, args.mode, args.threshold)
    review_queue.append(args.review_queue, review_queue.review_items(doc.doc_id, result.outcomes, args.model))

    for o in result.outcomes:
        print(f"{o.field:<26} {o.decision.value:<10} {str(o.value):<20} {', '.join(o.reasons)}")
    print(json.dumps({"usage": usage.model_dump(), "verify_ms": result.verify_ms}))


if __name__ == "__main__":
    main()
