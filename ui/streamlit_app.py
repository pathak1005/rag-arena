"""Professional portfolio + RAG demonstration.

Navigation: Home (why hire) → Learn (technical depth) → Demo (editable, with observability sidebar) → Admin (portfolio management)

Demo has editable Petstore-style sample data. Change it, reload, compare retrieval. Sidebar shows real governance
parameters and evaluation metrics per strategy.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
import streamlit as st

from app import adminstore
from ui.portfolio import contact_banner, render_admin, render_home, render_learn

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000")
TIMEOUT = 120
MAX_EVAL_WORDS = 500

st.set_page_config(
    page_title="Ashish Pathak - Knowledge Architecture",
    page_icon="\U0001F50D",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    "<style>"
    "section[data-testid='stSidebar'] {display:none;}"
    ".block-container {max-width:1200px; margin:0 auto; padding-top:2rem; padding-left:20px; padding-right:20px;}"
    "[data-testid='stMetricDelta'] {display:none;}"
    "</style>",
    unsafe_allow_html=True,
)

STRATEGY_META = {
    "lexical":      ("Lexical (BM25)", "#b45309"),
    "vector":       ("Vector (semantic)", "#1d4ed8"),
    "graph":        ("Graph (multi-hop)", "#047857"),
    "hybrid_graph": ("Hybrid RAG", "#6d28d9"),
    "hybrid":       ("Hybrid (RRF)", "#6d28d9"),
}

SAMPLE_DATA = {
    "service_ownership": """# Service Ownership

## checkout-api
- **Owner**: Team Meridian
- **On-call**: Priya Raman (priya@company)
- **Purpose**: Processes payment transactions
- **Dependencies**: payments-gateway (settlement), ledger-service (audit log)
- **Error codes**: ERR-7741 (duplicate transaction), ERR-7742 (insufficient funds), ERR-7743 (network timeout)

## payments-gateway
- **Owner**: Team Meridian
- **On-call**: Rajesh Kumar (rajesh@company)
- **Purpose**: Handles fund transfers to partner banks
- **Dependencies**: compliance-check (regulatory), settlement-queue (async)

## ledger-service
- **Owner**: Team Genesis
- **On-call**: Sarah Chen (sarah@company)
- **Purpose**: Immutable transaction log
- **Dependencies**: encryption-service (PII protection)

## subscription-api
- **Owner**: Team Helix
- **On-call**: Marcus Johnson (marcus@company)
- **Purpose**: Manages recurring billing
- **Integrates with**: subscription-db, notification-service
""",
    "data_security": """# Data Protection & Incident Response

## Customer Data Classification

**PII (Personally Identifiable)**: Names, emails, phone numbers, addresses, payment methods
- **Storage**: Encrypted at rest (AES-256)
- **Transit**: TLS 1.3 only
- **Access**: Requires audit log entry

**Sensitive**: Error logs, debugging data
- **Risk**: Customer data leaking into logs if not redacted
- **Prevention**: Redaction layer before all log writes
- **Detection**: Automated scan for patterns (emails, phone numbers, SSN)

## Escalation on Security Incidents

1. **Level 1 (Data leak suspected)**: On-call security engineer (on-call-security@company) + Team lead
2. **Level 2 (Confirmed breach)**: CISO + Legal + Customer Communications
3. **Level 3 (Third party affected)**: Notify affected parties within 72h per GDPR

""",
    "documentation": """# Documentation Standards

## Why it matters
- Bad docs = users email you instead of checking wiki
- Retrievable docs = fewer questions, faster onboarding

## Writing for retrieval

1. **Name the subject explicitly**. Don't write "it depends on X". Write "checkout-api depends on payments-gateway for settlement."
2. **One fact per sentence**. Chunking splits at sentence breaks. If you bury two facts in one sentence, retrieval misses one.
3. **Use jargon consistently**. "checkout-api", "checkout API", "checkout system" all in one doc confuses embeddings.
4. **Link across services**. "See payments-gateway for settlement logic." Enables multi-hop traversal.
""",
}


# ============================================================================
# API helpers
# ============================================================================
def api_get(path: str, **params):
    try:
        r = requests.get(API_BASE + path, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        return {"__error__": "Backend unreachable"}
    except requests.exceptions.HTTPError as exc:
        try:
            detail = exc.response.json().get("detail", "")
        except Exception:  # noqa: BLE001
            detail = "Request failed."
        return {"__error__": detail}
    except Exception:  # noqa: BLE001
        return {"__error__": "Error"}


def api_post(path: str, payload: dict | None = None, files=None):
    try:
        r = requests.post(API_BASE + path, json=payload, files=files, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        return {"__error__": "Backend unreachable"}
    except requests.exceptions.HTTPError as exc:
        try:
            detail = exc.response.json().get("detail", "")
        except Exception:  # noqa: BLE001
            detail = "Request failed."
        return {"__error__": detail}
    except Exception:  # noqa: BLE001
        return {"__error__": "Error"}


def err(payload) -> str | None:
    return payload.get("__error__") if isinstance(payload, dict) else None


def strategy_badge(name: str) -> str:
    label, colour = STRATEGY_META.get(name, (name, "#475569"))
    return (
        "<span style='background:" + colour + ";color:#fff;padding:3px 10px;"
        "border-radius:8px;font-size:0.78rem;font-weight:600;'>" + label + "</span>"
    )


# ============================================================================
# Admin gate
# ============================================================================
if st.query_params.get("admin") == adminstore.ADMIN_SLUG:
    render_admin()
    st.stop()


content = adminstore.load_content()

# ============================================================================
# Navigation
# ============================================================================
if "nav" not in st.session_state:
    st.session_state["nav"] = "Home"

nav = st.segmented_control(
    "Navigate",
    ["Home", "Learn", "Demo", "Admin"],
    default=st.session_state["nav"],
    label_visibility="collapsed",
)
if nav is None:
    nav = st.session_state["nav"]
st.session_state["nav"] = nav

st.write("")


# ============================================================================
# HOME
# ============================================================================
if nav == "Home":
    render_home(content)


# ============================================================================
# LEARN
# ============================================================================
elif nav == "Learn":
    render_learn()


# ============================================================================
# DEMO: RAG Simulator with Editable Sample Data
# ============================================================================
elif nav == "Demo":
    contact_banner(content, "demo_top")

    health = api_get("/health")
    backend_down = bool(err(health))
    if backend_down:
        st.error("Backend is down.")
        st.stop()

    n_chunks = health.get("n_chunks", 0)

    # ---- Analyze Before Loading: File inspection ----
    st.markdown("### 0. Analyze Your Content (Before Loading)")
    st.caption("Upload a file to see: PII found, chunks created, entities extracted, retrieval fitness score.")

    uploaded_file = st.file_uploader("Upload text/markdown/PDF", type=["txt", "md", "markdown", "pdf", "docx"])
    if uploaded_file is not None:
        with st.spinner("Analyzing..."):
            result = api_post("/upload?generate_brief=false", files={"file": (uploaded_file.name, uploaded_file.getvalue())})

        if not err(result):
            st.success(f"✓ Loaded {result.get('n_chunks', 0)} chunks from {uploaded_file.name}")

            col1, col2, col3 = st.columns(3)
            col1.metric("Chunks", result.get("n_chunks", 0))
            col2.metric("Tokens", result.get("n_tokens", 0))
            col3.metric("PII redacted", result.get("pii", {}).get("total_redacted", 0))

            pii = result.get("pii", {})
            if pii.get("total_redacted", 0) > 0:
                st.warning(
                    f"PII redacted: {pii.get('emails', 0)} emails, {pii.get('phones', 0)} phones, "
                    f"{pii.get('ssns', 0)} SSNs, {pii.get('aws_keys', 0)} AWS keys"
                )

            graph = result.get("graph", {})
            if graph:
                st.markdown("**Entities & Relationships**")
                c1, c2 = st.columns(2)
                c1.metric("Entities", graph.get("entities_added", 0))
                c2.metric("Relations", graph.get("relations_added", 0))
                if graph.get("sample_triples"):
                    st.caption("Sample relationships:")
                    for s, r, o in graph["sample_triples"][:3]:
                        st.caption(f"  {s} → {r} → {o}")

            # Now offer to load it
            if st.button("Load this file into workspace", type="primary"):
                st.rerun()
        else:
            st.error(err(result))

    st.divider()

    # ---- Sidebar: Governance, Evaluation, Observability ----
    with st.sidebar:
        st.markdown("### Governance & Observability")

        st.markdown("**Generation Parameters**")
        temp = st.slider("Temperature", 0.0, 1.0, 0.0, 0.1, help="0=deterministic, 1=creative (more hallucination risk)")
        top_p = st.slider("Top-p (nucleus)", 0.5, 1.0, 1.0, 0.05)
        max_tokens = st.slider("Max tokens", 50, 500, 300, 50)

        st.markdown("**Retrieval Thresholds**")
        recall_target = st.slider("Recall target", 1, 10, 3, help="How many relevant passages to find")
        latency_slo = st.slider("Latency SLO (ms)", 100, 5000, 2000, 200)

        st.markdown("**Safety**")
        poisoning_guard = st.slider("Injection detection", 0.0, 1.0, 0.7, 0.05, help="0=permissive, 1=strict")
        hallucination_threshold = st.slider("Hallucination threshold", 0.0, 1.0, 0.7, 0.05, help="Min groundedness to accept")

        st.divider()

        if n_chunks > 0:
            st.markdown("**Last Query Metrics**")
            if "last_result" in st.session_state:
                r = st.session_state["last_result"]
                if r.get("results"):
                    best = r["results"][0]
                    m = best.get("metrics", {})
                    st.metric("Groundedness", format(m.get("groundedness", 0.0), ".2f"))
                    st.metric("Context relevance", format(m.get("context_relevance", 0.0), ".2f"))
                    st.metric("Entity leakage", format(m.get("entity_leakage", 0.0), ".2f"))
                    st.metric("Citation coverage", format(m.get("citation_coverage", 0.0), ".2f"))
                    st.metric("Latency", str(best.get("latency_ms", "?")) + " ms")
        st.markdown("(Run a query to populate)")

    # ---- Main: Editable Sample Data ----
    st.markdown("### 1. Editable Sample Content")
    st.caption("Modify the text below and press 'Load'. Watch how retrieval changes. This is how writers should test before publishing.")

    doc_type = st.selectbox(
        "Sample dataset",
        list(SAMPLE_DATA.keys()),
        format_func=lambda x: x.replace("_", " ").title(),
    )

    content_text = st.text_area(
        "Edit and load:",
        value=SAMPLE_DATA[doc_type],
        height=250,
        key="sample_content",
    )

    if st.button("Load this content", type="primary"):
        with st.spinner("Chunking, embedding, extracting relationships..."):
            result = api_post("/reset") and api_post(
                "/ingest_text",
                {"title": doc_type.replace("_", " ").title(), "text": content_text, "generate_brief": False},
            )
        if err(result):
            st.error(err(result))
        else:
            st.success(f"Loaded {result.get('n_chunks', 0)} chunks")
            st.rerun()

    if n_chunks == 0:
        st.info("Load sample content above to continue.")
        st.stop()

    st.divider()

    # ---- Query Interface ----
    st.markdown("### 2. Compare Retrieval Strategies")

    question = st.text_input("Ask a question about the content above")
    include_hybrid = st.checkbox("Also include Hybrid strategies")
    top_k = st.slider("Chunks per strategy", 1, 6, 3)

    if st.button("Compare strategies", type="primary", disabled=not question.strip()):
        strategies = ["lexical", "vector", "graph"]
        if include_hybrid:
            strategies.extend(["hybrid_graph", "hybrid"])

        with st.spinner("Routing, retrieving, generating..."):
            result = api_post(
                "/query_compare",
                {"question": question, "strategies": strategies, "top_k": top_k, "generate": True},
            )
        st.session_state["last_result"] = None if err(result) else result
        if err(result):
            st.error(err(result))

    result = st.session_state.get("last_result")
    if result:
        routing = result.get("routing", {})
        st.markdown("#### Routing decision")
        st.caption(
            "The router recommended **" + STRATEGY_META.get(routing.get("recommended", ""), ("unknown",))[0] + "** — "
            + routing.get("rationale", "")
        )

        if result.get("winner"):
            st.success(
                "**Best result:** " + STRATEGY_META.get(result["winner"], (result["winner"],))[0]
                + " — " + result.get("winner_reason", "")
            )

        # ---- Results side-by-side ----
        st.markdown("#### Results")
        cols = st.columns(len(result.get("results", [])))
        for col, r in zip(cols, result.get("results", [])):
            with col:
                st.markdown(strategy_badge(r["strategy"]), unsafe_allow_html=True)
                if r.get("answer"):
                    st.markdown(r["answer"])
                else:
                    st.caption("No answer retrieved.")
                m = r.get("metrics", {})
                st.metric("Grounded", format(m.get("groundedness", 0.0), ".2f"))
                st.metric("Relevance", format(m.get("context_relevance", 0.0), ".2f"))
                st.metric("Leakage", format(m.get("entity_leakage", 0.0), ".2f"))
                if r.get("sources"):
                    with st.expander("Sources (" + str(len(r["sources"])) + ")"):
                        for s in r["sources"]:
                            st.caption("[" + str(s.get("rank", "?")) + "] " + s.get("doc_title", ""))
                            st.markdown(s.get("text", "")[:200] + ("..." if len(s.get("text", "")) > 200 else ""))


# ============================================================================
# ADMIN
# ============================================================================
elif nav == "Admin":
    st.markdown("### Admin")
    if st.session_state.get("admin_authed"):
        render_admin()
    else:
        if st.query_params.get("admin") != adminstore.ADMIN_SLUG:
            st.caption("Admin area restricted. Use the hidden URL to access.")
            st.stop()
