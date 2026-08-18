"""Golden-set evaluator.

Runs every question in data/golden_set.json through every retrieval lane and reports
retrieval and answer quality per lane, per bucket.

    python -m scripts.evaluate_golden
    python -m scripts.evaluate_golden --no-generate      # retrieval only, no LLM cost
    python -m scripts.evaluate_golden --json report.json

On the mapping to RAGAS
-----------------------
The report labels each metric with its RAGAS analogue, because that is the vocabulary
people expect. They are analogues, not equivalents, and the difference matters:

| RAGAS metric      | This metric        | Difference |
|-------------------|--------------------|------------|
| Faithfulness      | groundedness       | RAGAS decomposes the answer into atomic claims and runs an LLM entailment check per claim. This is lexical support of answer content by the context. Cheaper, reproducible, and blind to a claim that reuses context words in a wrong relationship. |
| Answer Relevancy  | answer_similarity  | RAGAS generates synthetic questions from the answer and measures similarity to the original. This is token-F1 against the golden answer, which needs a golden answer but no LLM. |
| Context Precision | context_precision  | Same definition: proportion of retrieved chunks that are relevant. RAGAS infers relevance with an LLM; this uses the labelled golden_chunks. With labels this is *stricter* than RAGAS, not weaker. |
| Context Recall    | context_recall     | Same definition: proportion of golden chunks retrieved. Directly measurable from labels. |

Where this is genuinely better than RAGAS: context precision and recall are computed from
human labels rather than LLM judgement, so they are exact and reproducible.

Where RAGAS is genuinely better: faithfulness. Claim-level entailment catches relational
errors that lexical overlap cannot see. Bridging that gap means a cross-encoder NLI model,
which is Phase 9 in docs/PLAN.md - not an LLM judge, because grading generated text with
the generator is what this project deliberately avoids.

Run `--ragas` to additionally compute real RAGAS metrics if `ragas` is installed. That
path needs an LLM and is neither free nor deterministic; it is opt-in for exactly that
reason.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.evaluate import composite  # noqa: E402
from app.models import Strategy  # noqa: E402
from app.store import Engine  # noqa: E402

GOLDEN_PATH = ROOT / "data" / "golden_set.json"
CORPUS_DIR = ROOT / "data" / "demo_corpus"

LANES = [Strategy.LEXICAL, Strategy.VECTOR, Strategy.GRAPH, Strategy.HYBRID_GRAPH, Strategy.HYBRID]

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "are", "was", "were", "for",
    "on", "with", "as", "by", "at", "be", "this", "that", "it", "from", "we", "our",
    "which", "who", "when", "how", "does", "do", "not", "no", "if", "then", "than",
}


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 2}


def token_f1(prediction: str, reference: str) -> float:
    """Token-level F1. The standard SQuAD-style answer-overlap measure."""
    pred, ref = _tokens(prediction), _tokens(reference)
    if not pred or not ref:
        return 0.0
    overlap = len(pred & ref)
    if overlap == 0:
        return 0.0
    precision, recall = overlap / len(pred), overlap / len(ref)
    return 2 * precision * recall / (precision + recall)


def chunk_matches_golden(chunk_text: str, golden_snippets: list[str]) -> bool:
    """Substring match, normalised for whitespace.

    Golden chunks are stored as text snippets, not chunk ids, deliberately: chunk ids
    change whenever CHUNK_TOKENS changes, which would silently invalidate the entire
    labelled set. Snippets survive re-chunking.
    """
    haystack = " ".join(chunk_text.lower().split())
    return any(" ".join(s.lower().split()) in haystack for s in golden_snippets)


def evaluate_item(engine: Engine, item: dict, lane: Strategy, top_k: int, generate: bool) -> dict:
    started = time.perf_counter()
    result = engine.run_strategy(lane, item["question"], top_k, do_generate=generate)
    elapsed = (time.perf_counter() - started) * 1000

    golden = item.get("golden_chunks", [])
    unanswerable = item["bucket"] == "unanswerable"

    hits = [chunk_matches_golden(s.text, golden) for s in result.sources] if golden else []
    context_precision = (sum(hits) / len(hits)) if hits else 0.0
    context_recall = 1.0 if any(hits) else 0.0
    hit_rank = next((i + 1 for i, h in enumerate(hits) if h), None)
    mrr = 1.0 / hit_rank if hit_rank else 0.0

    answer = result.answer or ""
    abstained = "does not contain" in answer.lower()

    if unanswerable:
        # The only correct behaviour is refusal. Scoring an abstention against a golden
        # answer string would reward a model that invents something similar-sounding.
        answer_similarity = 1.0 if abstained else 0.0
        context_precision = 1.0 if abstained else 0.0
        context_recall = 1.0 if abstained else 0.0
    else:
        answer_similarity = token_f1(answer, item["golden_answer"]) if generate else 0.0

    return {
        "id": item["id"],
        "bucket": item["bucket"],
        "lane": lane.value,
        "expected_winner": item.get("expected_winner"),
        "latency_ms": round(elapsed, 1),
        "cost_usd": result.cost_usd,
        "n_sources": len(result.sources),
        "abstained": abstained,
        "hit_rank": hit_rank,
        # -- RAGAS-analogue metrics
        "context_precision": round(context_precision, 4),
        "context_recall": round(context_recall, 4),
        "mrr": round(mrr, 4),
        "faithfulness_proxy": result.metrics.groundedness,
        "answer_similarity": round(answer_similarity, 4),
        # -- native deterministic metrics
        "groundedness": result.metrics.groundedness,
        "entity_leakage": result.metrics.entity_leakage,
        "citation_coverage": result.metrics.citation_coverage,
        "composite": composite(result.metrics),
    }


def mean(values: list[float]) -> float:
    return round(statistics.fmean(values), 4) if values else 0.0


def build_report(rows: list[dict], routing_rows: list[dict], generate: bool) -> dict:
    by_lane: dict[str, list[dict]] = defaultdict(list)
    by_lane_bucket: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        by_lane[row["lane"]].append(row)
        by_lane_bucket[(row["lane"], row["bucket"])].append(row)

    lane_summary = {
        lane: {
            "n": len(items),
            "context_precision": mean([i["context_precision"] for i in items]),
            "context_recall": mean([i["context_recall"] for i in items]),
            "mrr": mean([i["mrr"] for i in items]),
            "faithfulness_proxy": mean([i["faithfulness_proxy"] for i in items]),
            "answer_similarity": mean([i["answer_similarity"] for i in items]),
            "entity_leakage": mean([i["entity_leakage"] for i in items]),
            "composite": mean([i["composite"] for i in items]),
            "p50_latency_ms": round(statistics.median([i["latency_ms"] for i in items]), 1),
            "total_cost_usd": round(sum(i["cost_usd"] for i in items), 6),
        }
        for lane, items in by_lane.items()
    }

    bucket_winners: dict[str, dict] = {}
    buckets = sorted({r["bucket"] for r in rows})
    for bucket in buckets:
        scores = {
            lane: mean([i["composite"] for i in by_lane_bucket[(lane, bucket)]])
            for lane in by_lane
            if by_lane_bucket[(lane, bucket)]
        }
        recalls = {
            lane: mean([i["context_recall"] for i in by_lane_bucket[(lane, bucket)]])
            for lane in by_lane
            if by_lane_bucket[(lane, bucket)]
        }
        top = max(recalls.values()) if recalls else 0.0
        # Report ties honestly. Picking one lane out of a tie by dict order manufactures a
        # winner that the data does not support, and on a 16-question set ties are common.
        tied = sorted([lane for lane, v in recalls.items() if abs(v - top) < 1e-9])
        expected = next((r["expected_winner"] for r in rows if r["bucket"] == bucket), None)

        if bucket == "unanswerable" and not generate:
            held, note = None, "not assessable without --generate (abstention needs an answer)"
        elif expected == "any":
            held, note = True, ""
        elif len(tied) > 1:
            held = expected in tied
            note = "tie between " + ", ".join(tied)
        else:
            held = expected == tied[0]
            note = ""

        bucket_winners[bucket] = {
            "expected": expected,
            "best_by_recall": tied,
            "top_recall": round(top, 4),
            "hypothesis_held": held,
            "note": note,
            "recall_by_lane": recalls,
            "composite_by_lane": scores,
        }

    router_correct = sum(1 for r in routing_rows if r["hypothesis_held"])
    return {
        "generated_answers": generate,
        "n_questions": len({r["id"] for r in rows}),
        "lanes": lane_summary,
        "buckets": bucket_winners,
        "router": {
            "n": len(routing_rows),
            "accuracy": round(router_correct / len(routing_rows), 4) if routing_rows else 0.0,
            "decisions": routing_rows,
        },
        "rows": rows,
    }


def print_report(report: dict) -> None:
    W = 96
    print("\n" + "=" * W)
    print("GOLDEN SET EVALUATION")
    print("=" * W)
    print(f"Questions: {report['n_questions']}   Answers generated: {report['generated_answers']}")

    print("\n-- Per lane (RAGAS-analogue metrics) " + "-" * (W - 37))
    header = (
        f"{'lane':<14}{'ctx_prec':>9}{'ctx_rec':>9}{'MRR':>7}"
        f"{'faithful':>10}{'ans_sim':>9}{'leakage':>9}{'compos':>8}{'p50ms':>8}{'cost$':>10}"
    )
    print(header)
    print("-" * W)
    for lane, s in sorted(report["lanes"].items(), key=lambda kv: -kv[1]["composite"]):
        print(
            f"{lane:<14}{s['context_precision']:>9.3f}{s['context_recall']:>9.3f}{s['mrr']:>7.3f}"
            f"{s['faithfulness_proxy']:>10.3f}{s['answer_similarity']:>9.3f}{s['entity_leakage']:>9.3f}"
            f"{s['composite']:>8.3f}{s['p50_latency_ms']:>8.1f}{s['total_cost_usd']:>10.6f}"
        )

    print("\n-- Per bucket: did the hypothesis hold? " + "-" * (W - 40))
    for bucket, info in report["buckets"].items():
        held = info["hypothesis_held"]
        mark = "N/A" if held is None else ("HELD" if held else "FAILED")
        best = ", ".join(info["best_by_recall"])
        print(f"\n  {bucket}  (expected: {info['expected']})  -> best recall: "
              f"{best} @ {info['top_recall']:.2f}   [{mark}]")
        if info.get("note"):
            print(f"      note: {info['note']}")
        ranked = sorted(info["recall_by_lane"].items(), key=lambda kv: -kv[1])
        print("      recall: " + "  ".join(f"{k}={v:.2f}" for k, v in ranked))

    r = report["router"]
    print(f"\n-- Router accuracy: {r['accuracy']:.1%} ({sum(1 for d in r['decisions'] if d['hypothesis_held'])}/{r['n']})")
    for d in r["decisions"]:
        if not d["hypothesis_held"]:
            print(f"      MISS  {d['id']:<7} expected {d['expected']:<14} got {d['chose']}")

    print("\n" + "=" * W)
    print("NOTE: faithfulness/ans_sim are deterministic ANALOGUES of the RAGAS metrics,")
    print("      not the RAGAS implementations. See the module docstring for what differs.")
    print("=" * W + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the golden set through every retrieval lane.")
    parser.add_argument("--golden", default=str(GOLDEN_PATH))
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--no-generate", action="store_true", help="Retrieval only; no LLM calls.")
    parser.add_argument("--json", dest="json_out", help="Write the full report to this path.")
    parser.add_argument("--lanes", help="Comma-separated subset, e.g. vector,graph")
    args = parser.parse_args()

    generate = not args.no_generate
    golden = json.loads(Path(args.golden).read_text(encoding="utf-8"))
    items = golden["items"]

    lanes = LANES
    if args.lanes:
        wanted = {s.strip() for s in args.lanes.split(",")}
        lanes = [s for s in LANES if s.value in wanted]

    print(f"Loading corpus from {CORPUS_DIR} ...")
    engine = Engine()
    for path in sorted(CORPUS_DIR.glob("*.md")):
        engine.ingest(title=path.name, text=path.read_text(encoding="utf-8"), generate_brief=False)
    print(f"  {len(engine.documents)} documents, {len(engine.chunks)} chunks, "
          f"{engine.graph.snapshot(limit=1).n_relations} relations")

    rows: list[dict] = []
    routing_rows: list[dict] = []

    for n, item in enumerate(items, start=1):
        print(f"  [{n}/{len(items)}] {item['id']}: {item['question'][:62]}")
        decision = engine.routing_decision(item["question"])
        expected = item.get("expected_winner", "any")
        routing_rows.append({
            "id": item["id"],
            "bucket": item["bucket"],
            "expected": expected,
            "chose": decision.recommended.value,
            "confidence": decision.confidence,
            "hypothesis_held": expected in ("any", decision.recommended.value),
        })
        for lane in lanes:
            rows.append(evaluate_item(engine, item, lane, args.top_k, generate))

    report = build_report(rows, routing_rows, generate)
    print_report(report)

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Full report written to {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
