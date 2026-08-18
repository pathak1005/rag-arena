# Multi-stage. Stage 1 builds wheels, stage 2 ships only the runtime.
# The single biggest size lever is fastembed (ONNX) instead of sentence-transformers
# (torch): ~400MB final image instead of ~2.5GB.

FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    HF_HOME=/app/.cache \
    FASTEMBED_CACHE_PATH=/app/.cache/fastembed

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser ui/ ./ui/
COPY --chown=appuser:appuser data/demo_corpus/ ./data/demo_corpus/
COPY --chown=appuser:appuser start.sh ./start.sh
RUN chmod +x start.sh && mkdir -p /app/.cache /app/data/briefs /app/data/chroma \
    && chown -R appuser:appuser /app

USER appuser

# Bake the embedding model into the image. Without this the first request after every
# cold start pays a ~130MB download, which on Fly reads as a broken deploy.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5')" || \
    echo "WARN: model prefetch failed; will download at runtime"

EXPOSE 8000 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["./start.sh"]
