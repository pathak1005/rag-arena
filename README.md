# RAG Arena — Lexical vs. Vector vs. Graph retrieval, measured

An enterprise RAG reference implementation that runs **three retrieval strategies over one
identical chunk set** and scores each answer deterministically, so you can see *which*
strategy wins *which* kind of question — and why.

It also ships the parts that usually get bolted on last: PII redaction before indexing,
a content-readiness analyzer, and an API playground that explains what a response actually
means.

```
                      ┌─ BM25 index        → lexical retriever ─┐
Document → PII scrub → ┼─ embeddings        → vector retriever  ─┼→ chunk_ids → ONE prompt → LLM
          → chunk ONCE └─ entities/relations → graph retriever  ─┘         │
                                                                    RRF fusion → hybrid
```

---

## The one design decision everything rests on

Documents are redacted and chunked **exactly once**. All three retrievers select from that
same immutable `chunk_id` set, and all three feed the **same prompt template**.

This matters more than it sounds. Most "Graph RAG vs Vector RAG" comparisons use different
chunking, different context sizes, and different prompts for each pipeline — which makes any
score difference unattributable. Here retrieval is the only variable, so a difference in
score is a difference in retrieval.

The same decision is what makes graph RAG *cheap to adopt*: the graph is an index built
alongside your existing chunks, not a replacement pipeline. See
[docs/GRAPHRAG.md](docs/GRAPHRAG.md) for the migration playbook.

---

## When does each strategy actually win?

The demo corpus is engineered so each strategy has a question it provably wins. These are
real results from `data/demo_corpus` (51 chunks, 60 relations):

| Question | Winner | Result | Why the others fail |
| --- | --- | --- | --- |
| `What causes ERR-7741?` | **Lexical** | lexical rank 1, vector rank 2 | 33 near-identical error-code chunks. Dense vectors compress the rare token toward its siblings; BM25 scores the literal term. |
| `How do we stop customer data leaking into our logs?` | **Vector** | vector finds the right doc; source shares almost no vocabulary with the query | The document says "subscriber identifiers" and "accidental disclosure", never "customer data" or "leaking". BM25 has nothing to match. |
| `Who should I escalate to if checkout-api is failing because of a payment problem?` | **Graph** | graph rank 1, **lexical and vector both miss it entirely** | The answer spans three documents: `checkout-api →DEPENDS_ON→ payments-gateway →OWNED_BY→ Team Meridian →ESCALATES_TO→ Priya Raman`. No single chunk contains it. |

The router classifies each question and picks a lane **before** retrieval, showing the
signals it used. On the three cases above it is correct 3/3.

The honest conclusion the project lands on is not "graph RAG is better". It is **route** —
the three strategies fail in different, predictable places, so pick per query.

---

## Quick start

Requires **Python 3.12** (3.13/3.14 wheels for the ML stack are still unreliable).

```powershell
git clone https://github.com/pathak1005/rag-arena.git
cd rag-arena
.\run.ps1                      # creates venv, installs, starts API + UI
```

Or manually:

```bash
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m uvicorn app.main:app --port 8000    # terminal 1
.venv/Scripts/python -m streamlit run ui/streamlit_app.py   # terminal 2
```

- UI → http://localhost:8501
- OpenAPI docs → http://localhost:8000/docs

Click **Load demo corpus** in the sidebar, then try the three example questions on the Chat tab.

**No API key needed.** Without `GROQ_API_KEY` the system answers using a deterministic
extractive fallback and flags `degraded: true`. Retrieval metrics stay valid and comparable —
only answer fluency changes.

---

## What's in the box

| Feature | Where |
| --- | --- |
| **Chat** with routing explanation and per-chunk source attribution | UI → Chat |
| **Multi-agent pipeline** (LangGraph) with self-correcting re-routing | UI → Agent Pipeline |
| **Evaluation Arena** — all lanes side by side, scored | UI → Evaluation Arena |
| **RAG Readiness analyzer** — paste any page, get a 0–100 score and specific fixes | UI → RAG Readiness |
| **API Playground** — send real requests, get annotated explanations of the response | UI → API Playground |
| **Knowledge graph viewer** with component-count health warning | UI → Knowledge Graph |
| **PII redaction** before chunking/embedding/LLM, with audit report | UI → Ingestion |
| **Content Briefs** — auto-generated markdown brief per document | UI → Ingestion |

Backends are pluggable and fall back rather than failing to boot:

| Concern | Default (zero infra) | Production path |
| --- | --- | --- |
| Graph | NetworkX, in-process | **Neo4j** (`GRAPH_BACKEND=neo4j`) |
| Vectors | numpy exact search | **ChromaDB** (`VECTOR_BACKEND=chroma`) |
| Embeddings | fastembed / ONNX (`bge-small-en-v1.5`) | same — no torch anywhere |
| Generation | extractive fallback | Groq `llama-3.3-70b-versatile` |

Running Neo4j locally takes one command, and [docs/LEARN.md](docs/LEARN.md) has the Cypher
queries to explore the graph in Neo4j Browser:

```bash
docker compose up -d neo4j     # http://localhost:7474 — neo4j / helios-dev-password
GRAPH_BACKEND=neo4j .venv/Scripts/python -m uvicorn app.main:app --port 8000
```

---

## The agent layer, and why it isn't decoration

Most "agentic RAG" is a linear pipeline wearing a costume. The LangGraph layer here exists
for one behaviour a linear pipeline cannot do:

> **If retrieval was bad, re-route to a different strategy and try again.**

That falls directly out of the routing thesis. If the three lanes fail in different,
predictable places, a grader that detects "this retrieval failed" should hand the query to a
lane that fails *differently* — rather than letting the generator produce fluent prose over
irrelevant passages, which is the most dangerous failure mode in RAG because it looks like
success.

```
plan ──> retrieve ──> grade ──┬── context sufficient ──> synthesize ──> verify ──> END
  ▲                           │
  └────── re-route ◄──────────┘   context weak, attempts remaining
```

Real behaviour on an out-of-corpus question — three lanes attempted, all rejected by the
grader, then an honest abstention rather than a confident invention:

```
plan → retrieve → grade    lexical,  context relevance 0.000, rejected
plan → retrieve → grade    vector,   context relevance 0.000, rejected
plan → retrieve → grade    hybrid,   context relevance 0.000, rejected
synthesize → verify        "The provided context does not contain this information."
```

**Grading and verification are deterministic, not LLM-judged.** An LLM grading its own
retrieval and then its own answer compounds the same bias twice — if it finds a passage
plausible, it will find its answer from that passage plausible too. The loop couldn't detect
the failure it's most likely to make. Full reasoning in [docs/AGENTS.md](docs/AGENTS.md).

### Observability

Two sinks, one always available:

- **Local tracer** — every span (name, duration, inputs, outputs, notes) recorded in-process,
  exposed at `GET /traces` and rendered as a waterfall in the UI. No account, no key, works
  offline.
- **LangSmith** — set `LANGCHAIN_API_KEY` and the same spans mirror there automatically.

Local-first is deliberate: a project whose observability requires the reader to sign up for a
SaaS account has no observability story, because nobody evaluating it will ever see a trace.

---

## Evaluation: what these numbers do and don't prove

Every metric in the UI is **Tier-1 deterministic** — computed with no LLM in the loop, so it
reproduces exactly run to run.

This is deliberate. Using `llama-3.3-70b` to grade `llama-3.3-70b`'s own output is neither
independent nor deterministic, and anyone who works on evals will say so within a minute.

| Metric | Catches | Does **not** catch |
| --- | --- | --- |
| **Groundedness** | Confabulated content not traceable to context | A fluent answer that reuses context words in a *wrong relationship* |
| **Entity leakage** | Fabricated identifiers, codes, names, numbers — the sharpest available hallucination signal | Wrong claims made only with words already in context |
| **Context relevance** | Whether *retrieval* failed, separately from generation | Whether the retrieved chunk actually answers the question |
| **Citation coverage** | Answer sentences with no supporting chunk | Correctly-cited but misinterpreted sources |
| **Extractiveness** | Verbatim copying (diagnostic, not directional) | — |

An honest "I don't know" scores as **grounded**, not as a hallucination. Scoring abstention
as failure rewards models that bluff.

**What's missing:** a labelled gold set. Without one, the arena demonstrates mechanism, not
accuracy. Building one (30–40 questions stratified by query type) is the top item in
[docs/PLAN.md](docs/PLAN.md), and it's what would turn this from a demo into a benchmark.

---

## Documentation

| Document | What it covers |
| --- | --- |
| [docs/GRAPHRAG.md](docs/GRAPHRAG.md) | How graph RAG works here, the data model, and **how to convert an existing vector RAG to graph RAG** without re-chunking or re-embedding |
| [docs/PLAN.md](docs/PLAN.md) | Build plan, phase status, what's done and what isn't |
| [docs/FEATURES.md](docs/FEATURES.md) | Feature specification with acceptance criteria |
| [docs/INFRASTRUCTURE.md](docs/INFRASTRUCTURE.md) | Deployment, resource sizing, scaling limits |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Engineering log — the things that broke and what fixed them |
| [docs/AGENTS.md](docs/AGENTS.md) | Multi-agent design, why grading is deterministic, and observability |
| [docs/LEARN.md](docs/LEARN.md) | Hands-on Neo4j and ChromaDB guide with runnable queries |

---

## Known limitations

Stated plainly, because a demo that hides its edges isn't useful to learn from.

- **Single uvicorn worker, by necessity.** With the default in-process backends, indexes live
  in process memory; `--workers 2` gives each worker a different graph. Switching to Neo4j +
  Chroma removes this — both are implemented.
- **The graph currently fragments.** The demo corpus produces ~42 connected components across
  ~90 entities. That's the entity-resolution ladder stopping at step 3 (normalise → alias →
  cheap variant matching) without embedding-based clustering. The UI surfaces this as a
  warning rather than hiding it, because component count is the single best predictor of
  whether graph traversal will work.
- **Rule-based relation extraction.** Excellent on structured engineering docs, weak on prose.
  The upgrade is LLM triple extraction against a JSON schema; the `GraphStore` interface
  doesn't change.
- **Routing rules are hand-weighted, not learned.** They're inspectable and correct on the
  demo set, but the weights aren't validated against anything larger.
- **The agent grader catches topical mismatch, not semantic mismatch.** A chunk that shares
  vocabulary with the question but answers a different question will pass. Upgrading `grade`
  to a cross-encoder (still deterministic) is the right next step.
- **The demo corpus is synthetic.** It was written to expose the differences between
  strategies. Real corpora are messier, and results will be less clean.

---

## License

MIT — see [LICENSE](LICENSE).
