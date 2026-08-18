"""Embeddings with a graceful, honest fallback.

Primary:  fastembed (ONNX runtime, no torch)  -> ~400MB container, true semantic vectors.
Fallback: TF-IDF + truncated SVD (LSA) in numpy -> zero extra deps, works offline.

The fallback is *labelled* in /health rather than hidden, because a latent-semantic
model on a small corpus is measurably weaker at paraphrase matching than a trained
sentence encoder, and pretending otherwise would corrupt the arena results.
"""
from __future__ import annotations

import logging
import math
import re
import threading
from typing import Literal

import numpy as np

from app.config import ALLOW_EMBED_DOWNLOAD, EMBED_MODEL

log = logging.getLogger("rag.embed")

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "are", "was", "were", "for",
    "on", "with", "as", "by", "at", "be", "this", "that", "it", "from", "we", "our",
    "you", "your", "how", "what", "which", "who", "when", "do", "does", "can", "should",
}


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]


class Embedder:
    """Lazy-loading, thread-safe embedder with a deterministic fallback."""

    def __init__(self) -> None:
        self.mode: Literal["fastembed", "tfidf-fallback"] = "tfidf-fallback"
        self.model_name = "tfidf-svd-128"
        self.dim = 128
        self._fe = None
        self._lock = threading.Lock()
        self._vocab: dict[str, int] = {}
        self._idf: np.ndarray | None = None
        self._components: np.ndarray | None = None
        self._fitted = False
        self._try_fastembed()

    # -- fastembed path ----------------------------------------------------
    def _try_fastembed(self) -> None:
        if not ALLOW_EMBED_DOWNLOAD:
            log.info("Embedding download disabled; using TF-IDF/SVD fallback.")
            return
        try:
            from fastembed import TextEmbedding  # type: ignore

            self._fe = TextEmbedding(model_name=EMBED_MODEL)
            probe = list(self._fe.embed(["warmup"]))[0]
            self.dim = int(len(probe))
            self.mode = "fastembed"
            self.model_name = EMBED_MODEL
            log.info("Embedder ready: %s (dim=%d)", EMBED_MODEL, self.dim)
        except Exception as exc:  # noqa: BLE001 - any failure must degrade, not crash
            log.warning("fastembed unavailable (%s); falling back to TF-IDF/SVD.", exc)
            self._fe = None

    # -- fallback path -----------------------------------------------------
    def fit(self, corpus: list[str]) -> None:
        """Fit the fallback LSA space. No-op when fastembed is active."""
        if self.mode == "fastembed" or not corpus:
            return
        with self._lock:
            docs = [tokenize(c) for c in corpus]
            vocab: dict[str, int] = {}
            for doc in docs:
                for tok in doc:
                    vocab.setdefault(tok, len(vocab))
            if not vocab:
                return
            n_docs, n_terms = len(docs), len(vocab)
            tf = np.zeros((n_docs, n_terms), dtype=np.float32)
            for i, doc in enumerate(docs):
                for tok in doc:
                    tf[i, vocab[tok]] += 1.0
            df = (tf > 0).sum(axis=0)
            idf = np.log((1 + n_docs) / (1 + df)).astype(np.float32) + 1.0
            tfidf = tf * idf
            norms = np.linalg.norm(tfidf, axis=1, keepdims=True)
            tfidf = tfidf / np.clip(norms, 1e-9, None)

            k = int(min(self.dim, max(2, min(n_docs, n_terms) - 1)))
            try:
                _, _, vt = np.linalg.svd(tfidf, full_matrices=False)
                components = vt[:k]
            except np.linalg.LinAlgError:
                rng = np.random.default_rng(0)
                components = rng.normal(size=(k, n_terms)).astype(np.float32)

            self._vocab, self._idf, self._components = vocab, idf, components.astype(np.float32)
            self.dim, self._fitted = k, True
            log.info("LSA fallback fitted: %d docs, %d terms, k=%d", n_docs, n_terms, k)

    def _fallback_embed(self, texts: list[str]) -> np.ndarray:
        if not self._fitted or self._components is None or self._idf is None:
            return np.zeros((len(texts), self.dim), dtype=np.float32)
        rows = np.zeros((len(texts), len(self._vocab)), dtype=np.float32)
        for i, text in enumerate(texts):
            for tok in tokenize(text):
                j = self._vocab.get(tok)
                if j is not None:
                    rows[i, j] += 1.0
        rows *= self._idf
        rows /= np.clip(np.linalg.norm(rows, axis=1, keepdims=True), 1e-9, None)
        out = rows @ self._components.T
        return out / np.clip(np.linalg.norm(out, axis=1, keepdims=True), 1e-9, None)

    # -- public ------------------------------------------------------------
    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        if self.mode == "fastembed" and self._fe is not None:
            vecs = np.asarray(list(self._fe.embed(texts)), dtype=np.float32)
            return vecs / np.clip(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-9, None)
        return self._fallback_embed(texts)


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder


def cosine(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """a: (d,) query, b: (n, d) matrix. Both are pre-normalised."""
    if b.size == 0:
        return np.zeros(0, dtype=np.float32)
    return b @ a
