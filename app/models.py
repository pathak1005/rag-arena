"""Pydantic contracts. These are the single source of truth for the OpenAPI spec.

Design rule: the UI never imports pipeline code, it only speaks these models over HTTP.
That keeps one copy of every index in one process (see README, 'Why one worker').
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Strategy(str, Enum):
    LEXICAL = "lexical"
    VECTOR = "vector"
    GRAPH = "graph"
    HYBRID = "hybrid"
    # Sequential vector -> graph pipeline (the enterprise-standard "Hybrid RAG"),
    # distinct from HYBRID which fuses independent rankings via RRF.
    HYBRID_GRAPH = "hybrid_graph"


class QueryClass(str, Enum):
    """What kind of question this is. Drives routing."""
    EXACT_IDENTIFIER = "exact_identifier"
    CONCEPTUAL = "conceptual"
    MULTI_HOP_RELATIONAL = "multi_hop_relational"
    MIXED = "mixed"


# --------------------------------------------------------------------------
# Governance
# --------------------------------------------------------------------------
class PIIEntity(BaseModel):
    entity_type: str = Field(..., description="EMAIL, PHONE, SSN, CREDIT_CARD, IP, PERSON")
    surface: str = Field(..., description="Redacted preview, never the raw value")
    start: int
    end: int
    detector: Literal["regex", "presidio"] = "regex"


class PIIReport(BaseModel):
    enabled: bool = True
    total_redacted: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)
    entities: list[PIIEntity] = Field(default_factory=list)
    chars_before: int = 0
    chars_after: int = 0


# --------------------------------------------------------------------------
# Ingestion
# --------------------------------------------------------------------------
class ChunkInfo(BaseModel):
    chunk_id: str
    doc_id: str
    doc_title: str
    ordinal: int
    text: str
    n_tokens: int


class GraphDelta(BaseModel):
    entities_added: int = 0
    relations_added: int = 0
    entities_merged: int = 0
    sample_triples: list[list[str]] = Field(default_factory=list)


class IngestResponse(BaseModel):
    doc_id: str
    title: str
    n_chunks: int
    n_tokens: int
    pii: PIIReport
    graph: GraphDelta
    brief_markdown: str = Field(..., description="Structured Content Brief, docs-as-code output")
    brief_path: str
    elapsed_ms: float


class IngestTextRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    text: str = Field(..., min_length=1)
    generate_brief: bool = True


# --------------------------------------------------------------------------
# Retrieval + answers
# --------------------------------------------------------------------------
class RetrievedSource(BaseModel):
    chunk_id: str
    doc_id: str
    doc_title: str
    rank: int
    score: float
    text: str
    why: str = Field(..., description="Human-readable reason this chunk was retrieved")
    graph_path: list[str] | None = Field(
        None, description="Entity path that reached this chunk (graph strategy only)"
    )


class EvalMetrics(BaseModel):
    """Tier-1 metrics are deterministic (no LLM). Tier-3 is LLM-judged and labelled as such."""
    groundedness: float = Field(..., ge=0, le=1, description="Tier-1: claim support vs context")
    context_relevance: float = Field(..., ge=0, le=1, description="Tier-1: query-chunk term/semantic overlap")
    entity_leakage: float = Field(
        ..., ge=0, le=1, description="Tier-1: fraction of answer entities/numbers absent from context (lower is better)"
    )
    extractiveness: float = Field(..., ge=0, le=1, description="Tier-1: longest-common-span ratio")
    citation_coverage: float = Field(..., ge=0, le=1, description="Tier-1: answer sentences with >=1 supporting chunk")
    deterministic: bool = True


class StrategyResult(BaseModel):
    strategy: Strategy
    answer: str
    sources: list[RetrievedSource]
    latency_ms: float
    retrieval_ms: float
    generation_ms: float
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    metrics: EvalMetrics
    trace: dict[str, Any] = Field(default_factory=dict, description="Strategy-specific debug info")
    degraded: bool = Field(False, description="True when the LLM was unavailable and extractive fallback ran")


class RoutingSignal(BaseModel):
    name: str
    value: str
    weight: float
    favors: Strategy


class RoutingDecision(BaseModel):
    query_class: QueryClass
    recommended: Strategy
    confidence: float = Field(..., ge=0, le=1)
    rationale: str
    signals: list[RoutingSignal]
    scores: dict[str, float]


class QueryCompareRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000)
    strategies: list[Strategy] = Field(
        default_factory=lambda: [
            Strategy.LEXICAL, Strategy.VECTOR, Strategy.GRAPH,
            Strategy.HYBRID_GRAPH, Strategy.HYBRID,
        ]
    )
    top_k: int = Field(3, ge=1, le=10)
    generate: bool = Field(True, description="Set false to benchmark retrieval only")


class QueryCompareResponse(BaseModel):
    question: str
    routing: RoutingDecision
    results: list[StrategyResult]
    winner: Strategy | None = None
    winner_reason: str = ""
    total_ms: float


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    strategy: Strategy | None = Field(None, description="Omit to let the router decide")
    top_k: int = Field(3, ge=1, le=10)


class ChatResponse(BaseModel):
    question: str
    routing: RoutingDecision
    result: StrategyResult


# --------------------------------------------------------------------------
# Graph + system
# --------------------------------------------------------------------------
class GraphNode(BaseModel):
    id: str
    label: str
    type: str
    mentions: int


class GraphEdge(BaseModel):
    source: str
    target: str
    relation: str
    confidence: float
    chunk_ids: list[str]


class GraphSnapshot(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    n_entities: int
    n_relations: int
    n_components: int = Field(..., description="Connected components. >1 means entity resolution has gaps.")
    largest_component_pct: float


class DocSummary(BaseModel):
    doc_id: str
    title: str
    n_chunks: int
    pii_redacted: int
    has_brief: bool


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    embedder: str
    embedder_mode: Literal["fastembed", "tfidf-fallback"]
    llm_available: bool
    llm_model: str
    n_documents: int
    n_chunks: int
    n_entities: int
    n_relations: int
    uptime_s: float


class ErrorResponse(BaseModel):
    error: str
    detail: str
    request_id: str


# --------------------------------------------------------------------------
# RAG-readiness analysis
# --------------------------------------------------------------------------
class ReadinessFinding(BaseModel):
    severity: Literal["high", "medium", "low"]
    dimension: str
    issue: str = Field(..., description="What is wrong")
    evidence: str = Field(..., description="The offending text, so the finding is actionable")
    fix: str = Field(..., description="What to change, and why it matters for retrieval")


class ReadinessDimension(BaseModel):
    name: str
    score: int = Field(..., ge=0, le=100)
    weight: float = Field(..., ge=0, le=1)
    summary: str


class ReadinessReport(BaseModel):
    title: str
    overall_score: int = Field(..., ge=0, le=100)
    verdict: str
    n_words: int
    n_paragraphs: int
    estimated_chunks: int
    dimensions: list[ReadinessDimension]
    findings: list[ReadinessFinding]
    predicted_retrievability: dict[str, int] = Field(
        ..., description="Predicted per-strategy retrievability, 0-100"
    )


class ReadinessRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=200_000)
    title: str = Field("Pasted content", max_length=200)


# --------------------------------------------------------------------------
# Response explanation (API playground)
# --------------------------------------------------------------------------
class Observation(BaseModel):
    verdict: Literal["good", "warning", "bad", "info"]
    field: str = Field(..., description="Which part of the response this refers to")
    observation: str
    meaning: str = Field(..., description="What it tells you about the system")


class ExplainedResponse(BaseModel):
    endpoint: str
    summary: str
    observations: list[Observation]


# --------------------------------------------------------------------------
# Multi-agent pipeline
# --------------------------------------------------------------------------
class AgentRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000)
    top_k: int = Field(3, ge=1, le=10)
    strategy: Strategy | None = Field(
        None, description="Force a lane. Omit to let the planner route and self-correct."
    )


class AgentSpan(BaseModel):
    name: str
    status: str
    duration_ms: float
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class AgentTrace(BaseModel):
    trace_id: str
    question: str
    duration_ms: float
    n_spans: int
    spans: list[AgentSpan]
    summary: dict[str, Any] = Field(default_factory=dict)
    langsmith: bool = False


class AgentResponse(BaseModel):
    question: str
    answer: str
    strategy: str | None = None
    attempts: int = Field(..., description="How many plan/retrieve/grade cycles ran")
    strategies_tried: list[str] = Field(
        default_factory=list, description="Lanes attempted, in order. Length > 1 means self-correction fired."
    )
    routing: dict[str, Any] = Field(default_factory=dict)
    sources: list[RetrievedSource] = Field(default_factory=list)
    metrics: EvalMetrics | None = None
    grade: str | None = None
    grade_reason: str = ""
    verify_reason: str = ""
    degraded: bool = False
    cost_usd: float = 0.0
    trace_id: str
    trace: AgentTrace | None = None
