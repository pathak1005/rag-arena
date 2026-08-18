# Enterprise RAG Arena

**Professional Portfolio + Knowledge Architecture Showcase**

A multi-strategy retrieval arena demonstrating three retrieval approaches (lexical BM25, semantic vector, multi-hop graph) over identical content, with deterministic evaluation metrics and portfolio management for **Ashish Pathak** — 12+ years knowledge architecture expertise.

## Features

- **Three Retrieval Strategies**
  - Lexical (BM25): keyword matching
  - Vector (semantic): dense embeddings via fastembed
  - Graph (multi-hop): entity extraction + traversal

- **Hybrid Approaches**
  - Hybrid RAG: vector→entity→traverse pipeline
  - Hybrid Graph: dual-stage entity confirmation
  - Reciprocal Rank Fusion: multi-stage fusion

- **Governance & Safety**
  - PII redaction at ingestion (email, phone, SSN, credit card, IP, AWS keys)
  - Deterministic evaluation (groundedness, context relevance, entity leakage, citation coverage)
  - Copy prevention (CSS-based user-select: none on public content)
  - Admin-only portfolio management (/admin)

- **Portfolio & Resume**
  - Git-backed storage: `data/portfolio.json`
  - Edit, export, commit workflow
  - Resume upload (PDF/DOCX) or external link
  - Read-only viewing with anti-copy CSS

- **Multi-Agent Pipeline**
  - LangGraph: plan → retrieve → grade → synthesize → verify
  - Self-correcting with strategy retry (up to 3 attempts)
  - Built-in observability (LangSmith traces)

## Deployment

**Admin Panel:** `/admin` (requires authentication)
- Email: `ashishpathak1005@gmail.com`
- Requires GROQ_API_KEY

**Demo:** `/` → **Demo** tab
- Sample chat with RAG comparison
- Text-to-graph conversion
- Document upload & readiness analysis
- API documentation

**Tabs:**
1. **Home** — Portfolio & professional summary
2. **Demo** — Interactive playground (4 subtabs)
3. **Admin** — Resume, profile, portfolio export (auth required)

## Environment Setup

Required:
- `GROQ_API_KEY` — [Get from console.groq.com](https://console.groq.com)

Optional:
- `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` — for persistent graph backend (defaults to in-memory NetworkX)
- `CHROMA_PATH` — for persistent vector backend (defaults to in-memory numpy)
- `LANGSMITH_API_KEY` — for trace observability (defaults to local ring buffer)

## Persistence

On ephemeral containers (HF Spaces, Fly.io, Render):
- Portfolio state is **lost on restart**
- **Solution:** Export portfolio.json from Admin → Commit to git → Redeploy
- On next boot, `data/portfolio.json` loads automatically

To persist resume changes:
1. Edit in Admin tab
2. Click **"Save changes"**
3. Click **"Export portfolio.json"**
4. Commit file to git: `git add data/portfolio.json && git commit -m "Update resume"`
5. Push to repo
6. Redeploy Space

## API Documentation

Full interactive docs at `/docs` (Swagger UI) and `/redoc` (ReDoc).

### Key Endpoints

**Query & Retrieval:**
- `POST /query_compare` — Run all strategies on one question
- `POST /chat` — Single-answer chat with automatic strategy routing
- `POST /agent_query` — Multi-agent pipeline with self-correction

**Content Readiness:**
- `POST /analyze_readiness` — Score arbitrary text for retrieval-readiness without indexing

**Explanation:**
- `POST /explain` — Interpret responses (trustworthiness, citation quality, metrics)

**System:**
- `GET /health` — Real index state (n_documents, n_chunks, n_entities, etc.)
- `GET /backends` — Active storage engines

## Copy Prevention

All public content (Home, Demo) uses CSS:
```css
.readonly {
  user-select: none;
  -webkit-user-select: none;
  -moz-user-select: none;
  -ms-user-select: none;
}
```

Prevents `Ctrl+C` copy in browsers (Chrome, Firefox, Safari, Edge).

## Contact

**Ashish Pathak**
- Email: [ashishpathak1005@gmail.com](mailto:ashishpathak1005@gmail.com)
- Book time: [calendly.com/ashishpathak1005/30min](https://calendly.com/ashishpathak1005/30min)

---

**Built with:** FastAPI • Streamlit • fastembed • Groq • LangGraph • NetworkX
