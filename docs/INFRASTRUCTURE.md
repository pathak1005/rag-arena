# Infrastructure specification

## Runtime topology

One container, two processes, one worker each.

```
container
├── uvicorn app.main:app   :8000   (1 worker - see "Why one worker")
└── streamlit ui/…         :8501   (public surface)
```

Streamlit is a pure HTTP client of the API. It never imports `app.*` pipeline modules.
Importing them would build a second copy of every index inside the Streamlit process,
doubling memory and letting the two copies drift.

## Why one worker

With the default in-process backends, the BM25 index, the embedding matrix, and the graph
all live in process memory. `--workers 2` gives each worker a *different* graph and a
*different* vector index, and requests land on either one nondeterministically. That
presents as a phantom bug: the same question returns different sources depending on which
worker answered.

Removing the constraint means moving state out of the process. Both paths are implemented:

| Backend | Env | Effect |
| --- | --- | --- |
| Neo4j | `GRAPH_BACKEND=neo4j` | Graph becomes shared and persistent |
| ChromaDB | `VECTOR_BACKEND=chroma` | Vectors become shared and persistent |

The BM25 index is still per-process; with both backends switched, that is the remaining
blocker for multi-worker. Elasticsearch/OpenSearch is the natural swap, and `lexical.py`
has exactly two functions to reimplement.

## Resource sizing

| Component | Steady | Peak |
| --- | --- | --- |
| uvicorn + FastAPI | ~90 MB | ~120 MB |
| fastembed ONNX session | ~180 MB | ~260 MB during first encode |
| Streamlit | ~130 MB | ~200 MB |
| Indexes (51 chunks) | ~5 MB | grows linearly |

**1 GB minimum on Fly.** 512 MB OOMs during the first embed call, and it presents as a
connection reset rather than an OOM message, which is a miserable thing to debug.

Estimates from local observation, not from production load testing.

## Image size

The dominant lever is the embedding stack.

| Choice | Image |
| --- | --- |
| `sentence-transformers` (pulls torch) | ~2.5 GB |
| **`fastembed` (ONNX runtime)** | **~400 MB** |

Multi-stage build: stage 1 builds a venv, stage 2 copies only `/opt/venv` plus application
code. No build toolchain in the runtime layer.

The embedding model is **baked into the image** at build time. Without that, the first
request after every cold start pays a ~130 MB download, which on Fly reads as a broken
deploy rather than a slow one.

## Deployment

```bash
fly launch --no-deploy      # first time only
fly deploy
fly logs
```

`fly.toml` notes:

- `internal_port = 8501` — Streamlit is the public surface. The API is reachable
  in-container at `127.0.0.1:8000`. Uncomment the `[[services]]` block to expose it publicly.
- `auto_stop_machines = "suspend"` and `min_machines_running = 0` — scales to zero. Cold
  start is roughly 8 s with the model baked in.
- Health check hits `/_stcore/health` (Streamlit) with a 45 s grace period, because the API
  readiness wait in `start.sh` runs first.

## Process supervision

`start.sh` handles two things that are easy to get wrong:

1. **Ordered startup.** Streamlit rendering before the API can answer produces a confusing
   connection error on first paint. The script polls `/health` for up to 45 s rather than
   sleeping a fixed amount, and exits if the API dies during startup.
2. **Signal handling.** Fly sends SIGTERM on deploy and shutdown. Without the trap, children
   survive as zombies and the machine never drains cleanly. `wait -n` also means the
   container exits if *either* process dies, so the orchestrator restarts it rather than
   leaving a half-dead machine serving errors.

## Local development

```powershell
.\run.ps1              # venv + API + UI
.\run.ps1 -Neo4j       # also starts Neo4j via docker compose
```

```bash
make install
make api               # terminal 1
make ui                # terminal 2
make neo4j             # optional: Neo4j on :7474 / :7687
```

## Configuration

Everything is environment-driven; see `.env.example`. Nothing is required — the app boots
with zero configuration and reports what it fell back to.

| Variable | Default | Effect |
| --- | --- | --- |
| `GROQ_API_KEY` | unset | Without it, deterministic extractive answers, `degraded: true` |
| `GRAPH_BACKEND` | `networkx` | `neo4j` for the persistent path |
| `VECTOR_BACKEND` | `numpy` | `chroma` for the persistent path |
| `LANGCHAIN_API_KEY` | unset | Mirrors agent traces to LangSmith; local tracer runs regardless |
| `TOP_K` | 3 | Chunks per retrieval |
| `CHUNK_TOKENS` / `CHUNK_OVERLAP` | 110 / 25 | Chunking; changing these invalidates comparisons |
| `GRAPH_MAX_HOPS` | 3 | Traversal depth; 4+ explodes the candidate set |

## Failure behaviour

Every external dependency degrades rather than failing to boot. This is deliberate: a demo
that dies because a database is asleep is worse than a demo that says which database is
asleep.

| Failure | Behaviour | Visible where |
| --- | --- | --- |
| Neo4j unreachable | Falls back to NetworkX at startup | `GET /backends` |
| ChromaDB import fails | Falls back to numpy exact search | `GET /backends` |
| Model download blocked | Falls back to TF-IDF/SVD, labelled | `GET /health` |
| Groq unavailable or rate-limited | Extractive fallback per request | `degraded: true` |
| LangSmith not configured | Local tracer only | `GET /traces` |

## Security posture

- Container runs as non-root (`appuser`, uid 10001).
- Uploads capped at 5 MB, extension-allowlisted.
- PII redacted before chunking, embedding, or LLM contact; raw values never returned by any
  endpoint.
- No secrets in the image — `.env` is gitignored and Fly secrets are runtime-injected.
- No authentication. This is a single-tenant demonstrator; do not put real corporate
  documents in a public deployment of it.

## Not done

- No load testing. Concurrency limits in `fly.toml` are estimates.
- No persistent volume for Chroma on Fly, so the Chroma path loses data on machine
  replacement. Needs a `[mounts]` block.
- No CI. A GitHub Actions workflow running import checks and the smoke test is the obvious
  next step.
- Neo4j path is functionally tested but not load tested; the per-mention write pattern in
  `add_mention` issues one transaction per entity per chunk and would need batching for a
  corpus of any size.
