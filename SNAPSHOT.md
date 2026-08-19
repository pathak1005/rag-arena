# Project Snapshot

A plain description of what exists in this repository right now. Written to be read start to
finish in about five minutes.

**Repository:** https://github.com/pathak1005/rag-arena
**Live:** https://rag-arena.fly.dev
**Status:** deployed, running on Fly.io (single machine, combined API + UI container)
**Size:** ~6,050 lines of Python across `app/` and `ui/`, ~1,700 lines of documentation

---

## 1. What this is

Two things layered on top of each other:

1. **A portfolio site** for Ashish Pathak (Knowledge Architect, 12+ years) — Home, About, Work,
   and a Playground, all sourced from `data/portfolio.json` rather than hardcoded copy.
2. **A working retrieval-augmented generation system**, embedded in the Playground, that runs
   three retrieval strategies — lexical (BM25), vector (dense embeddings), and graph (entity
   extraction + multi-hop traversal) — over one identical chunk set and scores every answer
   deterministically.

The pitch the site makes about its author is backed by a system a visitor can actually run,
not a claim they have to take on faith.

## 2. The one decision the retrieval demo follows from

Documents are redacted and chunked **exactly once**. All three retrievers select from that same
immutable chunk set, and all three feed the same prompt template. That's what makes a score
difference attributable to retrieval rather than to chunking or prompt differences — and it's
what makes graph RAG cheap to adopt: the graph is an index built *alongside* existing chunks,
not a replacement pipeline.

## 3. What's built

### 3.1 Backend (`app/`, ~4,300 lines)

| Area | File(s) | What it does |
| --- | --- | --- |
| Orchestration | `store.py` (344 lines) | In-process `Engine`: single mutable index, one lock, `ingest()` + `compare()` + `run_strategy()` |
| Retrieval | `retrieval/graph.py` (501), `graph_neo4j.py` (339), `vector.py`/`vector_chroma.py`, `lexical.py`, `fusion.py`, `router.py` | Entity extraction, BFS traversal, BM25, cosine similarity, Reciprocal Rank Fusion, rule-based query routing |
| Agents | `agents/pipeline.py` (295) | LangGraph: plan → retrieve → grade → synthesize → verify, with self-correcting re-routing |
| Generation | `llm.py` (245) | Groq client (`openai/gpt-oss-120b`) + deterministic extractive fallback, `<think>` stripping for reasoning models |
| Evaluation | `evaluate.py` (184) | 4 deterministic metrics, no LLM in the loop |
| Governance | `governance/pii.py` (104) | Regex-first PII redaction before any indexing or LLM contact |
| Readiness | `readiness.py` (329) | Scores arbitrary pasted text 0-100 for retrieval-readiness, six weighted dimensions |
| API | `main.py` (422) | 18 endpoints, all Pydantic-typed, OpenAPI generated |

### 3.2 Frontend (`ui/streamlit_app.py`, 736 lines, single file)

Four tabs: **Home, About, Work, Playground.** Playground has four sub-tabs: Spec Inspector, RAG
Chat, Prompt Evaluator, Format Converter. The UI is a pure HTTP client of the API for live
retrieval (with a 15s-timeout-guarded call and local fallback) and reads `data/portfolio.json`
directly for static profile content — it never imports pipeline code, so there's exactly one
copy of every index, in the API process.

### 3.3 Static SEO/AEO/GEO layer (`public/`)

Served directly by Fly's edge via `[[statics]]`, bypassing the Streamlit app: `robots.txt`
(explicitly allows AI crawlers — GPTBot, ClaudeBot, Google-Extended, PerplexityBot, CCBot),
`sitemap.xml`, `about.html` (static profile page with `schema.org/Person` JSON-LD, since a
client-rendered SPA is close to invisible to crawlers that don't execute JavaScript), and
`llms.txt`. Regenerated from `data/portfolio.json` on every boot by
`scripts/generate_static_profile.py`.

## 4. Backends and fallbacks

Everything degrades rather than failing to boot, and every fallback is reported at
`GET /backends`, not hidden.

| Concern | Default (zero infra) | Production path |
| --- | --- | --- |
| Graph | NetworkX, in-process | Neo4j (`GRAPH_BACKEND=neo4j`) |
| Vectors | numpy exact cosine | ChromaDB (`VECTOR_BACKEND=chroma`) |
| Embeddings | fastembed / ONNX `bge-small-en-v1.5` | same |
| Generation | Groq `openai/gpt-oss-120b` | deterministic extractive fallback, no key needed |

## 5. Deployment

Single Fly.io machine (`sin` region, `shared-cpu-1x`, 512MB), one container running both
processes via `start.sh`: FastAPI on `:8000` (internal only), Streamlit on `:8501` (the public
`internal_port`). Streamlit talks to FastAPI over loopback via `API_BASE`. The Dockerfile bakes
the embedding model in at build time so cold starts don't pay a ~130MB download.

`data/portfolio.json` and `data/demo_corpus/*.md` are committed files, not database rows — on
Fly the container filesystem is ephemeral, so the actual persistence model is: edit in the app,
export, commit, push, redeploy.

## 6. What is NOT built

Stated plainly.

- **No labelled gold set.** The system demonstrates *mechanism* (the three strategies retrieve
  different chunks, explainably) not *accuracy* across a realistic query distribution.
- **The graph fragments** into multiple disconnected components on the demo corpus. Surfaced as
  a UI warning, not hidden.
- **Rule-based relation extraction** — weak on unstructured prose.
- **Routing weights are hand-set**, validated only on the demo corpus.
- **No CI, no load testing.** Auth exists for the admin surface only.
- **The demo corpus is synthetic**, engineered to expose the differences between strategies.

## 7. To run it locally

```bash
git clone https://github.com/pathak1005/rag-arena.git
cd rag-arena
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt

.venv/Scripts/python -m uvicorn app.main:app --port 8000     # terminal 1
.venv/Scripts/python -m streamlit run ui/streamlit_app.py    # terminal 2
```

UI at http://localhost:8501, API docs at http://localhost:8000/docs. Copy `.env.example` to
`.env` and set `GROQ_API_KEY` for live generated answers — without it, `/chat` still works via
a deterministic extractive fallback, flagged `degraded: true`.

Requires **Python 3.12** — 3.13/3.14 wheels for this stack are still unreliable.
