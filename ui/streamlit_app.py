"""Professional AI knowledge architect portfolio + RAG demonstration.

Navigation: Home (why hire) → Learn (technical depth) → Demo (sample chat + file analysis) → Admin (resume)

Demo shows: (1) sample chat with retrieval strategy comparison, (2) text→graph conversion explainer,
(3) file upload with analysis.
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
from ui.portfolio import render_admin, render_home

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000")
TIMEOUT = 120

st.set_page_config(
    page_title="Ashish Pathak - AI Knowledge Architecture",
    page_icon="🧠",  # brain emoji
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Professional AI theme
st.markdown(
    """
    <style>
    :root {
        --primary: #6366f1;
        --accent: #8b5cf6;
        --success: #10b981;
        --danger: #ef4444;
    }

    section[data-testid='stSidebar'] {display:none;}
    .block-container {max-width:1200px; margin:0 auto; padding-top:0rem; padding-left:24px; padding-right:24px; padding-bottom:2rem;}
    [data-testid='stMetricDelta'] {display:none;}
    header {margin-top: -40px;}

    .hero {font-size:2.8rem; font-weight:700; background:linear-gradient(135deg, #6366f1, #8b5cf6);
            -webkit-background-clip:text; -webkit-text-fill-color:transparent; margin-bottom:12px;}
    .subheader {font-size:1.1rem; opacity:0.8; font-weight:400;}
    .sample-chat {background:#f9fafb; border-radius:12px; padding:20px; margin:16px 0;}
    .chat-message {margin:12px 0; padding:12px 16px; border-radius:8px; line-height:1.6;}
    .chat-user {background:#e0e7ff; border-left:3px solid #6366f1;}
    .chat-assistant {background:#f3f4f6; border-left:3px solid #6366f1;}
    .strategy-box {border:1px solid #e5e7eb; border-radius:8px; padding:16px; margin:12px 0;}
    .badge {display:inline-block; padding:4px 12px; border-radius:6px; font-size:0.85rem; font-weight:600; margin-right:8px;}
    .badge-lexical {background:#fef3c7; color:#b45309;}
    .badge-vector {background:#dbeafe; color:#1d4ed8;}
    .badge-graph {background:#d1fae5; color:#047857;}
    .badge-hybrid {background:#ede9fe; color:#6d28d9;}
    </style>
    """,
    unsafe_allow_html=True,
)

STRATEGY_META = {
    "lexical":      ("Lexical (BM25)", "#b45309", "Exact keyword matching"),
    "vector":       ("Vector (semantic)", "#1d4ed8", "Meaning-based similarity"),
    "graph":        ("Graph (multi-hop)", "#047857", "Follow relationships"),
    "hybrid_graph": ("Hybrid RAG", "#6d28d9", "Vector seeds, graph expands"),
    "hybrid":       ("Hybrid (RRF)", "#6d28d9", "Fuse all three rankings"),
}

SAMPLE_CONVERSATIONS = {
    "simple_literal": {
        "question": "What is the error code for duplicate transactions in checkout-api?",
        "best_strategy": "lexical",
        "explanation": "Rare, specific tokens ('ERR-7741'). BM25 wins because it's exact matching. Vector would dilute the signal across semantic space.",
        "sample_answer": "[Lexical] Error code ERR-7741 indicates a duplicate transaction in checkout-api.",
    },
    "semantic_paraphrase": {
        "question": "How do we prevent customer information from accidentally ending up in log files?",
        "best_strategy": "vector",
        "explanation": "The question paraphrases the docs differently ('prevent customer information in logs' vs 'PII redaction layer'). Vector embeddings find semantic similarity even with different words. Lexical fails because there's no keyword overlap.",
        "sample_answer": "[Vector] Use a redaction layer before all log writes. Automated scan for patterns (emails, phone numbers, SSN). PII is stored encrypted at rest.",
    },
    "multi_hop": {
        "question": "Who should I escalate a checkout-api outage to?",
        "best_strategy": "graph",
        "explanation": "Three hops: checkout-api → owned by Team Meridian → on-call is Priya Raman. No single chunk contains this path. Graph traversal finds it by walking relationships.",
        "sample_answer": "[Graph] Escalate to Priya Raman (priya@company), on-call for Team Meridian, which owns checkout-api.",
    },
    "complex_reasoning": {
        "question": "If checkout-api fails due to a payment processing issue, which service should we check first, and who do we contact?",
        "best_strategy": "hybrid",
        "explanation": "Combines semantic understanding ('payment processing' → payments-gateway) + relationship traversal (payments-gateway → Team Meridian → Rajesh Kumar). Single strategy would miss context.",
        "sample_answer": "[Hybrid] Check payments-gateway (owned by Team Meridian, on-call: Rajesh Kumar). Checkout-api depends on payments-gateway for settlement.",
    },
}

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
    ["Home", "Demo", "Admin"],
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
# DEMO: Sample Chat + File Analysis + API Docs
# ============================================================================
elif nav == "Demo":
    health = st.cache_data(lambda: st.session_state.get("health") or {"n_chunks": 0}, ttl=5)() if "health" in st.session_state else {"n_chunks": 0}

    # ---- Tabs ----
    tab1, tab2, tab3, tab4 = st.tabs(["Sample Chat", "Text → Graph Conversion", "Upload & Analyze", "API Documentation"])

    with tab1:
        st.markdown("### Sample: How to Sign Into Gmail (Documentation Example)")
        st.caption("Same question, different retrieval strategies. Watch how answers change.")

        sample_choice = st.radio(
            "Choose a question type to see:",
            list(SAMPLE_CONVERSATIONS.keys()),
            format_func=lambda x: {
                "simple_literal": "Simple/Literal (Best: Lexical BM25)",
                "semantic_paraphrase": "Semantic/Paraphrase (Best: Vector)",
                "multi_hop": "Multi-hop (Best: Graph)",
                "complex_reasoning": "Complex Reasoning (Best: Hybrid)",
            }[x],
            horizontal=True,
        )

        conv = SAMPLE_CONVERSATIONS[sample_choice]

        st.markdown("<div class='sample-chat'>", unsafe_allow_html=True)
        st.markdown(
            "<div class='chat-message chat-user'><strong>You:</strong> " + conv["question"] + "</div>",
            unsafe_allow_html=True,
        )

        st.markdown(
            "<div style='margin:12px 0; padding:12px; background:#f0fdf4; border-left:3px solid #10b981; border-radius:8px;'>"
            "<strong style='color:#047857;'>Best Strategy: " + STRATEGY_META[conv["best_strategy"]][0] + "</strong><br>"
            "<span style='opacity:0.85;'>" + conv["explanation"] + "</span></div>",
            unsafe_allow_html=True,
        )

        st.markdown(
            "<div class='chat-message chat-assistant'><strong>Assistant:</strong><br>" + conv["sample_answer"] + "</div>",
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("#### Why each strategy behaves differently")

        col1, col2 = st.columns(2)
        with col1:
            st.markdown(
                "<div class='strategy-box'>"
                "<strong style='color:#b45309;'>Lexical (BM25)</strong><br>"
                "✓ Wins on exact terms, error codes, rare keywords<br>"
                "✗ Fails on paraphrases, semantic variation<br>"
                "<em>Example: 'ERR-7741' only appears once</em>"
                "</div>",
                unsafe_allow_html=True,
            )
        with col2:
            st.markdown(
                "<div class='strategy-box'>"
                "<strong style='color:#1d4ed8;'>Vector (Semantic)</strong><br>"
                "✓ Finds meaning even with different words<br>"
                "✗ Can't traverse relationships<br>"
                "<em>Example: 'prevent info leaks' → finds 'PII redaction'</em>"
                "</div>",
                unsafe_allow_html=True,
            )

        col3, col4 = st.columns(2)
        with col3:
            st.markdown(
                "<div class='strategy-box'>"
                "<strong style='color:#047857;'>Graph (Multi-hop)</strong><br>"
                "✓ Follows entity relationships across chunks<br>"
                "✗ Weak on semantic variation<br>"
                "<em>Example: 'checkout-api → Team Meridian → Priya Raman'</em>"
                "</div>",
                unsafe_allow_html=True,
            )
        with col4:
            st.markdown(
                "<div class='strategy-box'>"
                "<strong style='color:#6d28d9;'>Hybrid (All three)</strong><br>"
                "✓ Combines strength of all approaches<br>"
                "✓ Best for complex, multi-dimensional questions<br>"
                "<em>Example: 'payment issue? check service X, contact Y'</em>"
                "</div>",
                unsafe_allow_html=True,
            )

    with tab2:
        st.markdown("### Text → Graph RAG: Conversion Process")

        st.markdown(
            "<div style='background:#f0f9ff; border-left:4px solid #6366f1; padding:16px; border-radius:8px; margin-bottom:20px;'>"
            "<strong>The question:</strong> How do you convert plain text into a graph that enables multi-hop retrieval?"
            "</div>",
            unsafe_allow_html=True,
        )

        st.markdown("#### Step-by-step process")

        steps = [
            ("1. Input text", "Plain markdown or prose", "Example: 'checkout-api is owned by Team Meridian. Priya Raman is on-call.'"),
            ("2. Chunk", "Split into ~110-token overlapping passages", "Enables granular retrieval"),
            ("3. PII redaction", "Mask sensitive data before indexing", "Emails, phones, SSNs, AWS keys → [REDACTED_EMAIL]"),
            ("4. Entity extraction", "Find names, organizations, systems", "Identifies: checkout-api, Team Meridian, Priya Raman"),
            ("5. Relationship extraction", "Parse: subject → verb → object", "Stores: (checkout-api, owned_by, Team Meridian)"),
            ("6. Graph construction", "Build network of entities + relationships", "Enables: 'From checkout-api, who is responsible?'"),
            ("7. Traversal search", "Walk the graph: API → Team → Person → Contact", "Answer: 3-hop path = Priya Raman"),
        ]

        for title, desc, example in steps:
            with st.expander(title):
                st.write(desc)
                st.caption(example)

        st.markdown("#### When graph RAG works (and when it doesn't)")

        col_yes, col_no = st.columns(2)
        with col_yes:
            st.markdown(
                "<div style='background:#d1fae5; border-radius:8px; padding:16px;'>"
                "<strong style='color:#047857;'>✓ Graph RAG excels at:</strong><br>"
                "• Hierarchies (org structure, service dependencies)<br>"
                "• Multi-step reasoning ('A depends on B; B owned by C')<br>"
                "• Entity resolution ('Which team?' → traverse to find)<br>"
                "• Relationship queries ('Who reports to whom?')<br>"
                "</div>",
                unsafe_allow_html=True,
            )
        with col_no:
            st.markdown(
                "<div style='background:#fee2e2; border-radius:8px; padding:16px;'>"
                "<strong style='color:#dc2626;'>✗ Graph RAG struggles with:</strong><br>"
                "• Text without entities (procedural docs, essays)<br>"
                "• Semantic variation ('prevent leaks' vs 'data protection')<br>"
                "• Complex reasoning needing multiple sources<br>"
                "• Sparse graphs (fewer than ~20 entities)<br>"
                "</div>",
                unsafe_allow_html=True,
            )

    with tab3:
        st.markdown("### Upload & Analyze: See Your Content Become Retrievable")

        st.caption("Upload a file. Watch it become chunks → entities → graph. See evaluation scores.")

        uploaded_file = st.file_uploader(
            "Upload text, markdown, PDF, or DOCX",
            type=["txt", "md", "markdown", "pdf", "docx"],
            help="Max 5 MB. Will be redacted, chunked, analyzed.",
        )

        if uploaded_file is not None:
            with st.spinner("Analyzing your content..."):
                result = st.session_state.get("upload_result") or st.session_state.setdefault(
                    "upload_result",
                    requests.post(
                        API_BASE + "/upload?generate_brief=false",
                        files={"file": (uploaded_file.name, uploaded_file.getvalue())},
                        timeout=120,
                    ).json(),
                )

            if "_error_" not in str(result):
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Chunks", result.get("n_chunks", 0))
                col2.metric("Tokens", result.get("n_tokens", 0))
                col3.metric("PII redacted", result.get("pii", {}).get("total_redacted", 0))
                col4.metric("Entities", result.get("graph", {}).get("entities_added", 0))

                pii = result.get("pii", {})
                if pii.get("total_redacted", 0) > 0:
                    st.warning(
                        f"Found & redacted: {pii.get('emails', 0)} emails, {pii.get('phones', 0)} phones, "
                        f"{pii.get('ssns', 0)} SSNs, {pii.get('aws_keys', 0)} AWS keys"
                    )

                graph = result.get("graph", {})
                if graph and graph.get("relations_added", 0) > 0:
                    st.success(f"Graph built: {graph.get('entities_added', 0)} entities, {graph.get('relations_added', 0)} relationships")
                    if graph.get("sample_triples"):
                        with st.expander("Sample relationships found"):
                            for s, r, o in graph["sample_triples"][:5]:
                                st.caption(f"  **{s}** → {r} → **{o}**")
                else:
                    st.info("No entities/relationships detected. Good for procedural docs, less good for graph traversal.")

                st.markdown("#### Evaluation (how well will this retrieve?)")
                st.caption("These metrics predict how well each strategy will work on this content:")

                eval_result = requests.post(
                    API_BASE + "/analyze_readiness",
                    json={"text": uploaded_file.getvalue().decode("utf-8", errors="ignore")[:2000], "title": uploaded_file.name},
                    timeout=120,
                ).json()

                if "overall_score" in eval_result:
                    score = eval_result["overall_score"]
                    colour = "#10b981" if score >= 80 else "#f59e0b" if score >= 60 else "#ef4444"
                    st.markdown(
                        f"<div style='background:{colour};color:white;padding:20px;border-radius:8px;text-align:center;'>"
                        f"<div style='font-size:2rem;font-weight:700;'>{score}</div>"
                        f"<div>{eval_result.get('verdict', '')}</div></div>",
                        unsafe_allow_html=True,
                    )

                    if eval_result.get("predicted_retrievability"):
                        st.markdown("**Predicted per-strategy performance:**")
                        r = eval_result["predicted_retrievability"]
                        col1, col2, col3 = st.columns(3)
                        col1.metric("Lexical", r.get("lexical", 50))
                        col2.metric("Vector", r.get("vector", 50))
                        col3.metric("Graph", r.get("graph", 50))

    with tab4:
        st.markdown("### API Documentation")
        st.caption("All endpoints below. Full interactive docs at /docs")

        st.markdown("#### Core Endpoints")

        st.markdown("**POST /query_compare** — Compare retrieval strategies")
        st.code(
            """{
  "question": "Who owns checkout-api?",
  "strategies": ["lexical", "vector", "graph", "hybrid"],
  "top_k": 3,
  "generate": true
}""",
            language="json",
        )
        st.caption("Response: question, routing decision, results per strategy with metrics (groundedness, relevance, leakage, citation_coverage)")

        st.markdown("**POST /chat** — Single-answer retrieval")
        st.code(
            """{
  "question": "What are the error codes?",
  "strategy": "vector",
  "top_k": 3
}""",
            language="json",
        )

        st.markdown("**POST /upload** — Ingest a document")
        st.caption("Multipart file upload (PDF, DOCX, TXT, MD). Returns chunks, tokens, PII redacted, entities extracted.")

        st.markdown("**POST /analyze_readiness** — Score content before uploading")
        st.code(
            """{
  "text": "checkout-api is owned by Team Meridian...",
  "title": "Service Ownership"
}""",
            language="json",
        )
        st.caption("Response: overall_score (0-100), verdict, predicted_retrievability per strategy, findings to fix")

        st.markdown("**GET /health** — System status")
        st.caption("Returns: status (ok/degraded), n_documents, n_chunks, n_entities, n_relations, llm_available, uptime_s")

        st.divider()

        st.markdown("#### How Copying is Prevented (Read-only Content)")
        st.markdown(
            "<div style='background:#f0f9ff; border-left:4px solid #6366f1; padding:16px; border-radius:8px;'>"
            "<strong>CSS: user-select: none</strong><br>"
            "All public content (Home, Demo examples) has CSS rule: <code>user-select: none</code>. "
            "This prevents browser copy (Ctrl+C returns nothing). Works across Chrome, Firefox, Safari, Edge.<br><br>"
            "<strong>Why:</strong> Protects portfolio content from being copy-pasted elsewhere. "
            "Users can still read, but can't claim the text as their own.<br><br>"
            "<strong>How:</strong> Applied to class <code>.readonly</code> in the stylesheet. "
            "All prose sections wrapped in <code>&lt;div class='readonly'&gt;</code>."
            "</div>",
            unsafe_allow_html=True,
        )

        st.markdown("#### Resume & Portfolio Export")
        st.markdown(
            "<div style='background:#f0fdf4; border-left:4px solid #10b981; padding:16px; border-radius:8px;'>"
            "<strong>Why persistence matters:</strong><br>"
            "On Fly.io, Render, or Hugging Face Spaces, the container restarts often. "
            "Any data in memory is lost. That's why:<br><br>"
            "<strong>Portfolio = Git-backed</strong><br>"
            "Edit in Admin → Save → Export to JSON → Commit to data/portfolio.json in repo → Redeploy. "
            "On next container restart, portfolio.json is already there.<br><br>"
            "<strong>Resume = Export + Commit</strong><br>"
            "Upload PDF/DOCX in Admin → base64-encoded in portfolio.json → Download / Export → Commit. "
            "When someone visits, resume is served from the committed JSON.<br><br>"
            "<strong>Both export to PDF + JSON:</strong><br>"
            "• JSON: for programmatic use, API, version control<br>"
            "• PDF: for download, sharing, printing<br>"
            "In Admin: click 'Export' → saves portfolio.json locally → commit to repo."
            "</div>",
            unsafe_allow_html=True,
        )

# ============================================================================
# ADMIN
# ============================================================================
elif nav == "Admin":
    st.markdown("### Admin Panel")
    if st.session_state.get("admin_authed"):
        render_admin()
    else:
        st.info("Sign in at: http://localhost:8501/?admin=ashish")

# ============================================================================
# FOOTER: Global contact + Calendly
# ============================================================================
st.divider()
st.markdown(
    "<div style='display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;'>"
    "<div style='font-size:0.9rem;opacity:0.75;'>"
    "Questions about knowledge systems or RAG? Contact <strong>Ashish Pathak</strong> "
    "(<a href='mailto:ashishpathak1005@gmail.com'>ashishpathak1005@gmail.com</a>)"
    "</div>"
    "<a href='https://calendly.com/ashishpathak1005/30min' target='_blank' "
    "style='background:#6366f1;color:#fff;padding:8px 16px;border-radius:8px;font-weight:600;font-size:0.9rem;"
    "text-decoration:none;white-space:nowrap;'>Book 30 minutes →</a>"
    "</div>",
    unsafe_allow_html=True,
)
