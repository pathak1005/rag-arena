"""Tier-1 evaluation: deterministic, no LLM in the loop.

Every metric here is reproducible - same inputs, same number, every run, no API key
required. That is the point. Using llama-3.3-70b to grade llama-3.3-70b's own output
is neither independent nor deterministic, and any reviewer will say so within a
minute, so the honest metrics come first and LLM-judged scoring is a clearly
labelled separate tier.

What these do and do not prove:
  groundedness      - content words in the answer that are supported by context.
                      Catches confabulated specifics. Does NOT catch a fluent
                      answer that reuses context words in a wrong relationship.
  entity_leakage    - numbers/identifiers/proper nouns asserted but absent from
                      context. The sharpest hallucination signal here, because
                      fabricated specifics are what actually hurt users.
  context_relevance - did retrieval even fetch something on-topic. Isolates
                      retrieval failure from generation failure.
  extractiveness    - how much is copied verbatim. High is safe but may mean the
                      model is parroting; low with high groundedness is ideal.
  citation_coverage - fraction of answer sentences with a supporting chunk.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.models import EvalMetrics, RetrievedSource

_WORD = re.compile(r"[A-Za-z][A-Za-z\-']+|\d+(?:\.\d+)?")
_SENT = re.compile(r"(?<=[.!?])\s+")

_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "are", "was", "were", "for",
    "on", "with", "as", "by", "at", "be", "this", "that", "it", "from", "we", "our",
    "you", "your", "they", "their", "there", "here", "which", "who", "what", "when",
    "how", "why", "can", "should", "would", "will", "may", "must", "not", "no", "yes",
    "if", "then", "than", "but", "also", "into", "about", "based", "provided",
    "context", "according", "documents", "document", "answer", "however", "these",
    "those", "such", "its", "has", "have", "had", "does", "do", "did", "been", "being",
}

# Things a model should never invent: identifiers, codes, numbers, proper nouns.
_SPECIFIC = [
    re.compile(r"\bERR-\d{3,5}\b", re.I),
    re.compile(r"\b[A-Z]{2,}[-_]\d{2,}\b"),
    re.compile(r"\b\d+(?:\.\d+)?%?\b"),
    re.compile(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b"),
    re.compile(r"#[a-z0-9\-]{3,30}\b"),
    re.compile(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+){1,3}\b"),
]

_REFUSAL = re.compile(
    r"\b(?:not\s+(?:in|found|present|available|contained)|does\s?n[o']t\s+contain|"
    r"cannot\s+(?:be\s+)?(?:answer|determin|find)|no\s+(?:relevant\s+)?(?:information|context)|"
    r"insufficient\s+(?:context|information))\b",
    re.I,
)


def _content_words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text) if w.lower() not in _STOP and len(w) > 2]


def _specifics(text: str) -> set[str]:
    out: set[str] = set()
    for pattern in _SPECIFIC:
        for m in pattern.finditer(text):
            token = m.group(0).strip().lower()
            if token and token not in _STOP:
                out.add(token)
    return out


def _longest_common_span_ratio(answer: str, context: str) -> float:
    if not answer or not context:
        return 0.0
    a_words = answer.lower().split()
    c_words = context.lower().split()
    if not a_words:
        return 0.0
    matcher = SequenceMatcher(None, a_words, c_words, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return min(1.0, matched / len(a_words))


def score(question: str, answer: str, sources: list[RetrievedSource]) -> EvalMetrics:
    context = "\n".join(s.text for s in sources)

    # An honest "I don't know" is a correct, grounded output - not a hallucination.
    # Scoring it as ungrounded would reward models that bluff, which is backwards.
    if not answer.strip():
        return EvalMetrics(
            groundedness=0.0, context_relevance=0.0, entity_leakage=0.0,
            extractiveness=0.0, citation_coverage=0.0,
        )
    abstained = bool(_REFUSAL.search(answer)) and len(answer) < 400

    if not sources:
        return EvalMetrics(
            groundedness=1.0 if abstained else 0.0,
            context_relevance=0.0,
            entity_leakage=0.0 if abstained else 1.0,
            extractiveness=0.0,
            citation_coverage=1.0 if abstained else 0.0,
        )

    ctx_words = set(_content_words(context))
    ans_words = _content_words(answer)

    # --- groundedness ----------------------------------------------------
    if abstained:
        groundedness = 1.0
    elif ans_words:
        groundedness = sum(1 for w in ans_words if w in ctx_words) / len(ans_words)
    else:
        groundedness = 0.0

    # --- entity leakage --------------------------------------------------
    ans_specific = _specifics(answer)
    ctx_specific = _specifics(context)
    if abstained or not ans_specific:
        leakage = 0.0
    else:
        unsupported = {t for t in ans_specific if t not in ctx_specific and t not in context.lower()}
        leakage = len(unsupported) / len(ans_specific)

    # --- context relevance ------------------------------------------------
    q_words = set(_content_words(question))
    if q_words:
        per_chunk = [
            len(q_words & set(_content_words(s.text))) / len(q_words) for s in sources
        ]
        # Weight by rank: a relevant chunk at rank 1 is worth more than at rank 3.
        weights = [1.0 / (i + 1) for i in range(len(per_chunk))]
        context_relevance = sum(p * w for p, w in zip(per_chunk, weights)) / sum(weights)
    else:
        context_relevance = 0.0

    # --- extractiveness ---------------------------------------------------
    extractiveness = _longest_common_span_ratio(answer, context)

    # --- citation coverage ------------------------------------------------
    sentences = [s.strip() for s in _SENT.split(answer) if len(s.strip()) > 15]
    if abstained or not sentences:
        citation_coverage = 1.0
    else:
        covered = 0
        for sent in sentences:
            sent_words = set(_content_words(sent))
            if not sent_words:
                covered += 1
                continue
            if any(
                len(sent_words & set(_content_words(s.text))) / len(sent_words) >= 0.35
                for s in sources
            ):
                covered += 1
        citation_coverage = covered / len(sentences)

    clamp = lambda x: round(max(0.0, min(1.0, float(x))), 3)  # noqa: E731
    return EvalMetrics(
        groundedness=clamp(groundedness),
        context_relevance=clamp(context_relevance),
        entity_leakage=clamp(leakage),
        extractiveness=clamp(extractiveness),
        citation_coverage=clamp(citation_coverage),
        deterministic=True,
    )


def composite(metrics: EvalMetrics) -> float:
    """Single number for ranking strategies in the arena.

    Weighted toward not-lying: leakage is penalised hardest because a confidently
    wrong identifier is the failure mode that actually costs a user something.
    Extractiveness is excluded - it is diagnostic, not directional.
    """
    return round(
        0.35 * metrics.groundedness
        + 0.25 * metrics.context_relevance
        + 0.25 * (1.0 - metrics.entity_leakage)
        + 0.15 * metrics.citation_coverage,
        4,
    )
