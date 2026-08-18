"""Multi-agent RAG pipeline on LangGraph.

The agent layer earns its place through one behaviour that a linear pipeline cannot do:
**if retrieval was bad, re-route to a different strategy and try again.**

That is the direct consequence of the routing thesis. If the three strategies fail in
different, predictable places, then a grader that detects "this retrieval failed" should be
able to hand the query to the lane most likely to succeed instead - rather than letting the
generator paper over bad context with fluent prose.

    plan ──> retrieve ──> grade ──┬── (context good) ──> synthesize ──> verify ──┬─> END
              ▲                    │                                              │
              └── (bad, attempts left, different lane) ◄──────────────────────────┘
                              re-route

Five nodes, each a single responsibility:

  plan        classify the query, pick a strategy       (rule-based router, no LLM)
  retrieve    run that strategy against the chunk set   (no LLM)
  grade       is this context good enough to answer?    (deterministic, no LLM)
  synthesize  generate the answer from context          (LLM, or extractive fallback)
  verify      is the answer grounded in that context?   (deterministic, no LLM)

Only `synthesize` calls a model. Grading and verification are deterministic on purpose - an
LLM grading its own retrieval, then its own answer, compounds the same bias twice and makes
the loop unfalsifiable. See docs/DECISIONS.md D14.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Literal, TypedDict

from app.evaluate import composite, score as score_metrics
from app.llm import generate
from app.models import RetrievedSource, Strategy
from app.observability import tracer

log = logging.getLogger("rag.agent")

# Grading thresholds. Deliberately conservative: a needless retry costs one extra retrieval
# (single-digit milliseconds), while a missed retry costs a wrong answer.
MIN_CONTEXT_RELEVANCE = 0.12
MIN_SOURCES = 1
MIN_GROUNDEDNESS = 0.30
MAX_ATTEMPTS = 3

# Fallback order per strategy: what to try when this lane produced weak context.
# Ordered by how differently each lane fails - there is no point retrying with a strategy
# that fails the same way as the one that just failed.
REROUTE_ORDER: dict[str, list[str]] = {
    "graph":   ["hybrid", "vector", "lexical"],
    "vector":  ["lexical", "hybrid", "graph"],
    "lexical": ["vector", "hybrid", "graph"],
    "hybrid":  ["vector", "lexical", "graph"],
}


def _merge_attempts(left: list, right: list) -> list:
    """Reducer so parallel/looped nodes append rather than overwrite."""
    return (left or []) + (right or [])


class AgentState(TypedDict, total=False):
    question: str
    top_k: int
    strategy: str
    forced_strategy: str | None
    routing: dict[str, Any]
    sources: list[dict]
    trace: dict[str, Any]
    answer: str
    metrics: dict[str, Any]
    grade: str
    grade_reason: str
    verify_reason: str
    attempts: int
    tried: Annotated[list[str], _merge_attempts]
    history: Annotated[list[dict], _merge_attempts]
    degraded: bool
    cost_usd: float
    prompt_tokens: int
    completion_tokens: int


def build_agent(engine):
    """Compile the LangGraph state machine. `engine` is app.store.Engine."""
    from langgraph.graph import END, StateGraph

    # ---------------------------------------------------------------- plan
    def plan(state: AgentState) -> dict:
        question = state["question"]
        with tracer.span("plan", question=question) as span:
            routing = engine.routing_decision(question)
            forced = state.get("forced_strategy")
            tried = state.get("tried") or []

            if forced:
                chosen = forced
                reason = "caller forced this lane"
            elif not tried:
                chosen = routing.recommended.value
                reason = routing.rationale
            else:
                # Re-entry after a failed grade: pick the best lane not yet attempted.
                last = tried[-1]
                candidates = [s for s in REROUTE_ORDER.get(last, []) if s not in tried]
                chosen = candidates[0] if candidates else last
                reason = (
                    "re-routing after weak context from '" + last + "'; "
                    + chosen + " fails differently, so it is the useful next attempt"
                )

            span.outputs = {
                "strategy": chosen,
                "confidence": routing.confidence,
                "query_class": routing.query_class.value,
                "attempt": len(tried) + 1,
            }
            span.notes.append(reason)

        return {
            "strategy": chosen,
            "routing": routing.model_dump(),
            "attempts": state.get("attempts", 0) + 1,
            "tried": [chosen],
        }

    # ------------------------------------------------------------ retrieve
    def retrieve(state: AgentState) -> dict:
        strategy = Strategy(state["strategy"])
        with tracer.span("retrieve", strategy=strategy.value, top_k=state["top_k"]) as span:
            sources, trace, elapsed = engine._retrieve(strategy, state["question"], state["top_k"])
            span.outputs = {
                "n_sources": len(sources),
                "retrieval_ms": round(elapsed, 2),
                "documents": sorted({s.doc_title for s in sources}),
            }
            if not sources:
                span.notes.append("no chunks retrieved - grader will force a re-route")
        return {
            "sources": [s.model_dump() for s in sources],
            "trace": trace,
        }

    # --------------------------------------------------------------- grade
    def grade(state: AgentState) -> dict:
        """Corrective-RAG style gate, computed deterministically.

        Grades the CONTEXT, before any generation. Catching a bad retrieval here avoids
        paying for a generation that was doomed, and avoids producing a fluent answer built
        on irrelevant passages - which is far more dangerous than an obvious failure.
        """
        sources = [RetrievedSource(**s) for s in state.get("sources", [])]
        with tracer.span("grade", n_sources=len(sources)) as span:
            if len(sources) < MIN_SOURCES:
                verdict, reason = "insufficient", "retrieval returned no chunks"
            else:
                probe = score_metrics(state["question"], " ".join(s.text for s in sources), sources)
                relevance = probe.context_relevance
                if relevance < MIN_CONTEXT_RELEVANCE:
                    verdict = "insufficient"
                    reason = (
                        "context relevance " + format(relevance, ".3f") + " is below "
                        + format(MIN_CONTEXT_RELEVANCE, ".2f") + " - the retrieved chunks are "
                        "off-topic, so this is a retrieval failure, not a generation problem"
                    )
                else:
                    verdict = "sufficient"
                    reason = "context relevance " + format(relevance, ".3f") + " is adequate"
            span.outputs = {"grade": verdict}
            span.notes.append(reason)
        return {"grade": verdict, "grade_reason": reason}

    def route_after_grade(state: AgentState) -> Literal["synthesize", "plan"]:
        if state.get("grade") == "sufficient":
            return "synthesize"
        if state.get("attempts", 0) >= MAX_ATTEMPTS or state.get("forced_strategy"):
            # Out of retries: answer from what we have. The verifier will flag it, and an
            # honestly-flagged weak answer beats an infinite loop.
            return "synthesize"
        return "plan"

    # ---------------------------------------------------------- synthesize
    def synthesize(state: AgentState) -> dict:
        sources = [RetrievedSource(**s) for s in state.get("sources", [])]
        with tracer.span("synthesize", strategy=state["strategy"], n_sources=len(sources)) as span:
            completion = generate(state["question"], [s.text for s in sources])
            span.outputs = {
                "model": completion.model,
                "generation_ms": completion.latency_ms,
                "completion_tokens": completion.completion_tokens,
                "cost_usd": completion.cost_usd,
            }
            if completion.degraded:
                span.notes.append("LLM unavailable - deterministic extractive fallback used")
        return {
            "answer": completion.text,
            "degraded": completion.degraded,
            "cost_usd": completion.cost_usd,
            "prompt_tokens": completion.prompt_tokens,
            "completion_tokens": completion.completion_tokens,
        }

    # -------------------------------------------------------------- verify
    def verify(state: AgentState) -> dict:
        sources = [RetrievedSource(**s) for s in state.get("sources", [])]
        with tracer.span("verify") as span:
            metrics = score_metrics(state["question"], state.get("answer", ""), sources)
            overall = composite(metrics)
            problems = []
            if metrics.groundedness < MIN_GROUNDEDNESS:
                problems.append("groundedness " + format(metrics.groundedness, ".2f") + " is low")
            if metrics.entity_leakage > 0.25:
                problems.append(
                    "entity leakage " + format(metrics.entity_leakage, ".2f")
                    + " - the answer asserts identifiers absent from the retrieved context"
                )
            reason = "; ".join(problems) if problems else "answer is grounded in the retrieved context"
            span.outputs = {
                "composite": overall,
                "groundedness": metrics.groundedness,
                "entity_leakage": metrics.entity_leakage,
                "passed": not problems,
            }
            span.notes.append(reason)
        return {"metrics": metrics.model_dump(), "verify_reason": reason}

    # ------------------------------------------------------------- assemble
    workflow = StateGraph(AgentState)
    workflow.add_node("plan", plan)
    workflow.add_node("retrieve", retrieve)
    workflow.add_node("grade", grade)
    workflow.add_node("synthesize", synthesize)
    workflow.add_node("verify", verify)

    workflow.set_entry_point("plan")
    workflow.add_edge("plan", "retrieve")
    workflow.add_edge("retrieve", "grade")
    workflow.add_conditional_edges("grade", route_after_grade,
                                   {"synthesize": "synthesize", "plan": "plan"})
    workflow.add_edge("synthesize", "verify")
    workflow.add_edge("verify", END)

    return workflow.compile()


_agent = None


def get_agent(engine):
    global _agent
    if _agent is None:
        _agent = build_agent(engine)
    return _agent


def run_agent(engine, question: str, top_k: int = 3, forced_strategy: str | None = None) -> dict:
    agent = get_agent(engine)
    trace = tracer.start_trace(question)

    initial: AgentState = {
        "question": question,
        "top_k": top_k,
        "forced_strategy": forced_strategy,
        "attempts": 0,
        "tried": [],
        "history": [],
    }
    # recursion_limit guards against a cycle bug turning into an unbounded LLM spend.
    final = agent.invoke(initial, config={"recursion_limit": 25})

    tracer.end_trace(
        strategy=final.get("strategy"),
        attempts=final.get("attempts", 1),
        tried=final.get("tried", []),
        degraded=final.get("degraded", False),
    )

    return {
        "question": question,
        "answer": final.get("answer", ""),
        "strategy": final.get("strategy"),
        "attempts": final.get("attempts", 1),
        "strategies_tried": final.get("tried", []),
        "routing": final.get("routing", {}),
        "sources": final.get("sources", []),
        "metrics": final.get("metrics", {}),
        "grade": final.get("grade"),
        "grade_reason": final.get("grade_reason", ""),
        "verify_reason": final.get("verify_reason", ""),
        "degraded": final.get("degraded", False),
        "cost_usd": final.get("cost_usd", 0.0),
        "trace_id": trace.trace_id,
        "trace": tracer.get(trace.trace_id),
    }
