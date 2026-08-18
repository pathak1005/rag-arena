# Project Snapshot

A plain description of what exists in this repository, what it does, and what it does not do
yet. Written to be read start to finish in about five minutes.

**Repository:** https://github.com/pathak1005/rag-arena
**Status:** working locally, all tests passing, not yet deployed
**Size:** ~5,750 lines of Python, ~1,500 lines of documentation, 5 demo documents

---

## 1. What this is

A retrieval-augmented generation system that runs **three different retrieval strategies over
the same set of document chunks** and scores every answer deterministically, so you can see
which strategy wins which kind of question and why.

The three strategies:

- **Lexical (BM25)** — exact keyword matching. The same ranking function Elasticsearch uses.
- **Vector** — dense embedding similarity. Finds paraphrases with no shared words.
- **Graph** — entity extraction plus multi-hop traversal. Assembles answers spread across
  several documents.

Plus a **hybrid** lane that fuses all three with Reciprocal Rank Fusion.

## 2. The one decision everything else follows from

Documents are redacted and chunked **exactly once**. All three retrievers select from that
same immutable chunk set, and all three feed the **same prompt template**.

This is the difference between a comparison that means something and one that doesn't. Most
"Graph RAG vs Vector RAG" write-ups use different chunking and different prompts per pipeline,
so any score gap is unattributable — it could be the chunking, the prompt, or the retrieval.
Here retrieval is the only variable.

The same decision is what makes graph RAG cheap to adopt: the graph is an index built
*alongside* existing chunks, not a replacement pipeline. No re-chunking, no re-embedding.

## 3. What it demonstrates

The demo corpus is deliberately built so each strategy has a question it provably wins.
Measured results (51 chunks, 60 relations extracted):

| Question | Winner | What actually happens |
| --- | --- | --- |
| `What causes ERR-7741?` | **Lexical** | Lexical ranks the exact chunk 1st, vector 2nd–3rd. There are 33 structurally identical error-code entries; dense vectors compress the rare token toward its siblings, BM25 scores the literal term. |
| `How do we stop customer data leaking into our logs?` | **Vector** | The source document says "subscriber identifiers" and "accidental disclosure" — never "customer data" or "leaking". BM25 has almost nothing to match on. |
| `Who should I escalate to if checkout-api is failing because of a payment problem?` | **Graph** | Graph ranks the answer 1st with an explicit traversal path. **Lexical and vector both miss it entirely.** The answer spans three documents: `checkout-api →DEPENDS_ON→ payments-gateway →OWNED_BY→ Team Meridian →ESCALATES_TO→ Priya Raman`. |

A **router** classifies each question and picks a lane *before* retrieval runs, showing the
signals it used. It is correct on 3/3 of these.

**The conclusion the project lands on is not "graph RAG is better."** It is *route* — the
three strategies fail in different, predictable places, so pick per query.

---

## 4. What is built

### 4.1 Retrieval (`app/retrieval/`)

| File | Lines | What it does |
| --- | --- | --- |
| `graph.py` | 501 | Entity extraction, resolution ladder, BFS traversal, two-factor ranking |
| `graph_neo4j.py` | 339 | Same interface backed by real Cypher, including `shortestPath` traversal |
| `router.py` | 175 | Rule-based query classifier with inspectable signals |
| `vector_chroma.py` | 127 | ChromaDB backend (HNSW, persistent) |
| `lexical.py` | 102 | BM25Okapi index and retrieval |
| `vector.py` | 74 | Exact cosine over a numpy matrix |
| `fusion.py` | 59 | Reciprocal Rank Fusion, k=60 |

Graph traversal returns **chunks, not triples**, via a `MENTIONED_IN` edge from entity to
chunk. That is what keeps the generation stage identical across all lanes.

Graph ranking is two-factor and each term was added because the correct answer was ranking
too low without it:

```
score = (seed_strength × 0.85^hops / √(entities in chunk)) × (0.10 + 0.90 × idf_relevance)
```

### 4.2 Multi-agent pipeline (`app/agents/pipeline.py`, 295 lines)

A LangGraph state machine with five single-responsibility nodes:

```
plan ──> retrieve ──> grade ──┬── context sufficient ──> synthesize ──> verify ──> END
  ▲                           │
  └────── re-route ◄──────────┘   context weak, attempts remaining
```

The agent layer exists for exactly one behaviour a linear pipeline cannot do: **if retrieval
was bad, re-route to a different strategy and try again.** That falls directly out of the
routing thesis.

Only `synthesize` calls a model. **Grading and verification are deterministic** — an LLM
grading its own retrieval and then its own answer compounds the same bias twice and makes the
loop unfalsifiable.

Observed on an out-of-corpus question: three lanes attempted (`lexical → vector → hybrid`),
all rejected by the grader at context relevance 0.000, then an honest abstention rather than
a confident invention.

### 4.3 Evaluation (`app/evaluate.py`, 184 lines)

Five metrics, all **Tier-1 deterministic** — no LLM anywhere in the scoring path, so results
reproduce byte-for-byte run to run.

| Metric | Catches |
| --- | --- |
| Groundedness | Answer content not traceable to the retrieved context |
| Entity leakage | Fabricated identifiers, codes, names, numbers — the sharpest available hallucination signal |
| Context relevance | Isolates *retrieval* failure from *generation* failure |
| Citation coverage | Answer sentences with no supporting chunk |
| Extractiveness | Verbatim copying (diagnostic, not directional) |

An honest "I don't know" scores as **grounded**, not as a hallucination. Scoring abstention
as failure rewards models that bluff.

### 4.4 Governance (`app/governance/pii.py`, 104 lines)

Regex-first detection and redaction of EMAIL, PHONE, SSN, CREDIT_CARD (Luhn-validated),
IP_ADDRESS, AWS_KEY — applied **before** chunking, embedding, or any LLM contact.

Raw values are never returned by any endpoint; the audit trail carries masked previews only.
A test asserts that no raw email survives into any indexed chunk.

### 4.5 RAG-readiness analyzer (`app/readiness.py`, 329 lines)

Paste any page, get a 0–100 score with specific, evidence-backed findings. Nothing is stored
or indexed.

Six weighted dimensions: self-containment (0.26), structure (0.22), entity clarity (0.18),
relational density (0.14), lexical anchors (0.10), governance (0.10).

Self-containment carries the most weight because a chunk that opens with "It handles retries"
becomes unusable the moment it is separated from the paragraph that named "it" — and that
stays invisible until retrieval quality is already bad.

Measured discrimination: a well-structured document scores **90**; a page built from anaphora,
positional cross-references and marketing language scores **48**.

### 4.6 Response explainer (`app/explain.py`, 298 lines)

Powers the API playground. Turns a raw API response into plain statements about what is
trustworthy and what is not — because a 200 OK with a fluent answer can still be a total
failure.

Example observations it produces: "Graph lane ran with no seed entities" (bad), "Strategies
returned nearly identical chunks — this question does not discriminate" (warning), "Entity
leakage 0.33 — the answer asserts identifiers absent from the retrieved context" (bad).

### 4.7 Observability (`app/observability.py`, 155 lines)

Every agent span recorded in-process: name, status, duration, inputs, outputs, notes. A
50-entry ring buffer, exposed at `GET /traces`, rendered as a waterfall in the UI.

**Local-first by design.** A project whose observability requires the reader to sign up for a
SaaS account has no observability story, because nobody evaluating it will ever see a trace.
LangSmith is an optional *additional* sink when `LANGCHAIN_API_KEY` is set.

### 4.8 Content briefs (`app/ingest/brief.py`, 238 lines)

On ingestion, generates a markdown brief per document: summary, taxonomy tags, key themes,
knowledge-graph contribution with sample triples, governance report, and a per-strategy
retrieval profile. Downloadable.

The skeleton is deterministic so a brief is always produced and always diffable in git; the
LLM only enriches the summary.

### 4.9 API (`app/main.py`, 396 lines) — 18 endpoints

```
/health  /backends  /                          system
/upload  /ingest_text  /seed_demo  /documents  /brief/{id}  /reset   ingestion
/chat  /query_compare  /route  /graph                        retrieval
/agent_query  /traces  /traces/{id}                          agents
/analyze_readiness  /explain                                 governance
```

Every response is a declared Pydantic model, so the OpenAPI spec is generated rather than
maintained.

### 4.10 UI (`ui/streamlit_app.py`, 1,100 lines) — 8 tabs

Chat · Agent Pipeline · Evaluation Arena · RAG Readiness · API Playground · Knowledge Graph ·
Ingestion & Governance · Architecture

The UI is a **pure HTTP client** of the API and never imports pipeline code. Importing it
would build a second copy of every index inside the Streamlit process.

---

## 5. Backends

Everything falls back rather than failing to boot, and every fallback is **reported, not
hidden** (`GET /backends`).

| Concern | Default (zero infrastructure) | Production path |
| --- | --- | --- |
| Graph | NetworkX, in-process | Neo4j — `GRAPH_BACKEND=neo4j` |
| Vectors | numpy exact cosine | ChromaDB — `VECTOR_BACKEND=chroma` |
| Embeddings | fastembed / ONNX `bge-small-en-v1.5` | same — no torch anywhere |
| Generation | deterministic extractive fallback | Groq `llama-3.3-70b-versatile` |

The app runs with **zero configuration and no API key**. Without `GROQ_API_KEY` it answers
extractively and flags `degraded: true`; retrieval metrics stay valid and comparable.

Choosing fastembed over sentence-transformers is the single biggest deployment lever:
**~400 MB image instead of ~2.5 GB**, because sentence-transformers pulls torch.

---

## 6. Infrastructure

- **Dockerfile** — multi-stage, non-root user, embedding model baked in at build time so cold
  starts don't pay a 130 MB download
- **fly.toml** — single machine, 1 GB (512 MB OOMs during the first embed call), scale-to-zero
- **docker-compose.yml** — local Neo4j with a health check that tests HTTP readiness, not just
  Bolt acceptance
- **start.sh** — runs both processes, waits for API health before starting the UI, traps
  SIGTERM so Fly can drain cleanly
- **run.ps1 / Makefile** — local development

**One uvicorn worker, by necessity.** With in-process backends the indexes live in process
memory; `--workers 2` gives each worker a different graph and requests land on either
nondeterministically. Switching to Neo4j + Chroma removes this.

---

## 7. Tests

9 smoke tests, all passing, offline, no API key required. They assert the behaviours the
README claims, so a regression means the documentation has become a lie:

- No raw email survives into any indexed chunk
- The PII audit trail does not leak raw values
- All strategies select from the same chunk table (the core design invariant)
- The router picks the expected lane on the demo cases
- Graph surfaces the multi-hop answer with a traversal path
- Metrics are byte-identical across repeated runs
- Abstention is not scored as hallucination
- The readiness analyzer discriminates good from bad content
- The agent self-correction loop fires on an unanswerable query

---

## 8. Documentation

| Document | Lines | Covers |
| --- | --- | --- |
| `README.md` | 231 | Overview, quick start, when each strategy wins, honest limitations |
| `docs/LEARN.md` | 267 | Hands-on Neo4j and ChromaDB with runnable queries |
| `docs/GRAPHRAG.md` | 254 | Graph RAG design and the vector→graph migration playbook |
| `docs/DECISIONS.md` | 187 | Engineering log — 13 entries of what broke and what fixed it |
| `docs/AGENTS.md` | 164 | Multi-agent design, why grading is deterministic, observability |
| `docs/INFRASTRUCTURE.md` | 157 | Deployment, sizing, failure behaviour, security posture |
| `docs/FEATURES.md` | 151 | Feature spec with acceptance criteria and "broken if" conditions |
| `docs/PLAN.md` | 73 | Phase status and ordered backlog |

`docs/DECISIONS.md` is the one worth reading if you want to know whether this was actually
built or just assembled. Sample entries: hop decay at 0.62 buried the 3-hop answer at rank 5;
greedy regex capture produced entities like `payments-gateway_for_authorisation_of_every_order`
and fragmented the graph into 47 components; the readiness analyzer scored a pure-marketing
page 98/100 on "technical identifiers" because `world-class` matched the kebab-case pattern.

---

## 9. What is NOT built

Stated plainly, because a project that hides its edges is not useful to learn from.

**No gold set.** This is the big one. Without labelled questions, the system demonstrates
*mechanism* — that the strategies retrieve different chunks and the differences are
explainable. It does **not** demonstrate *accuracy* — how often each is right across a
realistic query distribution. Those are different claims, and conflating them is the most
common overclaim in RAG portfolio projects. This is Phase 8 and the highest-value work
remaining.

**The graph fragments.** ~42 connected components across ~90 entities. The entity-resolution
ladder stops at step 3 (normalise → alias map → cheap variant matching) without embedding-based
clustering. The UI surfaces this as a warning rather than hiding it, because component count
is the single best predictor of whether traversal will work.

**Other gaps:**

- Rule-based relation extraction — strong on structured engineering docs, weak on prose
- Routing weights are hand-set, validated only on the demo corpus
- The agent grader catches topical mismatch, not semantic mismatch
- Not deployed; cold-start numbers in the docs are estimates
- No CI, no load testing, no authentication
- Neo4j write pattern issues one transaction per entity per chunk — fine at 51 chunks, wrong
  at 50,000
- The demo corpus is synthetic, written to expose real effects; real corpora are messier

---

## 10. To run it

```bash
git clone https://github.com/pathak1005/rag-arena.git
cd rag-arena
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt

.venv/Scripts/python -m uvicorn app.main:app --port 8000     # terminal 1
.venv/Scripts/python -m streamlit run ui/streamlit_app.py    # terminal 2
```

UI at http://localhost:8501, API docs at http://localhost:8000/docs. Click **Load demo
corpus**, then try the three example questions on the Chat tab.

Optional: copy `.env.example` to `.env` and set `GROQ_API_KEY` for real generated answers,
`PORTFOLIO_URL` / `CALENDLY_URL` for the sidebar links, and `LANGCHAIN_API_KEY` to mirror
traces to LangSmith.

Requires **Python 3.12** — 3.13 and 3.14 wheels for this stack are still unreliable.
