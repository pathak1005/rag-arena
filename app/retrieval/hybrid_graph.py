"""Hybrid RAG: vector retrieval seeds the graph, graph traversal expands the evidence.

This is the pattern most enterprise deployments converge on, and it is different from the
RRF `hybrid` lane. RRF runs three retrievers independently and fuses their *rankings*.
Hybrid RAG runs them in *sequence*, so each stage does the job it is actually good at:

    stage 1  vector search      -> "which passages are semantically about this question?"
    stage 2  chunk -> entities  -> "what things are named in those passages?"
    stage 3  graph traversal    -> "what is connected to those things?"
    stage 4  entities -> chunks -> "what passages describe those connections?"
    stage 5  merge + rank       -> semantic seeds and relational evidence, scored together

Why the sequence beats either lane alone:

- Pure vector retrieval finds the passage that *sounds like* the question, then stops. It
  cannot follow "and who owns that?" into a document that never mentions the question's
  vocabulary.
- Pure graph retrieval needs an entity mention in the question to seed traversal. Ask it
  something phrased conceptually and `link_query` returns nothing, so the lane returns
  nothing. Vector seeding removes that dependency entirely - the *passage* supplies the
  entities the question failed to name.

The second point is the one that matters in practice. It converts graph retrieval from
"works when the user names an entity" into "works on natural language", which is the
difference between a demo and a product.

Equivalent to the `Neo4jVector(retrieval_query=...)` pattern in LangChain, implemented
here directly so it works against both the NetworkX and Neo4j backends.
"""
from __future__ import annotations

import logging
import math

from app.models import RetrievedSource
from app.retrieval.graph import _terms

log = logging.getLogger("rag.hybrid")

# How many semantic seeds to expand from. More seeds means broader traversal and more
# noise; 5 was the point where extra seeds stopped changing the top-3 on the demo corpus.
SEED_CHUNKS = 5

# Cap seeds per source document. A block of near-identical chunks from one document
# would otherwise consume every seed slot and confine traversal to one neighbourhood.
MAX_SEEDS_PER_DOC = 2

# Expanded (relational) evidence is discounted against direct semantic hits. A chunk found
# by traversal is *contextually* relevant, not *semantically* matched, and conflating the
# two lets weakly-related neighbours outrank a direct answer.
# Weight of the relational list in the rank fusion, relative to the semantic list.
# Below 1.0 because a traversal hit is contextually relevant, not semantically matched.
EXPANSION_WEIGHT = 0.9


def _idf_table(store, chunks: dict) -> dict[str, float]:
    cached = getattr(store, "_idf_cache", None)
    if cached is not None and cached[0] == len(chunks):
        return cached[1]
    n_docs = max(1, len(chunks))
    df: dict[str, int] = {}
    for chunk in chunks.values():
        for term in _terms(chunk.text):
            df[term] = df.get(term, 0) + 1
    idf = {t: math.log(1.0 + (n_docs - c + 0.5) / (c + 0.5)) for t, c in df.items()}
    store._idf_cache = (len(chunks), idf)
    return idf


def _entities_in_chunk(store, chunk_id: str) -> set[str]:
    """Reverse the MENTIONED_IN edge: which entities does this chunk mention?"""
    cached = getattr(store, "chunk_entities", None)
    if cached is not None and chunk_id in cached:
        return set(cached[chunk_id])
    # Neo4j backend keeps chunk_ids on the cached Entity objects instead.
    return {eid for eid, ent in store.entities.items() if chunk_id in ent.chunk_ids}


def retrieve_hybrid_graph(
    vector_module,
    vector_index,
    store,
    question: str,
    chunks: dict,
    top_k: int,
    max_hops: int,
) -> tuple[list[RetrievedSource], dict]:
    # ---- stage 1: semantic seeds (diversified) ---------------------------
    # Over-fetch, then cap per document. Without the cap all five seeds came from the
    # 33-entry error-code reference - the chunks are near-identical, so they occupy every
    # top slot and traversal then expands from one corner of the graph. Seed diversity
    # matters more here than seed precision: this stage picks where traversal *starts*.
    raw_seeds, vector_trace = vector_module.retrieve_vector(
        vector_index, question, chunks, SEED_CHUNKS * 4
    )
    if not raw_seeds:
        return [], {"reason": "vector stage returned nothing", "stage_failed": "vector_seed"}

    per_doc: dict[str, int] = {}
    seed_sources = []
    for source in raw_seeds:
        if per_doc.get(source.doc_id, 0) >= MAX_SEEDS_PER_DOC:
            continue
        per_doc[source.doc_id] = per_doc.get(source.doc_id, 0) + 1
        source.rank = len(seed_sources) + 1
        seed_sources.append(source)
        if len(seed_sources) >= SEED_CHUNKS:
            break

    semantic_rank = {s.chunk_id: s.rank for s in seed_sources}
    semantic_score = {s.chunk_id: float(s.score) for s in seed_sources}

    # ---- stage 2: seed chunks -> entities ---------------------------------
    seed_entities: dict[str, float] = {}
    for source in seed_sources:
        for ent_id in _entities_in_chunk(store, source.chunk_id):
            # An entity named in a strongly-matching passage is a stronger seed than one
            # named in a weak passage, so traversal strength inherits the vector score.
            seed_entities[ent_id] = max(seed_entities.get(ent_id, 0.0), float(source.score))

    # The question may also name entities directly. Those are stronger seeds than
    # anything inferred from a passage, so they override rather than merge.
    for ent_id, strength in store.link_query(question):
        seed_entities[ent_id] = max(seed_entities.get(ent_id, 0.0), strength)

    if not seed_entities:
        for source in seed_sources[:top_k]:
            source.why = "Semantic match (graph expansion found no entities to traverse)"
        return seed_sources[:top_k], {
            **vector_trace,
            "mode": "hybrid_graph",
            "stages": ["vector_seed"],
            "note": "no entities in the seed passages; degraded to pure vector",
        }

    # ---- stage 3 + 4: traverse, then map entities back to chunks ----------
    ranked_seeds = sorted(seed_entities.items(), key=lambda kv: -kv[1])[:8]
    reach = store.traverse(ranked_seeds, max_hops)

    idf = _idf_table(store, chunks)
    q_terms = {t for t in _terms(question) if t in idf}
    q_mass = sum(idf[t] for t in q_terms) or 1.0

    expansion_candidates: list[tuple[str, float, dict]] = []
    for chunk_id, info in reach.items():
        chunk = chunks.get(chunk_id)
        if chunk is None:
            continue
        hops = int(info.get("hops", 0))

        # A seed chunk is trivially reachable at 0 hops from entities it itself mentions.
        # Counting that as corroboration is circular - it inflated every seed and let a
        # block of near-identical error-code chunks crowd out the real answer. Only
        # genuine traversal (>= 1 hop) counts as relational evidence.
        if hops == 0 and chunk_id in semantic_rank:
            continue

        matched = q_terms & _terms(chunk.text)
        relevance = sum(idf[t] for t in matched) / q_mass
        # NOTE: store.traverse() already applies hop decay and entity-saturation
        # normalisation to info["score"]. Applying HOP_DECAY again here double-penalised
        # every multi-hop result - which is precisely the evidence this lane exists to
        # surface. Only the relevance factor is applied on top.
        strength = float(info["score"]) * (0.15 + 0.85 * relevance)
        expansion_candidates.append((chunk_id, strength, {"hops": hops, "path": info.get("path") or []}))

    expansion_candidates.sort(key=lambda row: -row[1])
    expansion_rank = {cid: i + 1 for i, (cid, _, _) in enumerate(expansion_candidates)}
    expansion_meta = {cid: meta for cid, _, meta in expansion_candidates}

    # ---- stage 5: rank-based fusion --------------------------------------
    # Fuse by RANK, not by score. Cosine similarity, hop decay and IDF relevance live on
    # incommensurable scales, and normalising them requires assumptions that break the
    # moment the corpus changes. Ranks need none. Same reasoning as fusion.py.
    K = 20
    fused: dict[str, float] = {}
    for chunk_id, rank in semantic_rank.items():
        fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (K + rank)
    for chunk_id, rank in expansion_rank.items():
        fused[chunk_id] = fused.get(chunk_id, 0.0) + EXPANSION_WEIGHT / (K + rank)

    # Appearing in both lists is the strongest signal available: semantically on-topic AND
    # structurally connected. Applied as a multiplier so it re-orders without swamping.
    both = set(semantic_rank) & set(expansion_rank)
    for chunk_id in both:
        fused[chunk_id] *= 1.35

    ordered = sorted(fused.items(), key=lambda kv: -kv[1])[:top_k]

    sources: list[RetrievedSource] = []
    origins: list[str] = []
    for rank, (chunk_id, score) in enumerate(ordered, start=1):
        chunk = chunks.get(chunk_id)
        if chunk is None:
            continue
        meta = expansion_meta.get(chunk_id, {})
        in_sem, in_exp = chunk_id in semantic_rank, chunk_id in expansion_rank

        if in_sem and in_exp:
            origin = "semantic+relational"
            why = (
                "Confirmed by both stages: semantic match (cosine "
                + format(semantic_score.get(chunk_id, 0.0), ".3f") + ") and "
                + str(meta.get("hops", "?")) + "-hop graph connection"
            )
        elif in_exp:
            origin = "relational"
            why = (
                "Relational evidence only - vector search missed this. Reached in "
                + str(meta.get("hops", "?")) + " hop(s): " + " ".join(meta.get("path", []))
            )
        else:
            origin = "semantic"
            why = "Semantic seed - cosine " + format(semantic_score.get(chunk_id, 0.0), ".3f")

        origins.append(origin)
        sources.append(
            RetrievedSource(
                chunk_id=chunk_id,
                doc_id=chunk.doc_id,
                doc_title=chunk.doc_title,
                rank=rank,
                score=round(float(score), 5),
                text=chunk.text,
                why=why,
                graph_path=meta.get("path") or None,
            )
        )
    trace = {
        "mode": "hybrid_graph",
        "stages": ["vector_seed", "chunk_to_entity", "graph_traverse", "entity_to_chunk", "merge"],
        "seed_chunks": len(seed_sources),
        "seed_entities": [
            {"entity": store.entities[e].label, "strength": round(s, 3)}
            for e, s in ranked_seeds
            if e in store.entities
        ],
        "chunks_reached_by_traversal": len(reach),
        "expansion_candidates": len(expansion_candidates),
        "candidates_merged": len(fused),
        "result_origins": origins,
        "confirmed_by_both": sum(1 for o in origins if o == "semantic+relational"),
        "embedder": vector_trace.get("embedder"),
        "max_hops": max_hops,
    }
    return sources, trace
