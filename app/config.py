"""Central configuration. Everything tunable lives here, nothing is hardcoded downstream."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CORPUS_DIR = DATA_DIR / "demo_corpus"
BRIEF_DIR = DATA_DIR / "briefs"

# --- LLM -------------------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
LLM_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "45"))

# Groq public pricing for llama-3.3-70b-versatile, USD per 1M tokens.
COST_PER_1M_INPUT = float(os.getenv("COST_PER_1M_INPUT", "0.59"))
COST_PER_1M_OUTPUT = float(os.getenv("COST_PER_1M_OUTPUT", "0.79"))

# --- Retrieval -------------------------------------------------------------
TOP_K = int(os.getenv("TOP_K", "3"))
CHUNK_TOKENS = int(os.getenv("CHUNK_TOKENS", "110"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "25"))
GRAPH_MAX_HOPS = int(os.getenv("GRAPH_MAX_HOPS", "3"))
RRF_K = 60  # standard Reciprocal Rank Fusion damping constant

# --- Embeddings ------------------------------------------------------------
# fastembed (ONNX, no torch) keeps the container ~400MB instead of ~2.5GB.
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
ALLOW_EMBED_DOWNLOAD = os.getenv("ALLOW_EMBED_DOWNLOAD", "1") == "1"

# Memory knobs, not speed knobs. onnxruntime allocates a memory arena per thread;
# measured peak RSS on a bulk encode was 470MB at default threads vs 189MB at 1.
# Batching bounds the transient activation buffers. Both matter far more than
# throughput on a small shared-CPU VM.
EMBED_THREADS = int(os.getenv("EMBED_THREADS", "1"))
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "8"))

# --- Governance ------------------------------------------------------------
PII_ENABLED = os.getenv("PII_ENABLED", "1") == "1"

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000")

# --- Pluggable backends ----------------------------------------------------
# Both default to the in-process implementations so the app runs with zero
# infrastructure. Flip either one to exercise the real database.
GRAPH_BACKEND = os.getenv("GRAPH_BACKEND", "networkx")   # networkx | neo4j
VECTOR_BACKEND = os.getenv("VECTOR_BACKEND", "numpy")    # numpy | chroma

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "helios-dev-password")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

CHROMA_PATH = DATA_DIR / "chroma"
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "helios_chunks")

# --- Author / branding -----------------------------------------------------
# Set these in .env so the deployed app links back to you. Empty values simply
# hide the link rather than rendering a dead one.
AUTHOR_NAME = os.getenv("AUTHOR_NAME", "Ashish Pathak")
AUTHOR_TAGLINE = os.getenv(
    "AUTHOR_TAGLINE",
    "Documentation, Knowledge Management & Content Engineering",
)
PORTFOLIO_URL = os.getenv("PORTFOLIO_URL", "")
CALENDLY_URL = os.getenv("CALENDLY_URL", "")
LINKEDIN_URL = os.getenv("LINKEDIN_URL", "")
GITHUB_URL = os.getenv("GITHUB_URL", "")
