"""ChromaDB-backed dense retrieval - the real vector database path.

Set VECTOR_BACKEND=chroma to use this instead of the in-process numpy matrix.

Two things worth understanding while learning here:

1. Embeddings are supplied explicitly rather than letting Chroma pick its own model.
   If the store embedded documents with one model and queries with another, every
   similarity score would be meaningless - and it would fail silently, returning
   plausible-looking neighbours. Owning the embedding function is not ceremony.

2. Chroma uses HNSW, an *approximate* nearest-neighbour index. It trades a small,
   usually invisible amount of recall for a large speedup. At demo scale that
   tradeoff buys nothing, which is exactly why the numpy backend exists as the
   exact-search control: run the same query against both and the delta you see is
   ANN recall loss, made visible.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.config import CHROMA_COLLECTION, CHROMA_PATH
from app.embed import get_embedder
from app.models import RetrievedSource

log = logging.getLogger("rag.chroma")


@dataclass
class ChromaIndex:
    collection: object | None
    n_vectors: int = 0

    @classmethod
    def empty(cls) -> "ChromaIndex":
        return cls(collection=None, n_vectors=0)


def _client():
    import chromadb  # optional dependency

    CHROMA_PATH.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(CHROMA_PATH))


def build_index(chunks: dict) -> ChromaIndex:
    if not chunks:
        return ChromaIndex.empty()

    embedder = get_embedder()
    ids = list(chunks.keys())
    texts = [chunks[cid].text for cid in ids]
    embedder.fit(texts)                      # no-op unless LSA fallback is active
    vectors = embedder.encode(texts)

    client = _client()
    # Rebuild rather than upsert: the corpus is small, and a stale vector left behind
    # by a partial update is far harder to notice than a slow rebuild.
    try:
        client.delete_collection(CHROMA_COLLECTION)
    except Exception:  # noqa: BLE001 - absent on first run
        pass

    collection = client.create_collection(
        name=CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine", "embedder": embedder.model_name},
    )
    collection.add(
        ids=ids,
        embeddings=[v.tolist() for v in vectors],
        documents=texts,
        metadatas=[
            {"doc_id": chunks[cid].doc_id, "doc_title": chunks[cid].doc_title,
             "ordinal": chunks[cid].ordinal}
            for cid in ids
        ],
    )
    log.info("Chroma collection '%s' built with %d vectors", CHROMA_COLLECTION, len(ids))
    return ChromaIndex(collection=collection, n_vectors=len(ids))


def retrieve_vector(
    index: ChromaIndex, question: str, chunks: dict, top_k: int
) -> tuple[list[RetrievedSource], dict]:
    if index.collection is None or index.n_vectors == 0:
        return [], {"reason": "empty collection"}

    embedder = get_embedder()
    q_vec = embedder.encode([question])[0]
    result = index.collection.query(
        query_embeddings=[q_vec.tolist()],
        n_results=min(top_k, index.n_vectors),
        include=["documents", "metadatas", "distances"],
    )

    ids = (result.get("ids") or [[]])[0]
    docs = (result.get("documents") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]
    dists = (result.get("distances") or [[]])[0]

    sources: list[RetrievedSource] = []
    for rank, (cid, doc, meta, dist) in enumerate(zip(ids, docs, metas, dists), start=1):
        similarity = 1.0 - float(dist)   # Chroma returns cosine DISTANCE, not similarity
        chunk = chunks.get(cid)
        sources.append(
            RetrievedSource(
                chunk_id=cid,
                doc_id=(meta or {}).get("doc_id", chunk.doc_id if chunk else "?"),
                doc_title=(meta or {}).get("doc_title", chunk.doc_title if chunk else "?"),
                rank=rank,
                score=round(similarity, 4),
                text=doc or (chunk.text if chunk else ""),
                why="ChromaDB HNSW cosine similarity " + format(similarity, ".3f"),
            )
        )

    trace = {
        "backend": "chromadb",
        "collection": CHROMA_COLLECTION,
        "index": "HNSW (approximate)",
        "embedder": embedder.model_name,
        "mode": embedder.mode,
        "dim": int(embedder.dim),
        "n_vectors": index.n_vectors,
    }
    return sources, trace
