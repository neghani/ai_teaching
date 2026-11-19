# Production AI for Document-Heavy Workflows

**Architecture write-ups and reference implementations for building reliable LLM systems on real-world documents: extraction, evaluation, cost control, and human-in-the-loop review.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Status](https://img.shields.io/badge/status-in%20progress-orange)
![Data](https://img.shields.io/badge/data-100%25%20synthetic-brightgreen)

Most document AI demos look perfect. Production is different: amendments override clauses, fields are missing, numbers appear in the wrong context, scans are noisy, and a confident wrong answer slips through unnoticed.

This series builds small, production-shaped systems that deal with those problems directly. Each article ships with:

- An architecture diagram, including failure paths
- A synthetic dataset with hand-checked labels
- Unit tests and adversarial tests (missing fields, conflicts, prompt injection)
- Before/after metrics: quality, latency, cost, and human review rate
- Lessons learned and what I would do differently

## Who this is for

- AI and ML engineers moving LLM features from prototype to production
- Teams building intelligent document processing (IDP) for contracts, invoices, claims, or compliance
- Architects who need to reason about reliability, evaluation, and cost, not just model choice

## Articles

| # | Article | Production concern | Status |
|---|---------|--------------------|--------|
| 1 | [Grounded extraction: evidence, verification, and abstain](articles/01-grounded-extraction/README.md) | Reliability, human-in-the-loop | Draft |
| 2 | Evaluation and regression testing for LLM pipelines | Evaluation | Planned |
| 3 | Parsing and chunking: tables, scans, and layout | Reliability | Planned |
| 4 | Cost-aware model routing and caching | Cost | Planned |
| 5 | Async document pipelines: scale and backpressure | Reliability | Planned |
| 6 | Observability and incident replay for AI systems | Reliability | Planned |
| 7 | Permission-aware agents | Reliability, human-in-the-loop | Planned |
| 8 | Human-in-the-loop document review system (capstone) | Human-in-the-loop | Planned |

Each article builds on the previous ones, and the capstone reuses pieces from all of them.

## Core principles

1. **Evidence over confidence.** Every extracted value carries a quote and a page, verified by code rather than by the model.
2. **Abstaining is a valid answer.** "Not found" is better than a plausible guess.
3. **Measure silent errors.** Track wrong answers that were auto-accepted, not just accuracy.
4. **Cost sits next to quality.** Never optimize one without reporting the other.
5. **Humans review what code can't verify**, and they see the reason why.

## Repository layout

```
articles/
└── 01-grounded-extraction/
    ├── README.md     # the article
    └── assets/       # diagrams, charts, demo GIFs
```

## Keywords

LLM engineering, document AI, intelligent document processing, information extraction, structured output, grounding and citations, hallucination detection, LLM evaluation, human-in-the-loop, prompt injection, cost optimization, MLOps.

## License

Code and text are released under the [MIT License](LICENSE).

## Disclaimer

Independent learning project. All data is synthetic. Nothing here is based on employer work, documents, or data.
