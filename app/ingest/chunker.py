"""Chunking. One chunk table, shared by all three retrievers.

This is the load-bearing decision of the whole system: because every retriever
selects from the same immutable chunk set, a score difference between strategies
is attributable to retrieval alone, not to chunking or prompt drift.
"""
from __future__ import annotations

import hashlib
import re

from app.config import CHUNK_OVERLAP, CHUNK_TOKENS
from app.models import ChunkInfo

_WS = re.compile(r"\s+")
_PARA = re.compile(r"\n\s*\n")


def approx_tokens(text: str) -> int:
    """Cheap token estimate; avoids shipping a tokenizer just for budget maths."""
    return max(1, len(text) // 4)


def _words(text: str) -> list[str]:
    return _WS.sub(" ", text).strip().split(" ")


def chunk_document(doc_id: str, title: str, text: str) -> list[ChunkInfo]:
    """Paragraph-aware sliding window.

    Paragraph boundaries are respected where possible because the graph extractor
    works far better on complete sentences than on mid-sentence fragments.
    """
    paragraphs = [p.strip() for p in _PARA.split(text) if p.strip()]
    if not paragraphs:
        return []

    target_words = max(20, CHUNK_TOKENS * 3 // 4)
    overlap_words = max(0, CHUNK_OVERLAP * 3 // 4)

    chunks: list[ChunkInfo] = []
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        body = " ".join(buffer).strip()
        if not body:
            return
        ordinal = len(chunks)
        digest = hashlib.sha1(f"{doc_id}:{ordinal}:{body[:64]}".encode()).hexdigest()[:10]
        chunks.append(
            ChunkInfo(
                chunk_id=f"{doc_id}::c{ordinal:03d}::{digest}",
                doc_id=doc_id,
                doc_title=title,
                ordinal=ordinal,
                text=body,
                n_tokens=approx_tokens(body),
            )
        )

    for para in paragraphs:
        para_words = _words(para)
        if len(buffer) + len(para_words) <= target_words:
            buffer.extend(para_words)
            continue
        if buffer:
            flush()
            buffer = buffer[-overlap_words:] if overlap_words else []
        # A single oversized paragraph still has to be split.
        while len(para_words) > target_words:
            buffer.extend(para_words[:target_words])
            flush()
            buffer = buffer[-overlap_words:] if overlap_words else []
            para_words = para_words[target_words:]
        buffer.extend(para_words)

    flush()
    return chunks
