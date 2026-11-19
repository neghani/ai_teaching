"""Run baseline and grounded pipelines on the synthetic set and write metrics, charts and a report.

    uv run python eval/run_eval.py                 # call the model (cached per doc)
    uv run python eval/run_eval.py --reuse         # re-score cached model outputs only

Raw model outputs are cached under eval/runs/<model>/<mode>/ so verification rules and
thresholds can be changed and re-measured without calling the model again.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from docai.extract import extract  # noqa: E402
from docai.llm import DEFAULT_MODEL, OllamaClient  # noqa: E402
from docai.normalize import normalize_name  # noqa: E402
from docai.parse import parse_pdf  # noqa: E402
from docai.pipeline import decide  # noqa: E402
from docai.policy import DEFAULT_POLICY, STRICT, PolicyConfig  # noqa: E402
from docai.schema import FIELDS, FIELDS_BY_NAME, Decision, FieldType  # noqa: E402
from docai.verify import DEFAULT_FUZZY_THRESHOLD  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RUNS = ROOT / "eval" / "runs"
ASSETS = ROOT / "articles" / "01-grounded-extraction" / "assets"
MODES = ("baseline", "grounded")


def load_dataset():
    for label_path in sorted((DATA / "labels").glob("*.json")):
        label = json.loads(label_path.read_text())
        yield parse_pdf(DATA / "docs" / f"{label['doc_id']}.pdf"), label


def model_outputs(model: str, reuse: bool, dataset) -> dict:
    client = None if reuse else OllamaClient(model)
    cache: dict = {}
    for doc, _ in dataset:
        for mode in MODES:
            path = RUNS / model.replace(":", "_") / mode / f"{doc.doc_id}.json"
            if path.exists():
                cache[(doc.doc_id, mode)] = json.loads(path.read_text())
                continue
            if client is None:
                raise SystemExit(f"No cached output at {path}; run without --reuse")
            print(f"  {mode:<9} {doc.doc_id}", flush=True)
            raw, usage = extract(doc, mode, client)
            record = {"raw": raw, "usage": usage.model_dump()}
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record, indent=2))
            cache[(doc.doc_id, mode)] = record
    return cache


def truth_value(field: str, label: dict) -> str | None:
    value = label["fields"][field]
    if value is None:
        return None
    return normalize_name(value) if FIELDS_BY_NAME[field].type == FieldType.TEXT else value


POLICY_ITERATIONS = [
    ("v1 strict", "v1\nstrict", STRICT),
    ("v2 + repair page citations", "v2\n+ page repair", PolicyConfig(repair_page=True)),
    ("v3 + review missing required fields", "v3\n+ required fields",
     PolicyConfig(repair_page=True, review_missing_required=True)),
    ("v4 + quote must mention the field", "v4\n+ quote names field", DEFAULT_POLICY),
]


def score(dataset, outputs, mode: str, threshold: float, policy: PolicyConfig = DEFAULT_POLICY) -> tuple[list[dict], list[float]]:
    rows, verify_ms = [], []
    for doc, label in dataset:
        result = decide(doc, outputs[(doc.doc_id, mode)]["raw"], mode, threshold, policy)
        verify_ms.append(result.verify_ms)
        for o in result.outcomes:
            truth = truth_value(o.field, label)
            final = o.value if o.decision == Decision.ACCEPT else None
            rows.append({
                "doc_id": doc.doc_id,
                "category": label["category"],
                "field": o.field,
                "truth": truth,
                "predicted": o.value,
                "decision": o.decision.value,
                "correct": truth is not None and o.value == truth,
                # Silent error: the system committed to an answer (accept, or a not_found nobody reviews) that is wrong.
                "silent_error": o.decision != Decision.REVIEW and final != truth,
                "expected_review": o.field in label.get("expect_review", []),
                "confidence": o.confidence,
                "quote_match": o.checks.get("quote_match"),
                "reasons": ";".join(o.reasons),
            })
    return rows, verify_ms


def pct(n: int, d: int) -> float | None:
    return round(100 * n / d, 1) if d else None


def metrics(rows: list[dict], outputs: dict, mode: str, verify_ms: list[float], price_in: float, price_out: float) -> dict:
    total = len(rows)
    present = [r for r in rows if r["truth"] is not None]
    missing = [r for r in rows if r["truth"] is None]
    accepted = [r for r in rows if r["decision"] == "accept"]
    quoted = [r for r in rows if r["quote_match"] in ("exact", "fuzzy", "none")]
    usages = [v["usage"] for (_, m), v in outputs.items() if m == mode]
    latencies = sorted(u["latency_s"] for u in usages)
    tok_in = statistics.mean(u["prompt_tokens"] for u in usages)
    tok_out = statistics.mean(u["completion_tokens"] for u in usages)
    return {
        "fields": total,
        "field_accuracy": pct(sum(r["correct"] for r in present), len(present)),
        "silent_error_rate": pct(sum(r["silent_error"] for r in rows), total),
        "silent_errors": sum(r["silent_error"] for r in rows),
        "accepted_precision": pct(sum(r["correct"] for r in accepted), len(accepted)),
        "abstain_correctness": pct(sum(r["decision"] == "not_found" for r in missing), len(missing)),
        "review_rate": pct(sum(r["decision"] == "review" for r in rows), total),
        "reviews_where_model_was_right": sum(r["decision"] == "review" and r["correct"] for r in rows),
        "citation_validity": pct(sum(r["quote_match"] in ("exact", "fuzzy") for r in quoted), len(quoted)) if quoted else None,
        "tokens_in_per_doc": round(tok_in),
        "tokens_out_per_doc": round(tok_out),
        "est_cost_per_1k_docs_usd": round(1000 * (tok_in * price_in + tok_out * price_out) / 1e6, 2),
        "latency_p50_s": round(statistics.median(latencies), 1),
        "latency_p95_s": round(latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))], 1),
        "verify_ms_per_doc": round(statistics.mean(verify_ms), 2),
    }


def threshold_sweep(dataset, outputs) -> list[dict]:
    points = []
    for t in range(50, 101, 5):
        rows, _ = score(dataset, outputs, "grounded", float(t))
        points.append({
            "threshold": t,
            "review_rate": pct(sum(r["decision"] == "review" for r in rows), len(rows)),
            "silent_error_rate": pct(sum(r["silent_error"] for r in rows), len(rows)),
        })
    return points


def policy_iterations(dataset, outputs, threshold: float) -> list[dict]:
    result = []
    for name, short, policy in POLICY_ITERATIONS:
        rows, _ = score(dataset, outputs, "grounded", threshold, policy)
        accepted = [r for r in rows if r["decision"] == "accept"]
        result.append({
            "policy": name,
            "short": short,
            "review_rate": pct(sum(r["decision"] == "review" for r in rows), len(rows)),
            "silent_errors": sum(r["silent_error"] for r in rows),
            "silent_error_rate": pct(sum(r["silent_error"] for r in rows), len(rows)),
            "accepted_precision": pct(sum(r["correct"] for r in accepted), len(accepted)),
        })
    return result


def calibration(rows: list[dict]) -> list[dict]:
    bins = [(0.0, 0.5), (0.5, 0.8), (0.8, 0.95), (0.95, 1.01)]
    found = [r for r in rows if r["predicted"] is not None and r["confidence"] is not None]
    out = []
    for lo, hi in bins:
        sel = [r for r in found if lo <= r["confidence"] < hi]
        out.append({"bin": f"{lo:.2f}-{min(hi, 1):.2f}", "n": len(sel),
                    "accuracy": pct(sum(r["predicted"] == r["truth"] for r in sel), len(sel))})
    return out


def charts(sweep, rows_by_mode, iterations, baseline_metrics) -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)

    points = [{"short": "baseline\n(accept all)", **baseline_metrics}] + iterations
    fig, ax = plt.subplots(figsize=(8, 4.2))
    names = [p["short"] for p in points]
    xs = range(len(points))
    ax.bar([x - 0.2 for x in xs], [p["review_rate"] for p in points], 0.4, label="Review rate (%)")
    ax.bar([x + 0.2 for x in xs], [p["silent_error_rate"] for p in points], 0.4, label="Silent error rate (%)")
    for x, p in zip(xs, points):
        ax.annotate(f"{p['silent_errors']} silent", (x + 0.2, p["silent_error_rate"]), ha="center", va="bottom", fontsize=8)
    ax.set_xticks(list(xs), names, fontsize=8)
    ax.set_ylabel("% of fields")
    ax.set_title("Each policy rule: review rate vs silent errors (same model outputs)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(ASSETS / "policy_iterations.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot([p["threshold"] for p in sweep], [p["review_rate"] for p in sweep], marker="o", label="Review rate")
    ax.plot([p["threshold"] for p in sweep], [p["silent_error_rate"] for p in sweep], marker="o", label="Silent error rate")
    ax.set_xlabel("Fuzzy quote-match threshold")
    ax.set_ylabel("% of fields")
    ax.set_title("Grounded pipeline: quote-match threshold trade-off")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(ASSETS / "threshold_tradeoff.png", dpi=150)
    plt.close(fig)

    width = 0.38
    categories = sorted({r["category"] for r in rows_by_mode["baseline"]})
    fig, ax = plt.subplots(figsize=(8, 4))
    for i, mode in enumerate(MODES):
        counts = Counter(r["category"] for r in rows_by_mode[mode] if r["silent_error"])
        ax.bar([j + (i - 0.5) * width for j in range(len(categories))], [counts[c] for c in categories], width, label=mode)
    ax.set_xticks(range(len(categories)), categories, rotation=30, ha="right")
    ax.set_ylabel("Silent errors (fields)")
    ax.yaxis.get_major_locator().set_params(integer=True)
    ax.set_title("Silent errors by document category")
    ax.legend()
    fig.tight_layout()
    fig.savefig(ASSETS / "silent_errors_by_category.png", dpi=150)
    plt.close(fig)


def write_report(model, threshold, m, sweep, calib_by_mode, rows_by_mode, iterations, price_in, price_out) -> str:
    labels = {
        "field_accuracy": "Field accuracy (%)",
        "silent_error_rate": "**Silent error rate (%)**",
        "silent_errors": "Silent errors (fields)",
        "accepted_precision": "Precision of auto-accepted fields (%)",
        "abstain_correctness": "Abstain correctness (%)",
        "review_rate": "Review rate (%)",
        "reviews_where_model_was_right": "Reviewed fields where the model was already right",
        "citation_validity": "Citation validity (%)",
        "tokens_in_per_doc": "Input tokens / doc",
        "tokens_out_per_doc": "Output tokens / doc",
        "est_cost_per_1k_docs_usd": f"Est. cost / 1k docs (USD at ${price_in}/${price_out} per 1M tokens)",
        "latency_p50_s": "Latency p50 (s)",
        "latency_p95_s": "Latency p95 (s)",
        "verify_ms_per_doc": "Verification time / doc (ms)",
    }
    lines = [
        "# Week 1 evaluation report",
        "",
        f"Generated by `eval/run_eval.py`. Model: `{model}` (local, via Ollama). Fuzzy threshold: {threshold:g}.",
        f"Dataset: {len(rows_by_mode['baseline']) // len(FIELDS)} synthetic documents x {len(FIELDS)} fields.",
        "",
        "## Baseline vs grounded",
        "",
        "| Metric | Baseline | Grounded |",
        "|---|---|---|",
    ]
    for key, name in labels.items():
        b, g = m["baseline"].get(key), m["grounded"].get(key)
        lines.append(f"| {name} | {'n/a' if b is None else b} | {'n/a' if g is None else g} |")

    lines += ["", "## Policy iterations (same model outputs, different verification policy)", "",
              "| Policy | Review rate (%) | Silent errors | Silent error rate (%) | Precision of auto-accepted (%) |",
              "|---|---|---|---|---|"]
    b = m["baseline"]
    lines.append(f"| baseline (accept everything) | {b['review_rate']} | {b['silent_errors']} | {b['silent_error_rate']} | "
                 f"{b['accepted_precision']} |")
    lines += [f"| {it['policy']} | {it['review_rate']} | {it['silent_errors']} | {it['silent_error_rate']} | "
              f"{it['accepted_precision']} |" for it in iterations]

    lines += ["", "## Silent errors by category", "", "| Category | Fields | Baseline | Grounded | Grounded review |", "|---|---|---|---|---|"]
    by_cat = defaultdict(lambda: defaultdict(list))
    for mode in MODES:
        for r in rows_by_mode[mode]:
            by_cat[r["category"]][mode].append(r)
    for cat in sorted(by_cat):
        b, g = by_cat[cat]["baseline"], by_cat[cat]["grounded"]
        lines.append(f"| {cat} | {len(b)} | {sum(r['silent_error'] for r in b)} | {sum(r['silent_error'] for r in g)} | "
                     f"{sum(r['decision'] == 'review' for r in g)} |")

    reasons = Counter(x for r in rows_by_mode["grounded"] for x in r["reasons"].split(";") if x)
    lines += ["", "## Why fields went to review (grounded)", "", "| Reason | Fields |", "|---|---|"]
    lines += [f"| `{k}` | {v} |" for k, v in reasons.most_common()]

    expected = [r for r in rows_by_mode["grounded"] if r["expected_review"]]
    lines += ["", f"Fields that should have gone to review (ambiguous dates): "
              f"{sum(r['decision'] == 'review' for r in expected)}/{len(expected)} routed to review."]

    for mode in MODES:
        lines += ["", f"## Silent errors ({mode})", "",
                  "| Doc | Field | Truth | Committed answer | Self-reported confidence |", "|---|---|---|---|---|"]
        errors = [r for r in rows_by_mode[mode] if r["silent_error"]]
        for r in errors:
            shown = r["predicted"] if r["decision"] == "accept" else "(not_found)"
            lines.append(f"| {r['doc_id']} | {r['field']} | {r['truth'] or '(absent)'} | {shown} | {r['confidence']} |")
        if not errors:
            lines.append("| none | | | | |")

    lines += ["", "## Threshold sweep (grounded)", "", "| Threshold | Review rate (%) | Silent error rate (%) |", "|---|---|---|"]
    lines += [f"| {p['threshold']} | {p['review_rate']} | {p['silent_error_rate']} |" for p in sweep]

    lines += ["", "## Self-reported confidence vs accuracy", "", "| Mode | Confidence | Fields | Accuracy (%) |", "|---|---|---|---|"]
    for mode, calib in calib_by_mode.items():
        lines += [f"| {mode} | {c['bin']} | {c['n']} | {c['accuracy']} |" for c in calib]

    lines += ["", "## Definitions", "",
              "- **Silent error:** the system committed to an answer without human review (auto-accepted a value, "
              "or returned not_found) and that answer is wrong. Denominator: all fields.",
              "- **Field accuracy:** fields where the extracted value is correct, regardless of decision / fields that have a true value.",
              "- **Abstain correctness:** truly missing fields that ended as not_found / truly missing fields.",
              "- **Citation validity:** returned quotes found on the cited page (exact or fuzzy) / returned quotes.",
              "- **Cost:** the model runs locally, so real cost is electricity. The estimate prices the measured tokens at a hosted small-model rate for comparison.",
              ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--threshold", type=float, default=DEFAULT_FUZZY_THRESHOLD)
    parser.add_argument("--reuse", action="store_true", help="Only re-score cached model outputs")
    parser.add_argument("--price-in", type=float, default=0.15, help="USD per 1M input tokens, for the estimate")
    parser.add_argument("--price-out", type=float, default=0.60, help="USD per 1M output tokens, for the estimate")
    args = parser.parse_args()

    dataset = list(load_dataset())
    print(f"{len(dataset)} documents, model {args.model}")
    outputs = model_outputs(args.model, args.reuse, dataset)

    rows_by_mode, m, calib_by_mode = {}, {}, {}
    for mode in MODES:
        rows, verify_ms = score(dataset, outputs, mode, args.threshold)
        rows_by_mode[mode] = rows
        m[mode] = metrics(rows, outputs, mode, verify_ms, args.price_in, args.price_out)
        calib_by_mode[mode] = calibration(rows)
    sweep = threshold_sweep(dataset, outputs)
    iterations = policy_iterations(dataset, outputs, args.threshold)

    run_dir = RUNS / args.model.replace(":", "_")
    for mode in MODES:
        with (run_dir / f"field_results_{mode}.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows_by_mode[mode][0]))
            writer.writeheader()
            writer.writerows(rows_by_mode[mode])
    (run_dir / "metrics.json").write_text(json.dumps(
        {"metrics": m, "policy_iterations": iterations, "sweep": sweep, "calibration": calib_by_mode}, indent=2))

    charts(sweep, rows_by_mode, iterations, m["baseline"])
    report = write_report(args.model, args.threshold, m, sweep, calib_by_mode, rows_by_mode, iterations,
                          args.price_in, args.price_out)
    (ROOT / "eval" / "report.md").write_text(report)
    print(json.dumps(m, indent=2))


if __name__ == "__main__":
    main()
