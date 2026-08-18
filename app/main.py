"""FastAPI application - API-first, contract-first.

Every response is a declared Pydantic model, so /docs is generated rather than
maintained. The Streamlit UI is a pure HTTP client of this API and never imports a
pipeline module; that is what keeps exactly one copy of each index in one process.
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.security import APIKeyHeader
from fastapi.responses import JSONResponse, PlainTextResponse

from app.config import CORPUS_DIR, GROQ_MODEL, TOP_K
from app.embed import get_embedder
from app.llm import llm_available
from app.models import (
    AgentRequest,
    AgentResponse,
    ChatRequest,
    ChatResponse,
    DocSummary,
    ErrorResponse,
    ExplainedResponse,
    GraphSnapshot,
    HealthResponse,
    IngestResponse,
    IngestTextRequest,
    QueryCompareRequest,
    QueryCompareResponse,
    ReadinessReport,
    ReadinessRequest,
    Strategy,
)
from app.security import AUTH_ENABLED, require_api_key
from app.store import get_engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)-14s %(message)s",
)
log = logging.getLogger("rag.api")

VERSION = "1.0.0"

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_SUFFIXES = {".md", ".txt", ".markdown", ".rst", ".pdf"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = get_engine()
    log.info(
        "Startup complete. graph=%s vector=%s embedder=%s llm=%s",
        engine.graph_backend,
        engine.vector_backend,
        get_embedder().mode,
        "groq" if llm_available() else "extractive-fallback",
    )
    yield
    close = getattr(engine.graph, "close", None)
    if close is not None:
        close()


api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)

# One dependency applied at the router level rather than decorating 18 endpoints
# individually - a new endpoint is then protected by default rather than by memory.
PROTECTED = [Depends(require_api_key), Depends(api_key_scheme)] if AUTH_ENABLED else []

app = FastAPI(
    dependencies=PROTECTED,
    title="Enterprise RAG Architecture & Governance Engine",
    version=VERSION,
    description=(
        "Compares lexical (BM25), dense vector, and multi-hop graph retrieval over an "
        "identical chunk set, with PII redaction at ingestion and deterministic "
        "evaluation on every answer."
    ),
    lifespan=lifespan,
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = uuid.uuid4().hex[:12]
    request.state.request_id = request_id
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("[%s] unhandled error on %s %s", request_id, request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error="internal_error",
                detail="An unexpected error occurred. Check server logs for the request id.",
                request_id=request_id,
            ).model_dump(),
        )
    elapsed = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-Ms"] = format(elapsed, ".2f")
    log.info("[%s] %s %s -> %s (%.1fms)", request_id, request.method,
             request.url.path, response.status_code, elapsed)
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error="http_" + str(exc.status_code),
            detail=str(exc.detail),
            request_id=getattr(request.state, "request_id", "unknown"),
        ).model_dump(),
    )


# --------------------------------------------------------------------------
# System
# --------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    """Reports real index state, not just liveness. A green /health that says
    n_chunks=0 has told you something useful; {"ok": true} has not."""
    engine = get_engine()
    embedder = get_embedder()
    snapshot = engine.graph.snapshot(limit=1)
    degraded = not llm_available() or embedder.mode != "fastembed"
    return HealthResponse(
        status="degraded" if degraded else "ok",
        version=VERSION,
        embedder=embedder.model_name,
        embedder_mode=embedder.mode,
        llm_available=llm_available(),
        llm_model=GROQ_MODEL if llm_available() else "extractive-fallback",
        n_documents=len(engine.documents),
        n_chunks=len(engine.chunks),
        n_entities=snapshot.n_entities,
        n_relations=snapshot.n_relations,
        uptime_s=round(time.time() - engine.started_at, 1),
    )


@app.get("/backends", tags=["system"])
def backends() -> dict:
    """Which storage engines are actually live, after fallbacks were applied."""
    engine = get_engine()
    embedder = get_embedder()
    return {
        "graph_backend": engine.graph_backend,
        "vector_backend": engine.vector_backend,
        "embedder_mode": embedder.mode,
        "embedder_model": embedder.model_name,
        "embedding_dim": int(embedder.dim),
        "llm": GROQ_MODEL if llm_available() else "extractive-fallback",
    }


# --------------------------------------------------------------------------
# Ingestion
# --------------------------------------------------------------------------
@app.post("/upload", response_model=IngestResponse, tags=["ingestion"])
async def upload(file: UploadFile = File(...)) -> IngestResponse:
    """Upload a document. PII is redacted before chunking, embedding, or LLM contact."""
    filename = file.filename or "untitled"
    suffix = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type '" + suffix + "'. Allowed: " + ", ".join(sorted(ALLOWED_SUFFIXES)),
        )

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 5 MB limit.")
    if not raw:
        raise HTTPException(status_code=400, detail="File is empty.")

    if suffix == ".pdf":
        try:
            import io

            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(raw))
            text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=422, detail="Could not parse PDF: " + str(exc)) from exc
    else:
        text = raw.decode("utf-8", errors="replace")

    if not text.strip():
        raise HTTPException(status_code=422, detail="No extractable text in the document.")

    try:
        return get_engine().ingest(title=filename, text=text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/ingest_text", response_model=IngestResponse, tags=["ingestion"])
def ingest_text(payload: IngestTextRequest) -> IngestResponse:
    try:
        return get_engine().ingest(
            title=payload.title, text=payload.text, generate_brief=payload.generate_brief
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/seed_demo", tags=["ingestion"])
def seed_demo() -> dict:
    """Load the demo corpus. It is engineered so each retrieval strategy has a query
    it provably wins - see the sample questions in the UI."""
    engine = get_engine()
    if not CORPUS_DIR.exists():
        raise HTTPException(status_code=404, detail="Demo corpus directory not found.")
    loaded = []
    for path in sorted(CORPUS_DIR.glob("*.md")):
        result = engine.ingest(title=path.name, text=path.read_text(encoding="utf-8"))
        loaded.append({
            "doc_id": result.doc_id,
            "title": result.title,
            "chunks": result.n_chunks,
            "pii_redacted": result.pii.total_redacted,
            "relations": result.graph.relations_added,
        })
    snapshot = engine.graph.snapshot()
    return {
        "loaded": loaded,
        "n_documents": len(engine.documents),
        "n_chunks": len(engine.chunks),
        "n_entities": snapshot.n_entities,
        "n_relations": snapshot.n_relations,
    }


@app.get("/documents", response_model=list[DocSummary], tags=["ingestion"])
def documents() -> list[DocSummary]:
    return get_engine().doc_summaries()


@app.get("/brief/{doc_id}", response_class=PlainTextResponse, tags=["ingestion"])
def brief(doc_id: str) -> str:
    engine = get_engine()
    doc = engine.documents.get(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Unknown document id.")
    if not doc.brief_path:
        raise HTTPException(status_code=404, detail="No brief was generated for this document.")
    from pathlib import Path

    return Path(doc.brief_path).read_text(encoding="utf-8")


@app.post("/reset", tags=["ingestion"])
def reset() -> dict:
    get_engine().reset()
    return {"status": "cleared"}


# --------------------------------------------------------------------------
# Retrieval
# --------------------------------------------------------------------------
@app.post("/query_compare", response_model=QueryCompareResponse, tags=["retrieval"])
def query_compare(payload: QueryCompareRequest) -> QueryCompareResponse:
    """Run every requested strategy over the same chunks with the same prompt.

    Identical generation stage is what makes the comparison attributable to
    retrieval rather than to prompt or chunking differences.
    """
    engine = get_engine()
    if not engine.chunks:
        raise HTTPException(status_code=409, detail="No documents indexed. POST /seed_demo or /upload first.")
    return engine.compare(
        question=payload.question,
        strategies=payload.strategies,
        top_k=payload.top_k,
        do_generate=payload.generate,
    )


@app.post("/chat", response_model=ChatResponse, tags=["retrieval"])
def chat(payload: ChatRequest) -> ChatResponse:
    """Single-answer chat. Omit `strategy` and the router picks one, with its reasoning."""
    engine = get_engine()
    if not engine.chunks:
        raise HTTPException(status_code=409, detail="No documents indexed. POST /seed_demo or /upload first.")

    routing = engine.routing_decision(payload.question)
    chosen = payload.strategy or routing.recommended
    result = engine.run_strategy(chosen, payload.question, payload.top_k, do_generate=True)
    return ChatResponse(question=payload.question, routing=routing, result=result)


@app.get("/route", tags=["retrieval"])
def route_only(q: str = Query(..., min_length=3, description="Question to classify")) -> dict:
    """Routing decision without running retrieval. Useful for inspecting the classifier."""
    return get_engine().routing_decision(q).model_dump()


@app.get("/graph", response_model=GraphSnapshot, tags=["retrieval"])
def graph_snapshot(limit: int = Query(120, ge=1, le=500)) -> GraphSnapshot:
    """Graph state. Watch n_components: anything much above 1 means entity resolution
    is leaving islands, and multi-hop traversal will quietly under-retrieve."""
    return get_engine().graph.snapshot(limit=limit)


# --------------------------------------------------------------------------
# Content readiness + response explanation
# --------------------------------------------------------------------------
@app.post("/analyze_readiness", response_model=ReadinessReport, tags=["governance"])
def analyze_readiness(payload: ReadinessRequest) -> ReadinessReport:
    """Score arbitrary pasted content for retrieval readiness, without indexing it.

    Deliberately separate from /upload: the point is to assess a page *before* deciding
    whether it belongs in the corpus, and to tell the author what to fix.
    """
    from app.readiness import analyze

    return analyze(payload.text, payload.title)


@app.post("/explain", response_model=ExplainedResponse, tags=["governance"])
def explain(payload: dict) -> ExplainedResponse:
    """Interpret a /chat or /query_compare response: what is trustworthy, what is not.

    Powers the API playground. A 200 OK with a fluent answer can still be a complete
    failure, and reading that correctly is a learned skill.
    """
    from app.explain import explain_chat, explain_compare

    if "results" in payload:
        return explain_compare(payload)
    if "result" in payload:
        return explain_chat(payload)
    raise HTTPException(
        status_code=422,
        detail="Body must be a /chat response (has 'result') or /query_compare response (has 'results').",
    )


# --------------------------------------------------------------------------
# Multi-agent pipeline
# --------------------------------------------------------------------------
@app.post("/agent_query", response_model=AgentResponse, tags=["agents"])
def agent_query(payload: AgentRequest) -> AgentResponse:
    """Run the LangGraph multi-agent pipeline: plan -> retrieve -> grade -> synthesize -> verify.

    Unlike /chat, a failed context grade re-routes to a different retrieval strategy and
    retries (up to 3 attempts). `strategies_tried` with more than one entry means the
    self-correction loop fired.
    """
    engine = get_engine()
    if not engine.chunks:
        raise HTTPException(status_code=409, detail="No documents indexed. POST /seed_demo or /upload first.")

    from app.agents.pipeline import run_agent

    result = run_agent(
        engine, payload.question, payload.top_k,
        forced_strategy=payload.strategy.value if payload.strategy else None,
    )
    return AgentResponse(**result)


@app.get("/traces", tags=["agents"])
def traces(limit: int = Query(20, ge=1, le=50)) -> dict:
    """Recent agent traces. Always available - no external observability account needed."""
    from app.observability import LANGSMITH_ENABLED, LANGSMITH_PROJECT, tracer

    return {
        "langsmith_enabled": LANGSMITH_ENABLED,
        "langsmith_project": LANGSMITH_PROJECT if LANGSMITH_ENABLED else None,
        "traces": tracer.recent(limit),
    }


@app.get("/traces/{trace_id}", tags=["agents"])
def trace_detail(trace_id: str) -> dict:
    from app.observability import tracer

    found = tracer.get(trace_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Unknown trace id (traces are kept in a 50-entry ring buffer).")
    return found


@app.get("/", tags=["system"])
def root() -> dict:
    return {
        "name": "Enterprise RAG Architecture & Governance Engine",
        "version": VERSION,
        "docs": "/docs",
        "strategies": [s.value for s in Strategy],
        "default_top_k": TOP_K,
        "auth_required": AUTH_ENABLED,
    }
