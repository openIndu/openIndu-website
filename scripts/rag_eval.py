"""RAG retrieval evaluation harness — reusable golden-test-set runner.

Why this exists
----------------
Ad-hoc "eyeball a few chat logs" evaluation doesn't scale and can't be re-run
after a config change. This script runs the SAME queries every time against
the SAME code path production uses (`app.services.milvus_service.search()` +
`app.services.chat_service.determine_mode()`), so retrieval-quality changes
(index type, nprobe, threshold, chunking, new documents) can be measured with
a single before/after diff instead of re-deriving the analysis from scratch.

Must run inside the backend container (needs app.* imports + Milvus access):
    docker compose exec -T web-api python scripts/rag_eval.py
    docker compose exec -T web-api python scripts/rag_eval.py --save baseline.json
    docker compose exec -T web-api python scripts/rag_eval.py --compare baseline.json

Test set lives in scripts/rag_eval_queries.json (aggregate repo root) — add
cases there as new documents/brands are onboarded; this script never needs
to change for that.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Aggregate-repo scripts/ is bind-mounted at /app/../scripts inside the
# web-api container (see docker-compose.yml volumes); resolve relative to
# this file so it works both in-container and if ever run from host.
QUERIES_PATH = Path(__file__).resolve().parent / "rag_eval_queries.json"
GROUNDED_THRESHOLD = 0.7  # must mirror chat_service._FALLBACK_SCORE_THRESHOLD


def load_queries() -> dict:
    if not QUERIES_PATH.exists():
        sys.exit(f"FATAL: test set not found at {QUERIES_PATH}")
    return json.loads(QUERIES_PATH.read_text(encoding="utf-8"))


def run_case(query: str, top_k: int = 5) -> dict:
    """Run one query through the real production retrieval path."""
    from app.services.milvus_service import milvus_service
    from app.services.chat_service import determine_mode

    chunks = milvus_service.search(query, top_k=top_k)
    mode = determine_mode(chunks)
    top1 = chunks[0] if chunks else None
    return {
        "mode": mode,
        "top1_score": top1["score"] if top1 else 0.0,
        "top1_document": top1["metadata"]["document_name"] if top1 else None,
        "top1_brand": top1["metadata"]["brand"] if top1 else None,
        "top_k_documents": [c["metadata"]["document_name"] for c in chunks],
    }


def evaluate() -> dict:
    data = load_queries()
    results = {"positive_cases": [], "negative_cases": []}

    print(f"=== Positive cases ({len(data['positive_cases'])}) ===")
    for case in data["positive_cases"]:
        r = run_case(case["query"])
        expected = case["expected_document_contains"]
        top1_hit = bool(r["top1_document"] and expected in r["top1_document"])
        top_k_hit = any(expected in d for d in r["top_k_documents"])
        row = {**case, **r, "top1_hit": top1_hit, "top_k_hit": top_k_hit}
        results["positive_cases"].append(row)
        flag = "OK " if (top1_hit and r["mode"] == "grounded") else ("~  " if top_k_hit else "MISS")
        print(f"  [{flag}] {case['id']:28} mode={r['mode']:9} top1_score={r['top1_score']:.3f}  top1_hit={top1_hit}  top_k_hit={top_k_hit}")
        if not top1_hit:
            print(f"         expected~={expected!r}  got={r['top1_document']!r}")

    print(f"\n=== Negative cases ({len(data['negative_cases'])}) — should fallback ===")
    for case in data["negative_cases"]:
        r = run_case(case["query"])
        correctly_fallback = r["mode"] == "fallback"
        row = {**case, **r, "correctly_fallback": correctly_fallback}
        results["negative_cases"].append(row)
        flag = "OK " if correctly_fallback else "MISS"
        print(f"  [{flag}] {case['id']:28} mode={r['mode']:9} top1_score={r['top1_score']:.3f}")

    return results


def summarize(results: dict) -> dict:
    pos = results["positive_cases"]
    neg = results["negative_cases"]
    n_pos = len(pos)
    n_neg = len(neg)

    top1_hit_rate = sum(1 for r in pos if r["top1_hit"]) / n_pos if n_pos else 0
    top_k_hit_rate = sum(1 for r in pos if r["top_k_hit"]) / n_pos if n_pos else 0
    grounded_rate = sum(1 for r in pos if r["mode"] == "grounded") / n_pos if n_pos else 0
    grounded_and_correct = sum(1 for r in pos if r["mode"] == "grounded" and r["top1_hit"]) / n_pos if n_pos else 0
    avg_top1_score = sum(r["top1_score"] for r in pos) / n_pos if n_pos else 0
    neg_correct_rate = sum(1 for r in neg if r["correctly_fallback"]) / n_neg if n_neg else 0

    summary = {
        "n_positive_cases": n_pos,
        "top1_hit_rate": round(top1_hit_rate, 3),
        "top_k_hit_rate": round(top_k_hit_rate, 3),
        "grounded_rate": round(grounded_rate, 3),
        "grounded_and_correct_rate": round(grounded_and_correct, 3),
        "avg_top1_score": round(avg_top1_score, 3),
        "n_negative_cases": n_neg,
        "negative_correct_fallback_rate": round(neg_correct_rate, 3),
    }
    return summary


def print_summary(summary: dict, label: str = "RESULTS"):
    print(f"\n=== {label} ===")
    print(f"  positive cases           : {summary['n_positive_cases']}")
    print(f"  top-1 hit rate           : {summary['top1_hit_rate']*100:.1f}%   (expected doc is the #1 result)")
    print(f"  top-k hit rate           : {summary['top_k_hit_rate']*100:.1f}%   (expected doc is anywhere in top-{5})")
    print(f"  grounded rate            : {summary['grounded_rate']*100:.1f}%   (score >= {GROUNDED_THRESHOLD} threshold)")
    print(f"  grounded AND correct     : {summary['grounded_and_correct_rate']*100:.1f}%   (the real end-to-end quality metric)")
    print(f"  avg top-1 score          : {summary['avg_top1_score']:.3f}")
    print(f"  negative fallback rate   : {summary['negative_correct_fallback_rate']*100:.1f}%   (should be 100% — no false positives)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--save", type=str, default=None, help="save full results to this JSON file")
    ap.add_argument("--compare", type=str, default=None, help="diff summary against a previously --save'd JSON file")
    args = ap.parse_args()

    results = evaluate()
    summary = summarize(results)
    print_summary(summary)

    if args.save:
        out = {"summary": summary, "results": results}
        Path(args.save).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nSaved to {args.save}")

    if args.compare:
        baseline = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        b = baseline["summary"]
        print(f"\n=== DIFF vs {args.compare} ===")
        for key in summary:
            if key.startswith("n_"):
                continue
            delta = summary[key] - b.get(key, 0)
            sign = "+" if delta >= 0 else ""
            print(f"  {key:28} {b.get(key, 0):.3f} -> {summary[key]:.3f}  ({sign}{delta:.3f})")


if __name__ == "__main__":
    main()
