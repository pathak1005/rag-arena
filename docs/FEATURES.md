# Feature specification

Each feature states what it does, how it works, and how you would know it is broken.

---

## F1. Tri-modal retrieval over one chunk set

Three retrievers select from one immutable chunk set and feed one prompt template.

| Lane | Implementation | Wins on |
| --- | --- | --- |
| Lexical | BM25Okapi (`rank_bm25`) - the ranking function Elasticsearch uses by default | Exact identifiers, rare tokens, error codes |
| Vector | fastembed `bge-small-en-v1.5` (ONNX), exact cosine or ChromaDB HNSW | Paraphrase, conceptual questions |
| Graph | Entity extraction, resolution, BFS traversal, `MENTIONED_IN` back to chunks | Multi-entity relational questions spanning documents |
| Hybrid | Reciprocal Rank Fusion, k=60 | Ambiguous queries; lower variance than betting on one lane |

**Acceptance:** on the demo corpus each of the three example questions is won by its intended
strategy, and `POST /query_compare` returns per-lane sources with different `chunk_id` sets
(mean Jaccard below 0.75).

**Broken if:** all lanes return identical chunks on the example questions. That means the
corpus does not discriminate, and any comparison drawn from it is noise.

---

## F2. Query router

Classifies each question and picks a lane **before** retrieval, exposing the signals used.

Signal families: exact-identifier patterns favour lexical; relational language and multiple
linked entities favour graph; conceptual phrasing and verbose no-rare-token queries favour
vector; a close margin falls back to hybrid.

**Acceptance:** `GET /route?q=...` returns `recommended`, `confidence`, `rationale`, and a
`signals[]` list where every signal names the text that matched. Correct on 3/3 demo cases.

**Broken if:** `recommended` changes without a signal explaining why. The router is
deliberately rule-based so this cannot happen silently.

**Known limit:** weights are hand-set and validated only on the demo corpus. Phase 8 replaces
them with a classifier trained on the gold set.

---

## F3. PII redaction (governance)

Regex-first detection and redaction of EMAIL, PHONE, SSN, CREDIT_CARD (Luhn-validated),
IP_ADDRESS, and AWS_KEY - applied **before** chunking, embedding, or any LLM contact.

Raw values are never returned by the API. The audit report carries masked previews only.

**Acceptance:** ingesting `03_oncall_escalation.md` reports 9 redactions; retrieved chunks
show `[REDACTED_EMAIL]` and `[REDACTED_PHONE]`; no raw address appears in any response body.

**Broken if:** a raw email appears anywhere in an API response or a generated brief.

**Known limit:** no PERSON detection. Names survive by design, because the graph demo depends
on them. Presidio would add NER-based detection at significant dependency weight; regex covers
the stated classes at roughly 95%.

---

## F4. Deterministic evaluation (Tier 1)

Five metrics computed with no LLM in the loop: groundedness, context relevance, entity
leakage, extractiveness, citation coverage. The composite weighting penalises entity leakage
hardest, because a confidently wrong identifier is the failure mode that actually costs a
user something.

Abstention scores as grounded, not as hallucination. Scoring an honest "I don't know" as
failure rewards models that bluff.

**Acceptance:** the same question against the same corpus produces byte-identical metrics
across runs.

**Broken if:** metrics vary between runs on a fixed corpus. That would mean an LLM leaked into
the scoring path.

**Known limit:** no gold set, so these measure consistency, not accuracy. See PLAN.md Phase 8.

---

## F5. RAG readiness analyzer

Paste any page; get a 0-100 score, six dimension scores, predicted per-strategy
retrievability, and specific findings with evidence and fixes. Nothing is stored or indexed.

Dimensions and weights: self-containment (0.26), structure (0.22), entity clarity (0.18),
relational density (0.14), lexical anchors (0.10), governance (0.10).

Self-containment carries the most weight because a chunk opening with "It handles retries" is
unusable the moment it is separated from the paragraph that named "it" - and that stays
invisible until retrieval quality is already bad.

**Acceptance:** a well-structured page scores 80 or above; a page built from anaphora,
positional cross-references and marketing language scores 55 or below. Measured:
`02_dependency_map.md` scores 90; a synthetic marketing page scores 48.

**Broken if:** the two example pages score within 15 points of each other.

---

## F6. API playground with response interpretation

Send real requests against any endpoint; get the raw response beside plain-language
annotations of what is trustworthy and what is not.

Interpreters exist for `/chat`, `/query_compare`, `/route`, `/graph`, and `/health`. Each
observation carries a verdict (good/warning/bad/info), the field it refers to, what was
observed, and what it means about the system.

**Acceptance:** a graph-lane response with zero seed entities produces a `bad` observation
naming `trace.seeds`; a response with `entity_leakage` at or above 0.25 produces a `bad`
observation explaining why fabricated identifiers are the worst failure mode.

**Broken if:** every response comes back clean regardless of quality.

---

## F7. Structured content briefs

On ingestion, generates a markdown brief: summary, taxonomy tags, key themes, knowledge-graph
contribution with sample triples, governance report, and a per-strategy retrieval profile.
Downloadable, and written to `data/briefs/`.

The skeleton is built deterministically so a brief is always produced and always diffable in
git; the LLM only enriches the summary. Without a key the summary is extractive and labelled
as such.

**Acceptance:** every ingested document yields a brief, and `GET /brief/{doc_id}` returns it.

---

## F8. Pluggable backends

| Concern | Default | Alternative | Switch |
| --- | --- | --- | --- |
| Graph | NetworkX in-process | Neo4j (Cypher, `shortestPath` traversal) | `GRAPH_BACKEND` |
| Vectors | numpy exact cosine | ChromaDB (HNSW, persistent) | `VECTOR_BACKEND` |
| Embeddings | fastembed ONNX | TF-IDF/SVD fallback | automatic, reported in `/health` |
| Generation | Groq | extractive fallback | automatic, reported as `degraded` |

Every fallback is **reported, not hidden**. `GET /backends` shows what is actually live after
fallbacks were applied.

**Acceptance:** with `GRAPH_BACKEND=neo4j` and Neo4j down, the app still boots, logs the
failure, and reports `graph_backend: networkx`.

**Broken if:** a backend failure produces a 500 at request time instead of a fallback at
startup.
