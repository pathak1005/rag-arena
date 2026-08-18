"""Dense vector retrieval.

Kept intentionally thin. An in-process numpy matrix is exact (no ANN recall loss) and
is the honest choice at demo scale - a HNSW index over 200 chunks would only add
approximation error and a dependency. The swap point for ChromaDB/pgvector/Qdrant is
this module's two functions.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.embed import cosine, get_embedder
from app.models import RetrievedSource


@dataclass
class VectorIndex:
    chunk_ids: list[str]
    matrix: np.ndarray

    @classmethod
    def empty(cls) -> "VectorIndex":
        return cls(chunk_ids=[], matrix=np.zeros((0, 1), dtype=np.float32))


def build_index(chunks: dict) -> VectorIndex:
    ids = list(chunks.keys())
    if not ids:
        return VectorIndex.empty()
    embedder = get_embedder()
    texts = [chunks[cid].text for cid in ids]
    embedder.fit(texts)          # no-op unless the LSA fallback is active
    matrix = embedder.encode(texts)
    return VectorIndex(chunk_ids=ids, matrix=matrix)


def retrieve_vector(
    index: VectorIndex, question: str, chunks: dict, top_k: int
) -> tuple[list[RetrievedSource], dict]:
    if not index.chunk_ids or index.matrix.size == 0:
        return [], {"reason": "empty index"}

    embedder = get_embedder()
    q_vec = embedder.encode([question])[0]
    sims = cosine(q_vec, index.matrix)
    order = np.argsort(-sims)[:top_k]

    sources: list[RetrievedSource] = []
    for rank, idx in enumerate(order, start=1):
        cid = index.chunk_ids[int(idx)]
        chunk = chunks[cid]
        score = float(sims[int(idx)])
        sources.append(
            RetrievedSource(
                chunk_id=cid,
                doc_id=chunk.doc_id,
                doc_title=chunk.doc_title,
                rank=rank,
                score=round(score, 4),
                text=chunk.text,
                why="Semantic similarity " + format(score, ".3f") + " (cosine, no term overlap required)",
            )
        )

    trace = {
        "embedder": embedder.model_name,
        "mode": embedder.mode,
        "dim": int(embedder.dim),
        "n_vectors": len(index.chunk_ids),
        "score_spread": round(float(sims.max() - sims.min()), 4) if sims.size else 0.0,
    }
    return sources, trace
