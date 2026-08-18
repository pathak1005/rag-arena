"""Smoke tests. Fast, no network, no API key.

These assert the behaviours the README claims, so a regression in any of them means the
documentation has become a lie.
"""
from __future__ import annotations

import os

os.environ.setdefault("ALLOW_EMBED_DOWNLOAD", "0")   # keep tests offline and fast

from pathlib import Path

import pytest

from app.governance.pii import scrub
from app.models import Strategy
from app.readiness import analyze
from app.store import Engine

CORPUS = Path(__file__).resolve().parent.parent / "data" / "demo_corpus"


@pytest.fixture(scope="module")
def engine() -> Engine:
    eng = Engine()
    for path in sorted(CORPUS.glob("*.md")):
        eng.ingest(title=path.name, text=path.read_text(encoding="utf-8"), generate_brief=False)
    return eng


def test_pii_redacted_before_indexing(engine: Engine):
    """No raw email may survive into any indexed chunk."""
    assert engine.chunks
    for chunk in engine.chunks.values():
        assert "@helios-internal.example" not in chunk.text
    assert any("[REDACTED_EMAIL]" in c.text for c in engine.chunks.values())


def test_pii_report_masks_values():
    text = "Reach me at alice.smith@example.com or +1 415-555-0142."
    clean, report = scrub(text)
    assert "alice.smith@example.com" not in clean
    assert report.total_redacted >= 2
    for entity in report.entities:
        assert "@example.com" not in entity.surface   # audit trail must not leak the raw value


def test_all_strategies_share_one_chunk_set(engine: Engine):
    """The core design invariant: every retriever selects from the same chunk table."""
    question = "What causes ERR-7741?"
    for strategy in (Strategy.LEXICAL, Strategy.VECTOR, Strategy.GRAPH):
        result = engine.run_strategy(strategy, question, top_k=3, do_generate=False)
        for source in result.sources:
            assert source.chunk_id in engine.chunks


def test_router_picks_expected_lane(engine: Engine):
    cases = [
        ("What causes ERR-7741?", Strategy.LEXICAL),
        ("Who should I escalate to if checkout-api is failing because of a payment problem?", Strategy.GRAPH),
    ]
    for question, expected in cases:
        assert engine.routing_decision(question).recommended is expected


def test_graph_wins_multi_hop(engine: Engine):
    """Graph must surface the cross-document answer that flat retrieval misses."""
    question = "Who should I escalate to if checkout-api is failing because of a payment problem?"
    graph = engine.run_strategy(Strategy.GRAPH, question, top_k=3, do_generate=False)
    assert any("Priya" in s.text for s in graph.sources), "graph lost its own demo case"
    top = graph.sources[0]
    assert top.graph_path and len(top.graph_path) > 1, "answer was not reached by traversal"


def test_metrics_are_deterministic(engine: Engine):
    question = "What causes ERR-7741?"
    first = engine.run_strategy(Strategy.LEXICAL, question, 3, do_generate=True)
    second = engine.run_strategy(Strategy.LEXICAL, question, 3, do_generate=True)
    assert first.metrics.model_dump() == second.metrics.model_dump()


def test_abstention_is_not_scored_as_hallucination(engine: Engine):
    result = engine.run_strategy(Strategy.VECTOR, "What is the capital of Mars?", 3, do_generate=True)
    if "does not contain" in result.answer:
        assert result.metrics.groundedness == 1.0
        assert result.metrics.entity_leakage == 0.0


def test_readiness_discriminates():
    good = (CORPUS / "02_dependency_map.md").read_text(encoding="utf-8")
    bad = (
        "Overview\n\nIt is a seamless, world-class platform. This makes it easy for the team "
        "to leverage our next-generation capabilities.\n\nAs mentioned above, the service "
        "handles requests. They are processed by the system. The above process is robust.\n\n"
        "Contact ops@example.com or 415-555-0199."
    )
    assert analyze(good, "good").overall_score >= 80
    assert analyze(bad, "bad").overall_score <= 55


def test_agent_self_corrects_on_bad_retrieval(engine: Engine):
    """The behaviour that justifies the agent layer at all."""
    from app.agents.pipeline import run_agent

    result = run_agent(engine, "What is the capital of Mars in the year 3000?", top_k=3)
    assert result["attempts"] > 1, "self-correction loop did not fire on an unanswerable query"
    assert len(result["strategies_tried"]) > 1
    assert "does not contain" in result["answer"]
