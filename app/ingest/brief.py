"""Structured Content Brief generation - the docs-as-code output.

Runs deterministically first (taxonomy, entities, readability, structure), then
optionally enriches with an LLM summary. Building the skeleton without the LLM means
a brief is always produced, is always the same shape, and is diffable in git - which
is the whole point of treating docs as code.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone

from app.llm import complete_raw
from app.models import ChunkInfo, PIIReport
from app.retrieval.graph import Triple

_WORD = re.compile(r"[A-Za-z][A-Za-z\-']+")
_SENT = re.compile(r"(?<=[.!?])\s+")

_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "are", "was", "were", "for",
    "on", "with", "as", "by", "at", "be", "this", "that", "it", "from", "we", "our",
    "you", "your", "they", "their", "there", "which", "who", "what", "when", "how",
    "can", "should", "would", "will", "may", "must", "not", "all", "any", "each",
    "has", "have", "had", "been", "being", "does", "did", "into", "about", "more",
    "than", "then", "also", "such", "its", "if", "but", "these", "those", "use",
    "used", "using", "via", "per", "one", "two", "new", "see", "note",
}

# Lightweight taxonomy. In production this maps to your real content taxonomy /
# information architecture; the mechanism is identical, only the vocabulary changes.
TAXONOMY: dict[str, set[str]] = {
    "Architecture": {"service", "architecture", "component", "topology", "dependency", "system", "pipeline", "infrastructure"},
    "Operations": {"oncall", "escalation", "incident", "runbook", "alert", "rotation", "paged", "sev", "outage", "deploy"},
    "Security & Privacy": {"pii", "redaction", "privacy", "encryption", "compliance", "gdpr", "audit", "sensitive", "credential", "secret"},
    "Observability": {"logging", "logs", "metrics", "tracing", "telemetry", "monitoring", "dashboard", "observability"},
    "Data": {"database", "postgres", "schema", "index", "query", "replication", "storage", "warehouse", "table"},
    "Troubleshooting": {"error", "failure", "debug", "root", "cause", "retry", "timeout", "exception", "diagnose"},
    "Governance": {"policy", "standard", "guideline", "approval", "review", "ownership", "sla", "contract"},
}


def _keywords(text: str, n: int = 12) -> list[tuple[str, int]]:
    words = [w.lower() for w in _WORD.findall(text) if w.lower() not in _STOP and len(w) > 3]
    bigrams = [
        words[i] + " " + words[i + 1]
        for i in range(len(words) - 1)
        if words[i] not in _STOP and words[i + 1] not in _STOP
    ]
    counts = Counter(words)
    bigram_counts = Counter(b for b in bigrams if bigrams.count(b) > 1)
    merged = Counter()
    for term, count in counts.items():
        merged[term] = count
    for term, count in bigram_counts.items():
        merged[term] = count * 2   # phrases carry more signal than single words
    return merged.most_common(n)


def _taxonomy_tags(text: str) -> list[tuple[str, float]]:
    lowered = set(w.lower() for w in _WORD.findall(text))
    scored: list[tuple[str, float]] = []
    for tag, vocab in TAXONOMY.items():
        hits = len(lowered & vocab)
        if hits:
            scored.append((tag, round(hits / len(vocab), 3)))
    return sorted(scored, key=lambda kv: -kv[1])


def _readability(text: str) -> tuple[float, str]:
    """Flesch Reading Ease, approximated. Directional signal, not a precise score."""
    sentences = [s for s in _SENT.split(text) if s.strip()]
    words = _WORD.findall(text)
    if not sentences or not words:
        return 0.0, "unknown"
    syllables = sum(max(1, len(re.findall(r"[aeiouy]+", w.lower()))) for w in words)
    score = 206.835 - 1.015 * (len(words) / len(sentences)) - 84.6 * (syllables / len(words))
    score = round(max(0.0, min(100.0, score)), 1)
    if score >= 60:
        band = "plain English"
    elif score >= 40:
        band = "technical"
    else:
        band = "dense - consider simplifying"
    return score, band


def build_brief(
    title: str,
    doc_id: str,
    raw_text: str,
    chunks: list[ChunkInfo],
    pii: PIIReport,
    triples: list[Triple],
    use_llm: bool = True,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    full_text = "\n\n".join(c.text for c in chunks)
    keywords = _keywords(full_text)
    tags = _taxonomy_tags(full_text)
    read_score, read_band = _readability(full_text)
    n_words = len(_WORD.findall(full_text))

    relation_counts = Counter(t.relation for t in triples)
    entities = Counter()
    for t in triples:
        entities[t.subject.strip()] += 1
        entities[t.obj.strip()] += 1

    summary = ""
    if use_llm:
        completion = complete_raw(
            system=(
                "You are a technical content strategist. Write a 3-sentence executive summary "
                "of the document. State what it covers, who needs it, and what decision it "
                "supports. No preamble, no bullet points, no marketing language."
            ),
            user="Title: " + title + "\n\nDocument:\n" + full_text[:6000],
            max_tokens=220,
        )
        summary = completion.text.strip()
    if not summary:
        lead = [s.strip() for s in _SENT.split(full_text) if len(s.strip()) > 40][:3]
        summary = (
            " ".join(lead)
            if lead
            else "No extractable summary; document is too short or too fragmented."
        )
        summary += "\n\n> _Extractive summary - LLM unavailable at ingestion time._"

    lines: list[str] = []
    add = lines.append

    add("# Content Brief: " + title)
    add("")
    add("> Auto-generated at ingestion by the RAG Governance Engine. Machine-written, human-owned.")
    add("")
    add("| Field | Value |")
    add("| --- | --- |")
    add("| Document ID | `" + doc_id + "` |")
    add("| Generated | " + now + " |")
    add("| Word count | " + str(n_words) + " |")
    add("| Chunks indexed | " + str(len(chunks)) + " |")
    add("| Readability | " + str(read_score) + " (" + read_band + ") |")
    add("| PII entities redacted | " + str(pii.total_redacted) + " |")
    add("| Relations extracted | " + str(len(triples)) + " |")
    add("")

    add("## Summary")
    add("")
    add(summary)
    add("")

    add("## Taxonomy Tags")
    add("")
    if tags:
        for tag, confidence in tags[:5]:
            bar = "#" * max(1, int(confidence * 40))
            add("- **" + tag + "** - coverage " + format(confidence, ".3f") + " `" + bar + "`")
    else:
        add("- _No taxonomy match. Consider extending `TAXONOMY` in `app/ingest/brief.py`._")
    add("")

    add("## Key Themes")
    add("")
    if keywords:
        for term, count in keywords:
            add("- `" + term + "` x" + str(count))
    else:
        add("- _Insufficient text for theme extraction._")
    add("")

    add("## Knowledge Graph Contribution")
    add("")
    if triples:
        add("This document contributed **" + str(len(triples)) + "** relations to the knowledge graph.")
        add("")
        add("| Relation | Count |")
        add("| --- | --- |")
        for relation, count in relation_counts.most_common():
            add("| `" + relation + "` | " + str(count) + " |")
        add("")
        add("**Top entities:** " + ", ".join("`" + e + "`" for e, _ in entities.most_common(8)))
        add("")
        add("Sample triples:")
        add("")
        add("```")
        for t in triples[:8]:
            add(t.subject + " --[" + t.relation + "]--> " + t.obj)
        add("```")
    else:
        add("No relations extracted. This document is reachable by vector and lexical search")
        add("only - it will not participate in multi-hop graph traversal.")
    add("")

    add("## Governance")
    add("")
    if pii.total_redacted:
        add("**" + str(pii.total_redacted) + " PII entities redacted before indexing.**")
        add("")
        add("| Type | Count |")
        add("| --- | --- |")
        for ptype, count in sorted(pii.by_type.items(), key=lambda kv: -kv[1]):
            add("| " + ptype + " | " + str(count) + " |")
        add("")
        add("Redaction happens before chunking, so no raw PII reached the embedder,")
        add("the graph extractor, or the LLM provider.")
    else:
        add("No PII detected. Document indexed unmodified.")
    add("")

    add("## Retrieval Profile")
    add("")
    add("How this document is expected to be found:")
    add("")
    identifiers = len(re.findall(r"\bERR-\d+\b|\b[A-Z]{2,}[-_]\d{2,}\b", full_text))
    add("- **Lexical (BM25):** " + (
        "strong - " + str(identifiers) + " exact identifiers present."
        if identifiers
        else "weak - no rare identifiers to anchor term matching."
    ))
    add("- **Vector:** " + (
        "strong - prose-heavy, good paraphrase surface."
        if n_words > 120
        else "limited - short document, little semantic surface."
    ))
    add("- **Graph:** " + (
        "strong - " + str(len(triples)) + " relations enable multi-hop reachability."
        if len(triples) >= 3
        else "weak - too few relations for traversal to reach this document."
    ))
    add("")
    add("---")
    add("")
    add("_Review before publication. This brief is a draft artifact, not an approved document._")

    return "\n".join(lines)
