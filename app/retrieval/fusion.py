"""Reciprocal Rank Fusion.

score(chunk) = sum over retrievers of 1 / (k + rank)

Rank-based rather than score-based on purpose: BM25 scores are unbounded, cosine is
[-1,1], and graph scores are arbitrary hop-decay units. Normalising those onto a
common scale requires assumptions that break the moment the corpus changes; ranks
need none. k=60 is the constant from Cormack et al. (2009) and is not sensitive.
"""
from __future__ import annotations

from app.config import RRF_K
from app.models import RetrievedSource


def reciprocal_rank_fusion(
    ranked_lists: dict[str, list[RetrievedSource]], top_k: int, k: int = RRF_K
) -> tuple[list[RetrievedSource], dict]:
    fused: dict[str, float] = {}
    provenance: dict[str, list[str]] = {}
    lookup: dict[str, RetrievedSource] = {}

    for strategy, sources in ranked_lists.items():
        for source in sources:
            contribution = 1.0 / (k + source.rank)
            fused[source.chunk_id] = fused.get(source.chunk_id, 0.0) + contribution
            provenance.setdefault(source.chunk_id, []).append(
                strategy + "#" + str(source.rank)
            )
            lookup.setdefault(source.chunk_id, source)

    ordered = sorted(fused.items(), key=lambda kv: -kv[1])[:top_k]

    out: list[RetrievedSource] = []
    for rank, (chunk_id, score) in enumerate(ordered, start=1):
        base = lookup[chunk_id]
        agreeing = provenance[chunk_id]
        out.append(
            RetrievedSource(
                chunk_id=chunk_id,
                doc_id=base.doc_id,
                doc_title=base.doc_title,
                rank=rank,
                score=round(score, 5),
                text=base.text,
                why="RRF over " + str(len(agreeing)) + " retriever(s): " + ", ".join(agreeing),
                graph_path=base.graph_path,
            )
        )

    consensus = sum(1 for v in provenance.values() if len(v) > 1)
    trace = {
        "k": k,
        "lists_fused": list(ranked_lists.keys()),
        "unique_chunks": len(fused),
        "multi_retriever_agreement": consensus,
        "provenance": {cid: provenance[cid] for cid, _ in ordered},
    }
    return out, trace
