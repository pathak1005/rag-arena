# Engineering log

Decisions that cost time, and what they cost. Newest last.

---

### D1. Python 3.12, not 3.14

`py -0p` showed 3.14 as the default interpreter on this machine. fastembed, onnxruntime and
chromadb wheels for 3.14 are incomplete, and the failures surface as compiler errors that
look like code bugs. Pinned to 3.12 before writing a line of application code.

**Cost if missed:** an evening, misattributed to the wrong layer.

---

### D2. fastembed (ONNX) instead of sentence-transformers (torch)

`sentence-transformers` pulls torch: ~2.5GB image, slow cold start, OOM on a 512MB Fly
machine. `fastembed` runs the same class of model through ONNX runtime: ~400MB, and faster
on CPU.

Trade-off: fewer models available, and the API is less familiar to people who expect
`SentenceTransformer`. Worth it — deployment size is the difference between a demo that
loads and one that times out.

A TF-IDF/SVD fallback exists for offline use and is **labelled** in `/health` rather than
hidden. A latent-semantic model on a small corpus is measurably worse at paraphrase matching
than a trained encoder, and pretending otherwise would corrupt every arena result.

---

### D3. One chunk table, shared by all retrievers

The original spec described two pipelines (Vector RAG, Graph RAG). Built that way, the
comparison is meaningless: different chunking and different prompts make any score gap
unattributable.

Restructured so documents are redacted and chunked once, and all three retrievers select
from the same immutable `chunk_id` set feeding one prompt template. Retrieval becomes the
only variable.

This also turned out to be the design that makes vector→graph migration cheap, which became
`docs/GRAPHRAG.md` §5.

---

### D4. Graph traversal returns chunks, not triples

Follows from D3. Feeding triples to the LLM would change the generation stage and break the
comparison. `MENTIONED_IN` (entity → chunk) is the bridge back to retrievable text.

---

### D5. Greedy relation capture fragmented the graph

**Symptom:** 82 entities, 47 connected components, largest component 15.9%.

**Cause:** the object capture group `[\w\-. ]{2,60}` is greedy. Against

> The checkout-api depends on payments-gateway for authorisation of every order.

it produced the entity `payments-gateway for authorisation of every order` — one real entity
plus a subordinate clause, unmergeable with the clean `payments-gateway` node elsewhere.

**Fix:** trim every captured span at the first connector word (`for`, `during`, `with`,
`that`, `because`, …), strip leading articles, and cap at four words.

**Result:** 72 entities, 39 components, largest component 44.4%. Clean chain now extracts:

```
checkout-api -[DEPENDS_ON]-> payments-gateway -[OWNED_BY]-> Team Meridian -[ESCALATES_TO]-> Priya Raman
```

Still not good enough — see D9.

---

### D6. Hop decay of 0.62 made multi-hop retrieval pointless

**Symptom:** the graph lane returned only hop-0 chunks. The 3-hop answer chunk (`Priya
Raman`) sat at rank 5 despite the correct path existing in the graph.

**Cause:** at decay 0.62, a 3-hop result scores 0.24 of a 0-hop mention. Any chunk that
merely name-drops the seed entity outranks the chunk the traversal was built to find.

**Fix:** decay 0.85, plus two ranking terms (D7, D8).

Lesson: hop decay is not a cosmetic tuning constant. Set too aggressively it silently
disables the feature while everything still "works".

---

### D7. Document headers were winning on reachability

A chunk that names twenty services is reachable from twenty seeds while being *about*
nothing. Added `/√(entities mentioned in chunk)` — the same saturation idea as TF
normalisation in BM25.

---

### D8. Unweighted term overlap ranked the answer fifth

**Symptom:** after D6 and D7, the correct chunk still lost. Its relevance score was 0.33
against 0.17 for the wrong chunks — better, but not enough to overcome the reachability gap.

**Cause:** relevance counted every matched term equally. The query
`Who should I escalate to if checkout-api is failing because of a payment problem?` tokenises
to `{because, checkout-api, escalate, fail, payment, problem}`. Matching `escalate` — which
appears in almost nothing — counted the same as matching `payment`.

Also: no stemming, so `escalate` in the question failed to match `escalates` in the chunk at
all.

**Fix:** suffix stemming, plus IDF-weighted relevance with corpus-absent query terms excluded
from the denominator (`because`, `problem` can never be matched by anything, so counting them
only flattens scores).

**Result:** the answer chunk moved to rank 1 with the correct 2-hop path shown, while lexical
and vector both miss it entirely.

---

### D9. Entity resolution stops at ladder step 3 — known debt

Current state: ~42 components across ~90 entities on the demo corpus.

Steps 1–3 (normalise → alias map → cheap variant matching) are implemented. Step 4
(embedding-based clustering at cosine ≥ 0.85) is not. That's the gap.

Not fixed yet because it needs the embedder available inside `GraphStore`, which currently
has no dependency on `app.embed` — a deliberate layering choice worth keeping. The fix is to
pass an optional encoder into the constructor.

Surfaced as a warning in the UI rather than hidden, because component count is the single
best predictor of whether traversal will work at all.

---

### D10. Demo corpus needed 33 error codes, not 7

**Symptom:** on `What causes ERR-7741?`, all three strategies returned the correct chunk at
rank 1. No differentiation — the "lexical wins on exact identifiers" claim was unsupported.

**Cause:** with 17 chunks, `bge-small` has no trouble finding the right one. The claim is
true at scale and false at toy scale.

**Fix:** expanded the error reference to 33 structurally identical entries. Now lexical
ranks the exact chunk 1, vector ranks it 2–3.

Worth stating plainly: this is a *demo corpus designed to expose a real effect*, not evidence
of the effect's magnitude on your corpus.

---

### D11. Readiness analyzer scored a marketing page 98 on lexical anchors

The kebab-case identifier pattern matched `world-class` and `next-generation`. A page made
almost entirely of marketing adjectives scored near-perfect on "has rare technical
identifiers" — the exact opposite of the truth.

**Fix:** an anchor must contain a digit, or have at least one segment that isn't a common
English compound word.

---

### D12. Extractive fallback is a feature, not a stopgap

Without `GROQ_API_KEY` the system answers by ranking and returning context sentences, flagged
`degraded: true`.

This keeps the app usable offline, rate-limited, or key-less, and every result stays
comparable because the fallback is identical across all strategies. It also gives the
groundedness metric a useful floor: extraction *cannot* hallucinate, so a degraded run
showing low groundedness means the metric is measuring something other than hallucination.

---

### D13. Single uvicorn worker is a constraint, not an oversight

With in-process backends, indexes live in process memory. `--workers 2` gives each worker a
different graph and different vectors, and requests hit either nondeterministically — a
phantom bug that costs hours to diagnose.

Documented in `start.sh`, `docs/INFRASTRUCTURE.md`, and the UI's Architecture tab. Removing
the constraint means moving state to Neo4j + Chroma, both of which are implemented behind
`GRAPH_BACKEND` / `VECTOR_BACKEND`.
