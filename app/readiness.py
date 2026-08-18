"""RAG-readiness analyzer.

Answers a question that comes up constantly and usually gets answered by vibes:
"is this page any good for retrieval?"

The scoring is deterministic and the findings are specific - each one points at the
offending text and says what to change. A score with no line reference is not
actionable, and an unactionable score gets ignored.

Six dimensions, scored 0-100:

  structure        headings, section sizing, list/table use
  self_containment anaphora that breaks when a chunk is cut loose from its neighbours
  entity_clarity   named things vs vague referents
  relational       extractable subject-relation-object density -> graph reachability
  lexical_anchors  unique identifiers -> BM25 retrievability
  governance       PII and unresolved-reference risk

The weights come from what actually breaks retrieval in practice, in order:
self-containment first (a chunk that says "it does this" is unusable once separated
from the paragraph that named "it"), then structure (bad boundaries poison every
downstream lane), then the rest.
"""
from __future__ import annotations

import re
from collections import Counter

from app.governance.pii import scrub
from app.models import ReadinessDimension, ReadinessFinding, ReadinessReport
from app.retrieval.graph import extract_triples

_SENT = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[A-Za-z][A-Za-z\-']+")
_PARA = re.compile(r"\n\s*\n")

# Words that point outside the current chunk. These are the single most common cause
# of a chunk that retrieves well and then answers badly.
_ANAPHORA_START = re.compile(
    r"^\s*(?:it|its|this|that|these|those|they|them|their|he|she|his|her|such|"
    r"the former|the latter|both|either|neither)\b",
    re.I,
)
_DEIXIS = re.compile(
    r"\b(?:as (?:mentioned|described|noted|discussed) (?:above|below|earlier|previously)|"
    r"see (?:above|below|the (?:previous|next|preceding|following))|"
    r"in the (?:previous|next|preceding|following) (?:section|chapter|paragraph)|"
    r"the (?:above|below|following|preceding)|refer to the|as follows)\b",
    re.I,
)
_VAGUE_SUBJECT = re.compile(
    r"\b(?:the (?:service|system|team|component|platform|application|tool|process|feature))\b",
    re.I,
)
_IDENTIFIER = re.compile(
    r"\bERR-\d{3,5}\b|\b[A-Z]{2,}[-_]\d{2,}\b|\b[a-z][a-z0-9]*(?:-[a-z0-9]+){1,3}\b|"
    r"\b[A-Z][A-Z0-9_]{4,}\b|\bv?\d+\.\d+(?:\.\d+)?\b"
)
# "world-class" and "next-generation" match the kebab-case pattern but are ordinary
# English adjectives, not identifiers. Counting them scored a pure-marketing page 98
# on lexical anchors, which is the opposite of the truth.
_COMMON_HYPHEN_WORDS = {
    "world", "class", "next", "generation", "cutting", "edge", "best", "in", "state",
    "of", "the", "art", "game", "changing", "long", "term", "short", "real", "time",
    "high", "low", "well", "known", "cost", "effective", "end", "to", "user",
    "friendly", "self", "service", "on", "off", "up", "date", "out", "box", "day",
    "one", "first", "second", "third", "full", "part", "non", "pre", "post", "co",
    "re", "multi", "cross", "inter", "intra", "sub", "super", "over", "under",
    "follow", "hands", "data", "driven", "decision", "making", "based", "make",
}


def _is_identifier(token: str) -> bool:
    """An anchor must be a *name*, not an English compound adjective."""
    if any(ch.isdigit() for ch in token):
        return True
    parts = [p for p in re.split(r"[-_]", token.lower()) if p]
    if len(parts) < 2:
        return len(token) > 3
    return not all(p in _COMMON_HYPHEN_WORDS for p in parts)


_HEADING = re.compile(r"^(#{1,6})\s+(.+)$", re.M)
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+", re.M)
_TABLE_ROW = re.compile(r"^\s*\|.+\|\s*$", re.M)
_CODE_FENCE = re.compile(r"```")
_MARKETING = re.compile(
    r"\b(?:seamless(?:ly)?|cutting[- ]edge|world[- ]class|best[- ]in[- ]class|"
    r"revolutionary|game[- ]changing|synerg\w+|leverage(?:s|d)? our|empower\w*|"
    r"unlock(?:s|ing)? the|next[- ]generation|robust and scalable|state of the art)\b",
    re.I,
)


def _clamp(value: float) -> int:
    return int(max(0.0, min(100.0, round(value))))


def _snippet(text: str, limit: int = 110) -> str:
    flat = " ".join(text.split())
    return flat[:limit] + ("..." if len(flat) > limit else "")


def analyze(text: str, title: str = "Pasted content") -> ReadinessReport:
    findings: list[ReadinessFinding] = []
    paragraphs = [p.strip() for p in _PARA.split(text) if p.strip()]
    sentences = [s.strip() for s in _SENT.split(text) if len(s.strip()) > 10]
    words = _WORD.findall(text)
    n_words = len(words)

    if n_words < 30:
        return ReadinessReport(
            title=title, overall_score=0, verdict="Too short to assess",
            n_words=n_words, n_paragraphs=len(paragraphs),
            dimensions=[], findings=[
                ReadinessFinding(
                    severity="high", dimension="structure",
                    issue="Document is under 30 words.",
                    evidence=_snippet(text),
                    fix="Provide a full page. Retrieval quality cannot be judged from a fragment.",
                )
            ],
            predicted_retrievability={"lexical": 0, "vector": 0, "graph": 0},
            estimated_chunks=0,
        )

    # ---------------------------------------------------------------- structure
    headings = _HEADING.findall(text)
    n_headings = len(headings)
    heading_levels = [len(h[0]) for h in headings]
    para_words = [len(_WORD.findall(p)) for p in paragraphs]
    oversized = [p for p, w in zip(paragraphs, para_words) if w > 220]
    tiny = [w for w in para_words if w < 12]

    structure_score = 60.0
    if n_headings:
        structure_score += min(25.0, n_headings / max(1, n_words / 250) * 12)
    else:
        structure_score -= 25
        findings.append(ReadinessFinding(
            severity="high", dimension="structure",
            issue="No headings found.",
            evidence=_snippet(paragraphs[0]),
            fix="Add H2/H3 headings every 150-250 words. Headings are the highest-signal "
                "chunk boundary available and they carry into chunk metadata for free.",
        ))
    if heading_levels and len(set(heading_levels)) == 1 and n_headings > 3:
        structure_score -= 8
        findings.append(ReadinessFinding(
            severity="low", dimension="structure",
            issue="Flat heading hierarchy - every heading is the same level.",
            evidence="; ".join(h[1] for h in headings[:4]),
            fix="Nest subsections so the outline conveys scope. Flat hierarchies give the "
                "chunker no way to tell a major boundary from a minor one.",
        ))
    for para in oversized[:3]:
        structure_score -= 9
        findings.append(ReadinessFinding(
            severity="medium", dimension="structure",
            issue="Paragraph exceeds 220 words and will be split mid-argument.",
            evidence=_snippet(para),
            fix="Break into paragraphs of 60-120 words, each making one point. Splits that "
                "land mid-argument produce chunks that are individually incoherent.",
        ))
    if len(tiny) > len(paragraphs) * 0.5 and len(paragraphs) > 6:
        structure_score -= 10
        findings.append(ReadinessFinding(
            severity="medium", dimension="structure",
            issue="Most paragraphs are under 12 words - the page is fragmented.",
            evidence=str(len(tiny)) + " of " + str(len(paragraphs)) + " paragraphs",
            fix="Merge fragments into complete paragraphs. Very short chunks carry too little "
                "context to embed meaningfully.",
        ))
    if _LIST_ITEM.search(text) or _TABLE_ROW.search(text):
        structure_score += 5

    # ------------------------------------------------------- self-containment
    anaphoric = [p for p in paragraphs if _ANAPHORA_START.search(p)]
    deictic = _DEIXIS.findall(text)
    containment_score = 100.0
    anaphora_rate = len(anaphoric) / max(1, len(paragraphs))
    containment_score -= anaphora_rate * 100 * 0.85
    containment_score -= min(30.0, len(deictic) * 6.0)

    for para in anaphoric[:3]:
        findings.append(ReadinessFinding(
            severity="high", dimension="self_containment",
            issue="Paragraph opens with a pronoun whose referent is in a different paragraph.",
            evidence=_snippet(para, 90),
            fix="Restate the subject by name: \"It handles retries\" -> \"The payments-gateway "
                "handles retries\". Once this paragraph becomes a chunk, the referent is gone.",
        ))
    for phrase in list(dict.fromkeys(deictic))[:3]:
        findings.append(ReadinessFinding(
            severity="medium", dimension="self_containment",
            issue="Positional cross-reference (\"" + str(phrase).strip() + "\") assumes surrounding text.",
            evidence=_snippet(next((s for s in sentences if str(phrase).lower() in s.lower()), str(phrase))),
            fix="Replace positional references with the named target, or repeat the fact. "
                "Chunks are retrieved alone - \"as described above\" resolves to nothing.",
        ))

    # ---------------------------------------------------------- entity clarity
    vague = _VAGUE_SUBJECT.findall(text)
    identifiers = _IDENTIFIER.findall(text)
    unique_identifiers = {i for i in identifiers if len(i) > 3 and _is_identifier(i)}
    proper_nouns = re.findall(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})?\b", text)

    entity_score = 55.0
    entity_score += min(30.0, len(unique_identifiers) / max(1.0, n_words / 100) * 14)
    entity_score += min(15.0, len(set(proper_nouns)) / max(1.0, n_words / 100) * 6)
    entity_score -= min(35.0, len(vague) / max(1.0, n_words / 100) * 12)

    if vague:
        counts = Counter(v.lower() for v in vague)
        top = counts.most_common(1)[0]
        findings.append(ReadinessFinding(
            severity="medium", dimension="entity_clarity",
            issue="Generic referent \"" + top[0] + "\" used " + str(top[1]) + " time(s) instead of a name.",
            evidence=_snippet(next((s for s in sentences if top[0] in s.lower()), top[0])),
            fix="Name the thing. Generic subjects cannot be linked to a graph node, so these "
                "sentences contribute nothing to multi-hop retrieval.",
        ))

    # --------------------------------------------------------------- relational
    triples = extract_triples("readiness::probe", text)
    triple_density = len(triples) / max(1.0, n_words / 100)
    relational_score = _clamp(min(100.0, triple_density * 42))
    if len(triples) == 0:
        findings.append(ReadinessFinding(
            severity="medium", dimension="relational",
            issue="No subject-relation-object statements detected.",
            evidence=_snippet(paragraphs[0]),
            fix="State relationships explicitly: \"X is owned by Y\", \"A depends on B\". "
                "Without them this page is invisible to graph traversal and reachable only "
                "by keyword or embedding similarity.",
        ))
    elif triple_density < 0.8:
        findings.append(ReadinessFinding(
            severity="low", dimension="relational",
            issue="Sparse relational content (" + format(triple_density, ".2f") + " relations per 100 words).",
            evidence=" | ".join(t.subject + " -> " + t.relation + " -> " + t.obj for t in triples[:2]),
            fix="Add explicit ownership, dependency, or escalation statements if this page "
                "should participate in multi-hop questions.",
        ))

    # ---------------------------------------------------------- lexical anchors
    anchor_density = len(unique_identifiers) / max(1.0, n_words / 100)
    lexical_score = _clamp(min(100.0, 38 + anchor_density * 30))
    if not unique_identifiers:
        findings.append(ReadinessFinding(
            severity="low", dimension="lexical_anchors",
            issue="No unique identifiers (codes, versions, service names) present.",
            evidence=_snippet(paragraphs[0]),
            fix="Where the page describes a specific thing, name it precisely. Rare tokens are "
                "the only handle keyword search has; without them BM25 cannot distinguish this "
                "page from any other on the topic.",
        ))

    # ---------------------------------------------------------------- governance
    _, pii = scrub(text, enabled=True)
    marketing = _MARKETING.findall(text)
    governance_score = 100.0
    governance_score -= min(60.0, pii.total_redacted * 12.0)
    governance_score -= min(25.0, len(marketing) * 6.0)

    if pii.total_redacted:
        findings.append(ReadinessFinding(
            severity="high", dimension="governance",
            issue=str(pii.total_redacted) + " PII entities detected ("
                  + ", ".join(pii.by_type.keys()) + ").",
            evidence="masked: " + ", ".join(e.surface for e in pii.entities[:4]),
            fix="These are redacted automatically at ingestion here, but the source page still "
                "carries them. Fix at the source - redaction is a safety net, not a policy.",
        ))
    if marketing:
        findings.append(ReadinessFinding(
            severity="low", dimension="governance",
            issue="Promotional language detected (" + ", ".join(sorted(set(m.lower() for m in marketing))[:3]) + ").",
            evidence=_snippet(next((s for s in sentences if _MARKETING.search(s)), "")),
            fix="Strip it. Marketing adjectives embed close to every other marketing page, "
                "which pulls unrelated content into your top-k.",
        ))

    # ------------------------------------------------------------------ scoring
    dims = [
        ReadinessDimension(name="self_containment", score=_clamp(containment_score), weight=0.26,
                           summary="Do chunks still make sense once separated from their neighbours?"),
        ReadinessDimension(name="structure", score=_clamp(structure_score), weight=0.22,
                           summary="Are there clean, well-sized boundaries for the chunker?"),
        ReadinessDimension(name="entity_clarity", score=_clamp(entity_score), weight=0.18,
                           summary="Are things named specifically enough to link and retrieve?"),
        ReadinessDimension(name="relational", score=_clamp(relational_score), weight=0.14,
                           summary="Density of explicit relationships - drives graph reachability."),
        ReadinessDimension(name="lexical_anchors", score=_clamp(lexical_score), weight=0.10,
                           summary="Rare tokens that keyword search can grip."),
        ReadinessDimension(name="governance", score=_clamp(governance_score), weight=0.10,
                           summary="PII exposure and noise that pollutes the embedding space."),
    ]
    overall = _clamp(sum(d.score * d.weight for d in dims))

    if overall >= 80:
        verdict = "RAG-ready. Index as-is."
    elif overall >= 65:
        verdict = "Usable, with known weak spots. Fix the high-severity findings first."
    elif overall >= 45:
        verdict = "Marginal. Expect inconsistent retrieval until the structural issues are fixed."
    else:
        verdict = "Not RAG-ready. Rewrite for self-containment and structure before indexing."

    predicted = {
        "lexical": _clamp(lexical_score * 0.7 + structure_score * 0.3),
        "vector": _clamp(containment_score * 0.55 + structure_score * 0.3 + governance_score * 0.15),
        "graph": _clamp(relational_score * 0.6 + entity_score * 0.4),
    }

    severity_rank = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: severity_rank.get(f.severity, 3))

    return ReadinessReport(
        title=title,
        overall_score=overall,
        verdict=verdict,
        n_words=n_words,
        n_paragraphs=len(paragraphs),
        dimensions=dims,
        findings=findings[:20],
        predicted_retrievability=predicted,
        estimated_chunks=max(1, round(n_words / 82)),
    )
