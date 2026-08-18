"""In-process corpus store and pipeline orchestration.

Everything lives in one process's memory on purpose: at demo scale it is exact, fast,
and has no external dependency to misconfigure. The cost is stated plainly in the
README - single uvicorn worker, state lost on restart - along with the two swaps
(persistent Chroma, Neo4j) that remove the limitation when it starts to matter.
"""
from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field

from app.config import (
    BRIEF_DIR,
    GRAPH_BACKEND,
    GRAPH_MAX_HOPS,
    NEO4J_DATABASE,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
    PII_ENABLED,
    TOP_K,
    VECTOR_BACKEND,
)
from app.evaluate import composite, score as score_metrics
from app.governance.pii import scrub
from app.ingest.brief import build_brief
from app.ingest.chunker import chunk_document
from app.llm import generate
from app.models import (
    ChunkInfo,
    DocSummary,
    GraphDelta,
    IngestResponse,
    QueryCompareResponse,
    RetrievedSource,
    RoutingDecision,
    Strategy,
    StrategyResult,
)
from app.retrieval import lexical, vector
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.graph import GraphStore, extract_mentions, extract_triples, retrieve_graph
from app.retrieval.hybrid_graph import retrieve_hybrid_graph
from app.retrieval.router import route

log = logging.getLogger("rag.store")


@dataclass
class Document:
    doc_id: str
    title: str
    raw_text: str
    clean_text: str
    chunk_ids: list[str] = field(default_factory=list)
    pii_redacted: int = 0
    brief_path: str | None = None


def _make_graph_store() -> tuple[object, str]:
    """Select the graph backend. Falls back to NetworkX rather than failing to boot -
    a demo that dies because a database is asleep is worse than a degraded demo."""
    if GRAPH_BACKEND.lower() == "neo4j":
        try:
            from app.retrieval.graph_neo4j import Neo4jGraphStore

            store = Neo4jGraphStore(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_DATABASE)
            log.info("Graph backend: Neo4j at %s", NEO4J_URI)
            return store, "neo4j"
        except Exception as exc:  # noqa: BLE001
            log.error("Neo4j unavailable (%s) - falling back to NetworkX.", exc)
    return GraphStore(), "networkx"


def _vector_module():
    if VECTOR_BACKEND.lower() == "chroma":
        try:
            from app.retrieval import vector_chroma

            import chromadb  # noqa: F401  - fail fast here, not mid-ingest
            log.info("Vector backend: ChromaDB")
            return vector_chroma, "chroma"
        except Exception as exc:  # noqa: BLE001
            log.error("ChromaDB unavailable (%s) - falling back to numpy exact search.", exc)
    return vector, "numpy"


class Engine:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.documents: dict[str, Document] = {}
        self.chunks: dict[str, ChunkInfo] = {}
        self.graph, self.graph_backend = _make_graph_store()
        self._vector_mod, self.vector_backend = _vector_module()
        self.lexical_index = lexical.LexicalIndex.empty()
        self.vector_index = self._vector_mod.build_index({})
        self.started_at = time.time()
        BRIEF_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------
    def ingest(self, title: str, text: str, generate_brief: bool = True) -> IngestResponse:
        start = time.perf_counter()
        with self.lock:
            doc_id = "doc_" + uuid.uuid4().hex[:8]

            # 1. Governance FIRST. Nothing downstream ever sees raw PII.
            clean_text, pii_report = scrub(text, enabled=PII_ENABLED)

            # 2. Chunk once. All three retrievers share this exact set.
            chunks = chunk_document(doc_id, title, clean_text)
            if not chunks:
                raise ValueError("Document produced no chunks; it may be empty after redaction.")

            # 3. Graph extraction over the same chunks.
            self.graph.reset_delta()
            all_triples = []
            register = getattr(self.graph, "register_chunk", None)
            for chunk in chunks:
                self.chunks[chunk.chunk_id] = chunk
                if register is not None:   # Neo4j materialises Chunk nodes; NetworkX does not
                    register(chunk.chunk_id, chunk.doc_id, chunk.doc_title)
                triples = extract_triples(chunk.chunk_id, chunk.text)
                all_triples.extend(triples)
                for triple in triples:
                    self.graph.add_triple(triple)
                # Mentions give chunks graph-reachability even without a parsed relation.
                for surface in extract_mentions(chunk.text):
                    self.graph.add_mention(surface, chunk.chunk_id)

            delta = GraphDelta(
                entities_added=self.graph.stats["entities_added"],
                relations_added=self.graph.stats["relations_added"],
                entities_merged=self.graph.stats["entities_merged"],
                sample_triples=[[t.subject, t.relation, t.obj] for t in all_triples[:8]],
            )

            doc = Document(
                doc_id=doc_id,
                title=title,
                raw_text=text,
                clean_text=clean_text,
                chunk_ids=[c.chunk_id for c in chunks],
                pii_redacted=pii_report.total_redacted,
            )
            self.documents[doc_id] = doc

            # 4. Rebuild flat indexes. O(n) rebuild is correct at this scale and avoids
            #    a whole class of incremental-update bugs.
            self._rebuild_indexes()

            # 5. Content brief.
            brief_md = ""
            brief_path = ""
            if generate_brief:
                brief_md = build_brief(title, doc_id, text, chunks, pii_report, all_triples, use_llm=True)
                safe = re.sub(r"[^a-zA-Z0-9_\-]+", "_", title)[:50] or "document"
                path = BRIEF_DIR / (doc_id + "_" + safe + ".md")
                path.write_text(brief_md, encoding="utf-8")
                brief_path = str(path)
                doc.brief_path = brief_path

            elapsed = (time.perf_counter() - start) * 1000
            return IngestResponse(
                doc_id=doc_id,
                title=title,
                n_chunks=len(chunks),
                n_tokens=sum(c.n_tokens for c in chunks),
                pii=pii_report,
                graph=delta,
                brief_markdown=brief_md,
                brief_path=brief_path,
                elapsed_ms=round(elapsed, 2),
            )

    def _rebuild_indexes(self) -> None:
        self.lexical_index = lexical.build_index(self.chunks)
        self.vector_index = self._vector_mod.build_index(self.chunks)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def _retrieve(
        self, strategy: Strategy, question: str, top_k: int
    ) -> tuple[list[RetrievedSource], dict, float]:
        start = time.perf_counter()
        if strategy is Strategy.LEXICAL:
            sources, trace = lexical.retrieve_lexical(self.lexical_index, question, self.chunks, top_k)
        elif strategy is Strategy.VECTOR:
            sources, trace = self._vector_mod.retrieve_vector(
                self.vector_index, question, self.chunks, top_k
            )
        elif strategy is Strategy.GRAPH:
            sources, trace = retrieve_graph(self.graph, question, self.chunks, top_k, GRAPH_MAX_HOPS)
        elif strategy is Strategy.HYBRID_GRAPH:
            sources, trace = retrieve_hybrid_graph(
                self._vector_mod, self.vector_index, self.graph,
                question, self.chunks, top_k, GRAPH_MAX_HOPS,
            )
        elif strategy is Strategy.HYBRID:
            lex, _ = lexical.retrieve_lexical(self.lexical_index, question, self.chunks, top_k * 2)
            vec, _ = self._vector_mod.retrieve_vector(
                self.vector_index, question, self.chunks, top_k * 2
            )
            gra, _ = retrieve_graph(self.graph, question, self.chunks, top_k * 2, GRAPH_MAX_HOPS)
            sources, trace = reciprocal_rank_fusion(
                {"lexical": lex, "vector": vec, "graph": gra}, top_k
            )
        else:
            sources, trace = [], {"reason": "unknown strategy"}
        return sources, trace, (time.perf_counter() - start) * 1000

    def run_strategy(
        self, strategy: Strategy, question: str, top_k: int, do_generate: bool = True
    ) -> StrategyResult:
        sources, trace, retrieval_ms = self._retrieve(strategy, question, top_k)
        context_blocks = [s.text for s in sources]

        if do_generate:
            completion = generate(question, context_blocks)
            answer, gen_ms = completion.text, completion.latency_ms
            p_tok, c_tok = completion.prompt_tokens, completion.completion_tokens
            cost, degraded = completion.cost_usd, completion.degraded
        else:
            answer, gen_ms, p_tok, c_tok, cost, degraded = "", 0.0, 0, 0, 0.0, False

        metrics = score_metrics(question, answer, sources)
        return StrategyResult(
            strategy=strategy,
            answer=answer,
            sources=sources,
            latency_ms=round(retrieval_ms + gen_ms, 2),
            retrieval_ms=round(retrieval_ms, 2),
            generation_ms=round(gen_ms, 2),
            prompt_tokens=p_tok,
            completion_tokens=c_tok,
            cost_usd=cost,
            metrics=metrics,
            trace=trace,
            degraded=degraded,
        )

    def routing_decision(self, question: str) -> RoutingDecision:
        seeds = self.graph.link_query(question)
        labels = [self.graph.entities[e].label for e, _ in seeds]
        return route(question, labels, graph_ready=bool(self.graph.entities))

    def compare(
        self, question: str, strategies: list[Strategy], top_k: int = TOP_K, do_generate: bool = True
    ) -> QueryCompareResponse:
        start = time.perf_counter()
        routing = self.routing_decision(question)

        results = [self.run_strategy(s, question, top_k, do_generate) for s in strategies]

        winner: Strategy | None = None
        winner_reason = ""
        scored = [(composite(r.metrics), r) for r in results if r.sources]
        if scored:
            scored.sort(key=lambda pair: -pair[0])
            best_score, best = scored[0]
            winner = best.strategy
            runner_up = scored[1][0] if len(scored) > 1 else 0.0
            gap = best_score - runner_up
            winner_reason = (
                best.strategy.value + " scores " + format(best_score, ".3f") + " on the composite "
                "(groundedness, context relevance, entity leakage, citation coverage)"
                + (
                    ", a decisive margin of " + format(gap, ".3f") + " over the next strategy."
                    if gap >= 0.05
                    else " - but the margin over the next strategy is only "
                    + format(gap, ".3f")
                    + ", which is inside noise. Treat this as a tie."
                )
            )

        return QueryCompareResponse(
            question=question,
            routing=routing,
            results=results,
            winner=winner,
            winner_reason=winner_reason,
            total_ms=round((time.perf_counter() - start) * 1000, 2),
        )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    def doc_summaries(self) -> list[DocSummary]:
        return [
            DocSummary(
                doc_id=d.doc_id,
                title=d.title,
                n_chunks=len(d.chunk_ids),
                pii_redacted=d.pii_redacted,
                has_brief=bool(d.brief_path),
            )
            for d in self.documents.values()
        ]

    def reset(self) -> None:
        with self.lock:
            self.documents.clear()
            self.chunks.clear()
            clear = getattr(self.graph, 'clear', None)
            if clear is not None:
                clear()          # Neo4j is persistent; wipe it rather than orphan it
            else:
                self.graph = GraphStore()
            self._rebuild_indexes()


_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = Engine()
    return _engine
