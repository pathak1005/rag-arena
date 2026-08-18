# syntax=docker/dockerfile:1.7
#
# Multi-stage build tuned for small-memory VMs.
#
# Measured peak RSS of the API process (51-chunk corpus, one agent run):
#   fastembed, default threads/batch ......... 470 MB
#   fastembed, EMBED_THREADS=1 BATCH=8 ....... 288 MB   <- default here
#   TF-IDF fallback (ALLOW_EMBED_DOWNLOAD=0) ..  93 MB   <- fits 256 MB
#
# Streamlit adds a further ~130-200 MB, so API+UI in one 256 MB machine is not
# achievable. See deploy/ for the two-app split.

ARG PYTHON_VERSION=3.12

# ---------------------------------------------------------------- builder
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .

# LEAN=1 drops chromadb + neo4j drivers. They are lazily imported and the app falls
# back cleanly, so a deployment using the in-process backends does not need them.
# Saves roughly 90 MB of image and a chunk of import-time RSS.
ARG LEAN=0
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && if [ "$LEAN" = "1" ]; then \
         grep -viE '^(chromadb|neo4j)' requirements.txt > lean.txt && \
         /opt/venv/bin/pip install -r lean.txt ; \
       else \
         /opt/venv/bin/pip install -r requirements.txt ; \
       fi

# Strip test suites, headers and caches out of site-packages - none are used at runtime.
RUN find /opt/venv -type d -name "__pycache__"  -prune -exec rm -rf {} + \
    && find /opt/venv -type d -name "tests"     -prune -exec rm -rf {} + \
    && find /opt/venv -type d -name "test"      -prune -exec rm -rf {} + \
    && find /opt/venv -type d -name "*.dist-info" -exec rm -rf {}/RECORD \; 2>/dev/null || true \
    && find /opt/venv -name "*.pyc" -delete \
    && rm -rf /opt/venv/include /opt/venv/share

# ---------------------------------------------------------------- runtime
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    HF_HOME=/app/.cache \
    FASTEMBED_CACHE_PATH=/app/.cache/fastembed \
    HF_HUB_DISABLE_TELEMETRY=1 \
    # Memory guards. onnxruntime allocates a per-thread arena; capping the thread
    # count is worth ~180 MB of peak RSS on this workload.
    EMBED_THREADS=1 \
    EMBED_BATCH_SIZE=8 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    # Return freed pages to the OS instead of holding them in the malloc arena.
    MALLOC_TRIM_THRESHOLD_=100000 \
    MALLOC_ARENA_MAX=2

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser ui/ ./ui/
COPY --chown=appuser:appuser data/demo_corpus/ ./data/demo_corpus/
COPY --chown=appuser:appuser start.sh ./start.sh

RUN chmod +x start.sh \
    && mkdir -p /app/.cache /app/data/briefs /app/data/chroma \
    && chown -R appuser:appuser /app

USER appuser

# Bake the embedding model in. Without this every cold start pays a ~130 MB download,
# which on Fly presents as a broken deploy rather than a slow one.
ARG PREFETCH_MODEL=1
RUN if [ "$PREFETCH_MODEL" = "1" ]; then \
      python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5', threads=1)" \
      || echo "WARN: model prefetch failed; will download at runtime"; \
    fi

EXPOSE 8000 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD curl -fsS http://127.0.0.1:${API_PORT:-8000}/health || exit 1

CMD ["./start.sh"]
