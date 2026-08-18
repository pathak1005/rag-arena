# Build plan and status

Status as of the current commit. Honest about what is done, partial, and not started.

## Phase status

| Phase | Scope | Status |
| --- | --- | --- |
| 0 | Toolchain, package layout, Pydantic contracts, stubbed API | done |
| 1 | Ingestion: PII scrub, chunk, BM25 + embeddings; lexical + vector retrieval | done |
| 2 | Graph: extraction, entity resolution, traversal, chunk recovery | done, with known debt (D9) |
| 3 | Router + RRF hybrid fusion | done |
| 4 | Tier-1 deterministic evaluation + Arena UI | done |
| 5 | Content briefs, readiness analyzer, API playground | done |
| 6 | Neo4j + ChromaDB backends | done, Neo4j path needs load testing |
| 7 | Dockerfile, fly.toml, compose, start scripts | done, not yet deployed |
| 8 | **Gold set + measured benchmark** | **not started - highest value remaining** |
| 9 | Tier-2 NLI faithfulness scoring | not started |
| 10 | Embedding-based entity resolution (ladder step 4) | not started |

## What "done" does not mean

Phase 4 is done in the sense that the metrics compute correctly and reproducibly. It is
**not** done in the sense of proving accuracy - that needs Phase 8.

Until there is a gold set, the arena demonstrates *mechanism*: it shows that the three
strategies retrieve different chunks and that the differences are explainable. It does not
show *how often* each is right on a representative query distribution. Those are different
claims, and conflating them is the most common overclaim in RAG portfolio projects.

## Phase 8 - the gold set (next)

The single highest-value remaining work.

**Shape:** 30-40 questions over the demo corpus in `data/gold_set.yaml`, stratified into
three buckets that map onto the three retrieval failure modes:

| Bucket | Expected winner | approx n |
| --- | --- | --- |
| Exact identifier / rare token | lexical | 12 |
| Conceptual paraphrase | vector | 12 |
| Multi-hop relational | graph | 12 |

Each entry: `question`, `bucket`, `relevant_chunk_ids[]`, `expected_answer_contains[]`.

**Deliverable:** `make eval` prints recall@3 and composite score per bucket per strategy,
plus router accuracy. That table is the artifact worth showing - it converts "here are three
answers side by side" into "here is which strategy wins which class of question, and how
often".

**Why it is not done yet:** labelling relevant chunk ids by hand is the actual work, and
doing it badly is worse than not doing it. It needs a focused sitting, not a spare hour.

## Ordered backlog after Phase 8

1. Embedding-based entity resolution (D9) - collapses the ~42 components.
2. LLM triple extraction behind a flag, benchmarked against the rule-based extractor on the
   gold set. Having both comparable is more interesting than replacing one with the other.
3. Tier-2 NLI faithfulness (claim decomposition + cross-encoder entailment). Adds a model to
   the image, so gate it behind a feature flag and keep the default container small.
4. Replace hand-weighted routing rules with a classifier trained on the gold set, keeping the
   same signal interface so the UI explanation still works.
5. Persistence for the Neo4j/Chroma paths + multi-worker uvicorn (removes D13).
6. Deploy to Fly and record real cold-start numbers rather than estimates.

## Explicitly out of scope

- Multi-tenant auth. This is a single-tenant demonstrator; half an auth story is worse than
  none.
- Streaming responses. UI complexity without changing what the project is about.
- Fine-tuning. The project is about retrieval and evaluation architecture.
- Community detection / global summarisation (Microsoft GraphRAG style). Genuinely useful for
  "what are the themes" questions, but a different problem from the one being measured here.
