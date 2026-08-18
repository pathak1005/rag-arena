"""Lexical retrieval (BM25) - the Elasticsearch-equivalent lane.

BM25 is the exact scoring function Elasticsearch/OpenSearch use by default, so this
lane is a faithful local stand-in for an ES cluster: same ranking maths, no cluster
to run. Swapping in a real ES client means reimplementing search() and nothing else.

It earns its place because dense retrieval is systematically bad at rare tokens:
error codes, SKUs, config keys, ticket ids. Those are most of what enterprise docs
are made of.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from app.models import RetrievedSource

_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-_.]*")

# Kept deliberately small: dropping too much hurts exact-identifier recall, which is
# the entire reason this lane exists.
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "are", "was", "were",
    "for", "on", "with", "as", "by", "at", "be", "this", "that", "it", "from",
}


def tokenize(text: str) -> list[str]:
    toks: list[str] = []
    for raw in _TOKEN.findall(text.lower()):
        if raw in _STOP:
            continue
        toks.append(raw)
        # Index sub-parts of compound identifiers too, so "checkout-api" is findable
        # by "checkout" without losing the exact-match advantage of the full token.
        if "-" in raw or "_" in raw or "." in raw:
            toks.extend(p for p in re.split(r"[-_.]", raw) if len(p) > 1)
    return toks


@dataclass
class LexicalIndex:
    chunk_ids: list[str]
    bm25: BM25Okapi | None
    doc_tokens: list[list[str]]

    @classmethod
    def empty(cls) -> "LexicalIndex":
        return cls(chunk_ids=[], bm25=None, doc_tokens=[])


def build_index(chunks: dict) -> LexicalIndex:
    ids = list(chunks.keys())
    if not ids:
        return LexicalIndex.empty()
    tokens = [tokenize(chunks[cid].text) for cid in ids]
    tokens = [t if t else ["__empty__"] for t in tokens]
    return LexicalIndex(chunk_ids=ids, bm25=BM25Okapi(tokens), doc_tokens=tokens)


def retrieve_lexical(
    index: LexicalIndex, question: str, chunks: dict, top_k: int
) -> tuple[list[RetrievedSource], dict]:
    if index.bm25 is None or not index.chunk_ids:
        return [], {"reason": "empty index"}

    q_tokens = tokenize(question)
    if not q_tokens:
        return [], {"reason": "query produced no searchable tokens"}

    scores = index.bm25.get_scores(q_tokens)
    order = sorted(range(len(scores)), key=lambda i: -scores[i])[:top_k]

    q_set = set(q_tokens)
    sources: list[RetrievedSource] = []
    for rank, idx in enumerate(order, start=1):
        if scores[idx] <= 0:
            continue
        cid = index.chunk_ids[idx]
        chunk = chunks[cid]
        matched = sorted(q_set & set(index.doc_tokens[idx]), key=lambda t: -len(t))[:6]
        sources.append(
            RetrievedSource(
                chunk_id=cid,
                doc_id=chunk.doc_id,
                doc_title=chunk.doc_title,
                rank=rank,
                score=round(float(scores[idx]), 4),
                text=chunk.text,
                why="BM25 term match on: " + (", ".join(matched) if matched else "(stemmed overlap)"),
            )
        )

    trace = {
        "query_tokens": q_tokens[:20],
        "scoring": "BM25Okapi (k1=1.5, b=0.75) - same ranking function as Elasticsearch default",
        "n_scored": len(index.chunk_ids),
        "top_score": round(float(max(scores)), 4) if len(scores) else 0.0,
    }
    return sources, trace
