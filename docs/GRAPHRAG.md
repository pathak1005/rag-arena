# Graph RAG: how it works here, and how to migrate an existing vector RAG

This is the document to read if you already have a working vector RAG and want to know
whether graph retrieval is worth adding, what it costs, and how to do it without a rewrite.

---

## 1. What graph RAG actually is (and isn't)

Graph RAG is **not** a replacement retrieval pipeline. It is an *index over the chunks you
already have*, built from the entities and relationships those chunks mention.

The distinction is load-bearing. A lot of graph RAG implementations retrieve triples and feed
those to the LLM. That works for question answering over a curated knowledge base, but it
throws away the surrounding prose, and it makes the system impossible to compare fairly
against vector RAG because the generation stage is now different.

**Here, traversal returns `chunk_id`s.** The graph decides *which chunks are reachable*;
the generator reads the same passages the other lanes read. This has three consequences:

1. The arena comparison is honest — retrieval is the only variable.
2. Adopting graph RAG doesn't change your generation stage at all.
3. You don't re-chunk and you don't re-embed. See §5.

---

## 2. Data model

```
(:Entity {id, label, type, aliases, mentions})
(:Chunk  {id, doc_id, doc_title})

(:Entity)-[:REL {type, confidence, chunk_ids, evidence}]->(:Entity)
(:Entity)-[:MENTIONED_IN]->(:Chunk)
```

`MENTIONED_IN` is the whole trick. It is the bridge from graph structure back to retrievable
text. Traversal finds entities; `MENTIONED_IN` converts those entities into the `chunk_id`s
the generator actually reads. Without it you have a knowledge graph, not a retrieval system.

Entity `id` is derived from a normalised form of the surface string, so `Team Meridian`,
`team meridian`, and `TEAM MERIDIAN` collapse to one node. Every observed surface form is
kept in `aliases` for query-time linking.

Implementation: [`app/retrieval/graph.py`](../app/retrieval/graph.py) (NetworkX) and
[`app/retrieval/graph_neo4j.py`](../app/retrieval/graph_neo4j.py) (Cypher). Same interface;
`app/store.py` doesn't know which is active.

---

## 3. The pipeline

### 3.1 Extraction

Rule-based, pattern-driven. Ten relation patterns cover the shapes that actually appear in
engineering documentation:

```
OWNED_BY      "X is owned by Y"        DEPENDS_ON    "X depends on Y"
ESCALATES_TO  "X escalates to Y"       PAGED_VIA     "X is paged via Y"
EMITS         "X emits ERR-1234"       RUNS_ON       "X runs on Y"
MAINTAINED_BY MEMBER_OF                GOVERNED_BY
```

This beats dependency parsing on structured docs, costs nothing, and is reproducible. It is
genuinely weak on prose — see §7 for the LLM-extraction upgrade.

The non-obvious part is **span trimming**. A naive capture of `X depends on Y` against

> The checkout-api depends on payments-gateway for authorisation of every order.

yields the object `payments-gateway for authorisation of every order` — one entity plus a
subordinate clause. That creates an unmergeable pseudo-entity, and enough of them fragment
the graph into uselessness. Cutting the capture at the first connector word (`for`, `during`,
`with`, `that`, `because`, …) was the single largest quality improvement in the extractor.

### 3.2 Entity resolution

This gets more code than extraction, on purpose. The usual reason graph RAG "underperforms"
is not bad triples — it's 1,400 isolated nodes because surface variants never merged.

The ladder, in order. Stop when good enough:

| Step | Method | Implemented |
| --- | --- | --- |
| 1 | Normalise — lowercase, strip punctuation, legal suffixes, trailing `service`/`system` | yes |
| 2 | Alias map — exact match on normalised key | yes |
| 3 | Cheap variant matching — plurals, prefix containment on multi-word names | yes |
| 4 | Embedding clustering — cosine ≥ 0.85 over entity surface forms | **no** — see limitations |
| 5 | LLM adjudication for the 0.75–0.85 grey band | **no** |

`n_components` in `GET /graph` is the diagnostic. If it's high relative to entity count, the
graph is fragmented and traversal will quietly under-retrieve. The UI surfaces this as a
warning. On the demo corpus it currently sits around 42 components / ~90 entities, which is
the honest cost of stopping at step 3.

### 3.3 Query-time linking

Map the question onto seed entities: exact alias match (strength 1.0), then partial token
overlap (0.2–0.75). Seeds with no match mean the graph cannot help — the router treats "no
entity linked" as a signal *against* the graph lane.

### 3.4 Traversal and ranking

BFS to `GRAPH_MAX_HOPS` (default 3), bidirectional — "who owns the thing that X depends on"
needs to traverse both directions.

Ranking is two-factor:

```
score = (seed_strength × HOP_DECAY^hops / √(entities mentioned in chunk))
        × (0.10 + 0.90 × idf_weighted_term_relevance)
```

Each term earns its place, and each was added because the correct answer was ranking too low
without it:

- **`HOP_DECAY = 0.85`** — started at 0.62, which made a 3-hop answer worth 0.24 of an
  incidental 0-hop mention. The chain never survived to the top-k. That defeats the entire
  purpose of traversal.
- **`/√(entities in chunk)`** — a document header naming twenty services is reachable from
  everywhere while being *about* nothing. Same idea as TF saturation.
- **IDF-weighted relevance** — unweighted overlap treats `escalate` and `problem` as equally
  informative. The rare term is the one that identifies the answer. This is exactly what BM25
  does, reused inside the graph lane.

The graph decides what's **reachable**; term relevance decides what's **relevant** among the
reachable set. Both factors are reported separately in the `why` field so ranking stays
inspectable rather than becoming an opaque blend.

---

## 4. When graph RAG wins, and when it doesn't

**Wins:**
- Multi-entity relational questions where the answer spans documents.
- Ownership, dependency, blast-radius, escalation — anything about *topology*.
- Questions where the correct chunk shares almost no vocabulary with the question, but is two
  hops from something that does.

**Loses:**
- Single-fact lookups. Vector or lexical get there directly and more cheaply.
- Exact identifiers. BM25 wins outright.
- Corpora with no explicit relational statements — nothing to extract, nothing to traverse.
- Any corpus where entity resolution hasn't been done properly. A fragmented graph is worse
  than no graph, because it produces confident-looking paths that go nowhere.

**The mature answer is routing, not picking a winner.** See
[`app/retrieval/router.py`](../app/retrieval/router.py).

---

## 5. Migrating an existing vector RAG to graph RAG

The encouraging part: **you do not re-chunk and you do not re-embed.**

### Step 1 — Confirm stable chunk IDs

If your chunks aren't addressable and immutable, fix that first. Everything below depends on
it. A chunk is `{id, doc_id, text, span, metadata}`.

### Step 2 — Offline extraction pass

Iterate your existing chunks (dump them from your vector store — no need to re-read source
documents). For each, extract triples with provenance:

```
(subject, relation, object, chunk_id, evidence_span, confidence)
```

This is a batch job. It touches your production read path zero times. Checkpoint to JSONL so
it's resumable.

### Step 3 — Entity resolution

The ladder in §3.2. **This is the step people skip**, and then wonder why graph RAG
underperforms. Budget roughly 60% of your migration effort here, not on extraction.

### Step 4 — Build the graph with chunk anchors

Two node types (`Entity`, `Chunk`), two edge classes (typed `REL` between entities,
`MENTIONED_IN` from entity to chunk). Chunk nodes hold only the id — the text stays in your
existing store. The graph is an index, not a second copy of your corpus.

### Step 5 — Wire the query path

```
question
  → entity-link to seed nodes (NER + alias lookup + embedding fallback)
  → k-hop subgraph expansion (k=2 is the sweet spot; k=3 starts to explode)
  → score paths (edge confidence × hop decay × seed strength × relevance)
  → collect chunk_ids via MENTIONED_IN
  → dedupe, budget to N tokens
  → SAME generation prompt you already use
```

### Step 6 — Keep both and route between them

Don't replace vector retrieval. Route: multi-entity/comparative/topological questions → graph;
single-fact → vector; exact-identifier → lexical; ambiguous → RRF fusion. A heuristic on
entity count in the question works; a small classifier trained on your gold set works better.

### What it costs

For a real 100k-chunk corpus:

| Item | Estimate |
| --- | --- |
| Extraction inference (small model / Groq) | ~$20–60 one-off |
| Compute | a few hours, batched, offline |
| Re-embedding | **none** |
| Re-chunking | **none** |
| Production downtime | **none** |
| Ongoing | one extraction call per new/changed chunk at ingest |

State that number when proposing this internally. It converts an academic demo into an
engineering proposal.

---

## 6. Neo4j vs. NetworkX

Both implemented, selected by `GRAPH_BACKEND`.

**NetworkX** is the default: zero infrastructure, exact, fast at demo scale, and the app boots
even when nothing else is running.

**Neo4j** is the production path, and the better one to learn on. Multi-hop traversal is a
`shortestPath` query rather than hand-written BFS, the graph is persistent, and you can
inspect it visually in Neo4j Browser. [docs/LEARN.md](LEARN.md) has runnable queries.

A note on hosting: **Neo4j AuraDB Free suspends after 3 days idle.** For a portfolio demo
that's a liability — it will be asleep exactly when someone opens your link. Ship NetworkX as
the default, keep the Neo4j adapter in the repo, and say so in the README. That reads as
judgment, not as a shortcut.

---

## 7. Upgrade path

Ordered by value per unit of effort:

1. **Embedding-based entity resolution** (ladder step 4). Highest impact — it's what would
   collapse the current 42 components. Reuses the embedder that's already loaded.
2. **LLM triple extraction.** One Groq call per chunk with a JSON-schema-constrained prompt
   returning `{subject, relation, object, evidence_span}`. Dramatically better on prose. Keep
   the rule-based extractor as the fast/free path — having both is itself a demoable
   comparison.
3. **Gold set + measured routing.** Replace hand-weighted routing rules with a classifier
   trained on labelled queries. Same signal interface.
4. **Community detection / summarisation** (the Microsoft GraphRAG approach) for global
   "what are the themes" questions, which none of the three current lanes handle well.
5. **Relation-type-aware traversal** — weight `DEPENDS_ON` higher than `MENTIONED_IN` when the
   question is about topology.
