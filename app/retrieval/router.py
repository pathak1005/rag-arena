"""Query router: decides WHICH retrieval strategy a question should use, and says why.

This is the thesis of the project. The mature production answer to "vector or graph?"
is neither - it is *route*, because the three strategies fail in different, predictable
places:

    exact identifier   -> lexical  (dense vectors smear rare tokens across near-dupes)
    conceptual/paraphrase -> vector   (no term overlap for BM25 to score on)
    multi-entity relational -> graph   (the answer spans chunks; no single chunk has it)
    ambiguous          -> hybrid   (RRF fusion, safest default)

Deliberately rule-based and inspectable rather than a learned classifier: every
decision comes with the signals that produced it, so the UI can show its work. On a
real corpus you would replace the weights here with a small classifier trained on
the gold set, and keep the same signal interface.
"""
from __future__ import annotations

import re

from app.models import QueryClass, RoutingDecision, RoutingSignal, Strategy

# --- signal detectors ------------------------------------------------------
IDENTIFIER_PATTERNS = [
    (re.compile(r"\bERR-\d{3,5}\b", re.I), "error code"),
    (re.compile(r"\b[A-Z]{2,}[-_]\d{2,}\b"), "ticket/code id"),
    (re.compile(r"\bv?\d+\.\d+(?:\.\d+)?\b"), "version number"),
    (re.compile(r"\b[A-Z][A-Z0-9_]{4,}\b"), "constant/config key"),
    (re.compile(r"\"[^\"]{3,40}\"|'[^']{3,40}'"), "quoted literal"),
    (re.compile(r"\b\w+_\w+(?:_\w+)*\b"), "snake_case symbol"),
    (re.compile(r"\b\d{3,}\b"), "numeric id"),
]

RELATIONAL_MARKERS = [
    (re.compile(r"\bwho\s+(?:owns|maintains|is\s+responsible|do\s+i|should\s+i)\b", re.I), "ownership question", 1.4),
    (re.compile(r"\bwhich\s+team\b", re.I), "team lookup", 1.3),
    (re.compile(r"\bdepend(?:s|ency|encies)?\b", re.I), "dependency language", 1.2),
    (re.compile(r"\b(?:upstream|downstream|blast\s+radius|impact(?:ed)?\s+by)\b", re.I), "topology language", 1.4),
    (re.compile(r"\bescalat\w*\b", re.I), "escalation path", 1.2),
    (re.compile(r"\b(?:related\s+to|connected\s+to|linked\s+to|affects?)\b", re.I), "relation language", 1.0),
    (re.compile(r"\bif\s+.+\s+fails?\b", re.I), "failure-propagation question", 1.3),
    (re.compile(r"\bchain|path|trace\s+(?:from|through)\b", re.I), "path language", 1.1),
]

CONCEPTUAL_MARKERS = [
    (re.compile(r"\b(?:how\s+do\s+we|how\s+should|what\s+is\s+our|why\s+do(?:es)?)\b", re.I), "policy/approach phrasing", 1.2),
    (re.compile(r"\b(?:approach|strategy|policy|philosophy|guideline|principle|best\s+practice)\b", re.I), "abstract noun", 1.1),
    (re.compile(r"\b(?:explain|describe|summari[sz]e|overview|rationale)\b", re.I), "explanatory intent", 1.0),
    (re.compile(r"\b(?:prevent|avoid|protect|ensure|improve|reduce)\b", re.I), "goal-oriented verb", 0.8),
]


def _detect_identifiers(question: str) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for pattern, label in IDENTIFIER_PATTERNS:
        m = pattern.search(question)
        if m:
            hits.append((m.group(0), label))
    return hits


def route(question: str, seed_entities: list[str], graph_ready: bool = True) -> RoutingDecision:
    """Score each strategy from inspectable signals. seed_entities comes from GraphStore.link_query."""
    scores = {Strategy.LEXICAL: 0.0, Strategy.VECTOR: 0.0, Strategy.GRAPH: 0.0, Strategy.HYBRID: 0.6}
    signals: list[RoutingSignal] = []

    # 1) Exact identifiers -> lexical
    identifiers = _detect_identifiers(question)
    for surface, label in identifiers:
        scores[Strategy.LEXICAL] += 1.5
        signals.append(RoutingSignal(name=label, value=surface, weight=1.5, favors=Strategy.LEXICAL))

    # 2) Relational language -> graph
    for pattern, label, weight in RELATIONAL_MARKERS:
        m = pattern.search(question)
        if m:
            scores[Strategy.GRAPH] += weight
            signals.append(RoutingSignal(name=label, value=m.group(0), weight=weight, favors=Strategy.GRAPH))

    # 3) Multiple linked entities -> graph (the strongest single signal)
    n_entities = len(seed_entities)
    if graph_ready and n_entities >= 2:
        bonus = 1.1 * min(n_entities, 4)
        scores[Strategy.GRAPH] += bonus
        signals.append(
            RoutingSignal(
                name="multiple entities linked",
                value=", ".join(seed_entities[:4]),
                weight=round(bonus, 2),
                favors=Strategy.GRAPH,
            )
        )
    elif graph_ready and n_entities == 1:
        scores[Strategy.GRAPH] += 0.4
        signals.append(
            RoutingSignal(name="single entity linked", value=seed_entities[0], weight=0.4, favors=Strategy.GRAPH)
        )
    elif graph_ready:
        signals.append(
            RoutingSignal(name="no entity linked", value="graph cannot seed", weight=-1.0, favors=Strategy.VECTOR)
        )
        scores[Strategy.GRAPH] -= 1.0
        scores[Strategy.VECTOR] += 0.5

    # 4) Conceptual phrasing -> vector
    for pattern, label, weight in CONCEPTUAL_MARKERS:
        m = pattern.search(question)
        if m:
            scores[Strategy.VECTOR] += weight
            signals.append(RoutingSignal(name=label, value=m.group(0), weight=weight, favors=Strategy.VECTOR))

    # 5) Long natural-language questions with no rare tokens favour dense retrieval
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z\-']+", question) if len(w) > 2]
    if len(words) >= 8 and not identifiers:
        scores[Strategy.VECTOR] += 0.7
        signals.append(
            RoutingSignal(
                name="verbose, no rare tokens",
                value=str(len(words)) + " content words",
                weight=0.7,
                favors=Strategy.VECTOR,
            )
        )

    if not graph_ready:
        scores[Strategy.GRAPH] = -99.0

    recommended = max(scores, key=lambda s: scores[s])
    ordered = sorted(scores.values(), reverse=True)
    margin = ordered[0] - ordered[1] if len(ordered) > 1 else ordered[0]

    # Close call between two specialists -> fuse instead of guessing.
    if margin < 0.5 and recommended is not Strategy.HYBRID:
        recommended = Strategy.HYBRID

    confidence = max(0.25, min(0.98, 0.45 + margin / 6.0))

    if recommended is Strategy.LEXICAL:
        qclass = QueryClass.EXACT_IDENTIFIER
        rationale = (
            "The query contains an exact identifier (" + identifiers[0][0] + "). Dense embeddings "
            "compress rare tokens toward their neighbourhood, so near-identical sibling chunks become "
            "indistinguishable; BM25 scores the literal term and wins."
            if identifiers
            else "Literal term matching is the strongest available signal for this query."
        )
    elif recommended is Strategy.GRAPH:
        qclass = QueryClass.MULTI_HOP_RELATIONAL
        rationale = (
            "The query names " + str(n_entities) + " known entit" + ("ies" if n_entities != 1 else "y")
            + " and uses relational language. The answer likely spans several documents, so no single "
            "chunk contains it - traversal assembles the chain that flat retrieval cannot."
        )
    elif recommended is Strategy.VECTOR:
        qclass = QueryClass.CONCEPTUAL
        rationale = (
            "The query is phrased conceptually with no rare literals and no entity pair to traverse. "
            "The source wording is probably a paraphrase, which is precisely where term matching fails "
            "and dense similarity succeeds."
        )
    else:
        qclass = QueryClass.MIXED
        rationale = (
            "Signals are split (margin " + format(margin, ".2f") + "), so no single retriever is clearly "
            "correct. Reciprocal Rank Fusion over all three is the lower-variance choice."
        )

    return RoutingDecision(
        query_class=qclass,
        recommended=recommended,
        confidence=round(confidence, 3),
        rationale=rationale,
        signals=signals,
        scores={k.value: round(v, 3) for k, v in scores.items()},
    )
