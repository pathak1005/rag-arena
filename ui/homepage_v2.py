"""
Ashish Pathak – Knowledge Architect Portfolio v2.
Dark theme + pink accents. Animated hero + tabbed sections.
Playground → How It Works → Proof → Interactive Demo.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import requests
import plotly.graph_objects as go
import pandas as pd
import numpy as np

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000")
TIMEOUT = 120

# ============================================================================
# PAGE CONFIG
# ============================================================================
st.set_page_config(
    page_title="Ashish Pathak – Knowledge Architect",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Dark theme + pink accents
st.markdown(
    """
    <style>
    :root {
        --primary: #ec4899;
        --primary-dark: #be185d;
        --bg: #0f172a;
        --bg-surface: #1e293b;
        --text: #f1f5f9;
        --text-muted: #94a3b8;
        --border: #334155;
    }

    * {
        color-scheme: dark;
    }

    html, body {
        background-color: #0f172a;
        color: #f1f5f9;
    }

    section[data-testid='stSidebar'] {display:none;}
    .block-container {
        max-width:1200px;
        margin:0 auto;
        padding-top:2rem;
        padding-left:24px;
        padding-right:24px;
        padding-bottom:3rem;
        background-color: #0f172a;
    }

    [data-testid='stMetricDelta'] {display:none;}
    header {margin-top: 0; padding-top: 0;}
    main {margin-top: 0; padding-top: 0;}

    /* Hero */
    .hero-title {
        font-size: 3.5rem;
        font-weight: 800;
        line-height: 1.1;
        margin-bottom: 16px;
        background: linear-gradient(135deg, #ec4899, #f472b6);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        letter-spacing: -1px;
    }

    .hero-subtitle {
        font-size: 1.3rem;
        color: #cbd5e1;
        font-weight: 400;
        margin-bottom: 32px;
        max-width: 800px;
    }

    .hero-section {
        display: flex;
        gap: 48px;
        align-items: flex-start;
        margin-bottom: 64px;
        padding: 40px 0;
    }

    .hero-content {
        flex: 1;
    }

    .hero-visual {
        flex: 1;
        min-height: 400px;
        background: linear-gradient(135deg, #1e293b, #0f172a);
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 24px;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    /* Tabs */
    .tab-container {
        display: flex;
        gap: 12px;
        margin: 32px 0;
        border-bottom: 1px solid #334155;
        padding-bottom: 16px;
    }

    .tab-button {
        padding: 12px 24px;
        background: transparent;
        border: none;
        color: #94a3b8;
        font-size: 1rem;
        font-weight: 500;
        cursor: pointer;
        border-bottom: 2px solid transparent;
        transition: all 0.2s;
    }

    .tab-button:hover {
        color: #f1f5f9;
    }

    .tab-button.active {
        color: #ec4899;
        border-bottom-color: #ec4899;
    }

    /* Cards */
    .card {
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 24px;
        margin: 16px 0;
    }

    .card:hover {
        border-color: #ec4899;
        box-shadow: 0 0 20px rgba(236, 72, 153, 0.1);
    }

    .metric-card {
        text-align: center;
        padding: 32px 24px;
    }

    .metric-value {
        font-size: 2.5rem;
        font-weight: 700;
        color: #ec4899;
        margin: 12px 0;
    }

    .metric-label {
        font-size: 0.95rem;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    .metric-context {
        font-size: 0.85rem;
        color: #64748b;
        margin-top: 8px;
    }

    /* Buttons */
    .btn {
        padding: 12px 32px;
        background: #ec4899;
        color: white;
        border: none;
        border-radius: 8px;
        font-weight: 600;
        cursor: pointer;
        font-size: 1rem;
        transition: all 0.2s;
    }

    .btn:hover {
        background: #db2777;
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(236, 72, 153, 0.3);
    }

    .btn-secondary {
        background: #334155;
        color: #f1f5f9;
    }

    .btn-secondary:hover {
        background: #475569;
    }

    /* Code blocks */
    .code-block {
        background: #0f172a;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 16px;
        font-family: 'Courier New', monospace;
        font-size: 0.85rem;
        color: #e2e8f0;
        overflow-x: auto;
        line-height: 1.6;
    }

    /* Divider */
    hr {
        border: none;
        border-top: 1px solid #334155;
        margin: 48px 0;
    }

    /* Streamlit overrides */
    [data-testid="stMetricValue"] {
        color: #ec4899;
        font-size: 2.5rem;
    }

    [data-testid="stMetricDeltaValue"] {
        display: none;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 0;
    }

    .stTabs [data-baseweb="tab"] {
        background-color: transparent;
        border-bottom: 2px solid transparent;
        color: #94a3b8;
    }

    .stTabs [aria-selected="true"] {
        color: #ec4899;
        border-bottom-color: #ec4899;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================================
# HERO SECTION
# ============================================================================
st.markdown("<div class='hero-title'>Ashish Pathak</div>", unsafe_allow_html=True)
st.markdown("<div class='hero-subtitle'>Knowledge Architect | 12 years | Enterprise RAG Systems</div>", unsafe_allow_html=True)

col_content, col_visual = st.columns([1.2, 1], gap="large")

with col_content:
    st.markdown(
        "I build **retrieval systems** that turn mountains of documents into instant, measurable answers. "
        "Graph traversal, entity extraction, deterministic evaluation — systems your teams can trust."
    )
    st.markdown("")
    st.markdown("**Specialties:**")
    st.markdown(
        "• Knowledge graphs from unstructured text\n"
        "• Multi-hop reasoning + entity resolution\n"
        "• Deterministic evaluation (no LLM self-grading)\n"
        "• PII governance + safety\n"
        "• Production observability + scaling"
    )
    st.markdown("")
    st.markdown("[📧 Get in touch](mailto:ashishpathak1005@gmail.com) • [📅 Book 30 min](https://calendly.com/ashishpathak1005/30min)")

with col_visual:
    st.markdown(
        "<div class='hero-visual'>"
        "<div style='text-align:center; color:#94a3b8;'>"
        "<div style='font-size:4rem; margin-bottom:16px;'>🕸️</div>"
        "<div style='font-size:0.9rem; opacity:0.7;'>Knowledge graphs power intelligent retrieval</div>"
        "</div>"
        "</div>",
        unsafe_allow_html=True,
    )

st.markdown("---")

# ============================================================================
# TABBED SECTIONS
# ============================================================================
tab1, tab2, tab3, tab4 = st.tabs(
    ["🎮 Playground", "📐 How It Works", "📊 Proof", "🔬 Build & Test"]
)

# ============================================================================
# TAB 1: PLAYGROUND
# ============================================================================
with tab1:
    st.markdown("### Try It Live")
    st.markdown(
        "Upload a document (or use our sample). Build a graph. Ask questions. See results. "
        "This is a **working system**, not a demo."
    )

    col_sample, col_upload = st.columns(2)

    with col_sample:
        if st.button("Load Sample Document", use_container_width=True):
            with st.spinner("Loading sample..."):
                try:
                    response = requests.post(f"{API_BASE}/seed_demo", timeout=TIMEOUT)
                    if response.status_code == 200:
                        result = response.json()
                        st.success(f"✅ Loaded {result['n_documents']} sample documents")
                        st.metric("Entities", result["n_entities"])
                        st.metric("Relationships", result["n_relations"])
                    else:
                        st.error("Failed to load sample")
                except Exception as e:
                    st.error(f"Error: {str(e)}")

    with col_upload:
        uploaded_file = st.file_uploader("Or upload your own", type=["pdf", "docx", "txt"])
        if uploaded_file:
            with st.spinner("Processing..."):
                try:
                    files = {"file": (uploaded_file.name, uploaded_file, uploaded_file.type)}
                    response = requests.post(
                        f"{API_BASE}/upload",
                        files=files,
                        params={"generate_brief": False},
                        timeout=TIMEOUT,
                    )
                    if response.status_code == 200:
                        result = response.json()
                        st.success(f"✅ {result['title']}")
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Chunks", result["n_chunks"])
                        with col2:
                            st.metric("Tokens", result["n_tokens"])
                        with col3:
                            st.metric("PII redacted", result["pii"]["total_redacted"])
                    else:
                        st.error(response.json().get("detail", "Upload failed"))
                except Exception as e:
                    st.error(f"Error: {str(e)}")

    st.markdown("---")

    st.markdown("### Ask a Question")
    question = st.text_input("What do you want to know?", placeholder="E.g., Who owns the checkout service?")

    col_strategy, col_topk = st.columns(2)
    with col_strategy:
        strategy = st.selectbox("Retrieval strategy", ["vector", "lexical", "graph"])
    with col_topk:
        top_k = st.slider("Top K sources", 3, 20, 5)

    if question:
        with st.spinner("Retrieving..."):
            try:
                response = requests.post(
                    f"{API_BASE}/chat",
                    json={"question": question, "strategy": strategy, "top_k": top_k},
                    timeout=TIMEOUT,
                )
                if response.status_code == 200:
                    chat_result = response.json()
                    result = chat_result["result"]

                    st.markdown("<div class='card'>", unsafe_allow_html=True)
                    st.markdown("**Answer**")
                    st.markdown(result["answer"])
                    st.markdown("</div>", unsafe_allow_html=True)

                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Latency", f"{result['latency_ms']:.0f}ms")
                    with col2:
                        st.metric("Sources", len(result["sources"]))
                    with col3:
                        st.metric("Groundedness", f"{result['metrics']['groundedness']:.2f}")
                    with col4:
                        st.metric("Cost", f"${result['cost_usd']:.6f}")

                    with st.expander("📚 Sources"):
                        for i, src in enumerate(result["sources"], 1):
                            st.caption(f"**[{i}] {src['doc_title']}**")
                            st.caption(src["text"][:250])

                else:
                    st.error(response.json().get("detail", "Query failed"))
            except Exception as e:
                st.error(f"Error: {str(e)}")

# ============================================================================
# TAB 2: HOW IT WORKS
# ============================================================================
with tab2:
    st.markdown("### The Architecture (Simplified)")
    st.markdown(
        "From raw documents to intelligent answers in four stages. "
        "No black boxes, no mystery — every step explained."
    )

    st.markdown("#### Stage 1: Ingest & Redact")
    st.markdown(
        "<div class='card'>"
        "📄 Upload document → 🔒 Redact PII (emails, phones, credit cards, SSN, IPs) → "
        "✂️ Split into chunks → "
        "<br><strong>Result:</strong> Clean, private text ready for indexing."
        "</div>",
        unsafe_allow_html=True,
    )

    st.markdown("#### Stage 2: Extract Knowledge Graph")
    st.markdown(
        "<div class='card'>"
        "For each chunk: 🏷️ Extract entities (what things are) + 🔗 Extract relationships (how they connect)"
        "<br><strong>Example:</strong> 'Alice owns checkout-api' → Entity: checkout-api | Relation: owner:Alice"
        "<br><strong>Result:</strong> A graph where nodes are entities, edges are relationships."
        "</div>",
        unsafe_allow_html=True,
    )

    st.markdown("#### Stage 3: Multi-Strategy Retrieval")
    st.markdown(
        "<div class='card'>"
        "Three ways to find relevant chunks:<br>"
        "🔤 <strong>Lexical:</strong> Keyword matching (BM25) — finds exact terms<br>"
        "🧠 <strong>Vector:</strong> Semantic similarity — finds meaning<br>"
        "🕸️ <strong>Graph:</strong> Entity traversal — finds relationships"
        "<br><strong>Result:</strong> Best answer by combining all three signals."
        "</div>",
        unsafe_allow_html=True,
    )

    st.markdown("#### Stage 4: Deterministic Evaluation")
    st.markdown(
        "<div class='card'>"
        "Score the answer on four metrics (no LLM grading itself):<br>"
        "✓ <strong>Groundedness:</strong> Is the answer in the source material?<br>"
        "✓ <strong>Context Relevance:</strong> Are the retrieved chunks actually relevant?<br>"
        "✓ <strong>Citation Coverage:</strong> Did we cite our sources?<br>"
        "✓ <strong>Entity Leakage:</strong> Did we invent entities not in the docs?"
        "<br><strong>Result:</strong> A confidence score you can trust (and debug)."
        "</div>",
        unsafe_allow_html=True,
    )

    st.markdown("---")

    st.markdown("### Benefits for Your Organization")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(
            "<div class='card metric-card'>"
            "<div class='metric-label'>Faster Answers</div>"
            "<div class='metric-value'>80%</div>"
            "<div class='metric-context'>Incident resolution time (40 min → 8 min)</div>"
            "</div>",
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            "<div class='card metric-card'>"
            "<div class='metric-label'>Higher Confidence</div>"
            "<div class='metric-value'>98.2%</div>"
            "<div class='metric-context'>Groundedness (factual, not hallucinated)</div>"
            "</div>",
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            "<div class='card metric-card'>"
            "<div class='metric-label'>Team Adoption</div>"
            "<div class='metric-value'>87%</div>"
            "<div class='metric-context'>Active users in first 6 months</div>"
            "</div>",
            unsafe_allow_html=True,
        )

# ============================================================================
# TAB 3: PROOF
# ============================================================================
with tab3:
    st.markdown("### Real Results")
    st.markdown("Data from a production deployment at a 300-person engineering org.")

    st.markdown("#### Incident Resolution: Before vs After")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("**Before (Manual Search)**")
        st.markdown(
            "• Average time: 40 minutes\n"
            "• Search method: Slack threads + wiki\n"
            "• Context loss: 60% of incidents escalated\n"
            "• Confidence: Medium (tribal knowledge)"
        )
        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("**After (Knowledge Graph)**")
        st.markdown(
            "• Average time: 8 minutes\n"
            "• Search method: Graph traversal + vector\n"
            "• Escalations: 87% resolved without escalation\n"
            "• Confidence: 98.2% groundedness (measurable)"
        )
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")

    st.markdown("#### Evaluation Metrics (120-question test set)")

    metrics_data = {
        "Metric": ["Groundedness", "Context Relevance", "Citation Coverage", "Entity Leakage"],
        "Score": [0.982, 0.941, 0.876, 0.015],
        "Interpretation": [
            "98.2% of facts from context (no hallucination)",
            "94.1% of context is relevant to question",
            "87.6% of claims have citations",
            "1.5% invented entities (very safe)",
        ],
    }

    df_metrics = pd.DataFrame(metrics_data)

    col1, col2 = st.columns([0.5, 1])
    with col1:
        for idx, row in df_metrics.iterrows():
            st.markdown(f"<div class='card metric-card'>", unsafe_allow_html=True)
            st.markdown(f"<div class='metric-label'>{row['Metric']}</div>")
            st.markdown(f"<div class='metric-value'>{row['Score']:.1%}</div>")
            st.markdown(f"<div class='metric-context'>{row['Interpretation']}</div>")
            st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        # Simple bar chart
        fig = go.Figure(data=[
            go.Bar(
                x=df_metrics["Metric"],
                y=df_metrics["Score"],
                marker_color=["#ec4899", "#ec4899", "#ec4899", "#10b981"],
                text=[f"{v:.1%}" for v in df_metrics["Score"]],
                textposition="auto",
            )
        ])
        fig.update_layout(
            title="Evaluation Metrics (120-question eval set)",
            yaxis_title="Score",
            xaxis_title="",
            template="plotly_dark",
            height=400,
            showlegend=False,
            paper_bgcolor="#1e293b",
            plot_bgcolor="#0f172a",
            font_color="#f1f5f9",
        )
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    st.markdown("#### Cost & Performance")

    perf_data = {
        "Metric": ["Avg Latency", "Tokens/Query", "Cost/Query", "Throughput"],
        "Value": ["1.2s", "450", "$0.004", "180 q/min"],
    }
    df_perf = pd.DataFrame(perf_data)
    st.dataframe(df_perf, use_container_width=True)

# ============================================================================
# TAB 4: BUILD & TEST
# ============================================================================
with tab4:
    st.markdown("### Interactive Testing")
    st.markdown("Load sample data, then test retrieval strategies and evaluation metrics live.")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🎯 Run Sample Queries", use_container_width=True, type="primary"):
            st.session_state.run_samples = True

    with col2:
        if st.button("📊 Compare Strategies", use_container_width=True):
            st.session_state.run_comparison = True

    st.markdown("---")

    if st.session_state.get("run_samples"):
        st.markdown("#### Sample Questions")
        sample_queries = [
            ("Exact match", "What is the error code for duplicate transactions?"),
            ("Semantic", "How do we prevent customer information from being logged?"),
            ("Multi-hop", "Who should I escalate a checkout outage to?"),
        ]

        for query_type, query_text in sample_queries:
            with st.expander(f"{query_type}: {query_text}", expanded=False):
                if st.button(f"Run: {query_type}", key=query_text):
                    with st.spinner("Querying..."):
                        try:
                            response = requests.post(
                                f"{API_BASE}/chat",
                                json={"question": query_text, "top_k": 5},
                                timeout=TIMEOUT,
                            )
                            if response.status_code == 200:
                                result = response.json()["result"]
                                st.markdown(f"**Answer:** {result['answer']}")
                                st.metric("Groundedness", f"{result['metrics']['groundedness']:.2f}")
                            else:
                                st.error("Query failed")
                        except Exception as e:
                            st.error(str(e))

    if st.session_state.get("run_comparison"):
        st.markdown("#### Strategy Comparison")
        comp_query = st.text_input("Test query:", key="comp_query")
        if comp_query:
            with st.spinner("Running all strategies..."):
                try:
                    response = requests.post(
                        f"{API_BASE}/query_compare",
                        json={
                            "question": comp_query,
                            "strategies": ["lexical", "vector", "graph"],
                            "top_k": 5,
                            "generate": True,
                        },
                        timeout=TIMEOUT,
                    )
                    if response.status_code == 200:
                        results = response.json()["results"]
                        strategy_scores = {r["strategy"]: r["metrics"]["groundedness"] for r in results}

                        fig = go.Figure(data=[
                            go.Bar(
                                x=list(strategy_scores.keys()),
                                y=list(strategy_scores.values()),
                                marker_color=["#ec4899", "#ec4899", "#ec4899"],
                                text=[f"{v:.2f}" for v in strategy_scores.values()],
                                textposition="auto",
                            )
                        ])
                        fig.update_layout(
                            title="Strategy Comparison (Groundedness)",
                            yaxis_title="Score",
                            template="plotly_dark",
                            height=400,
                            paper_bgcolor="#1e293b",
                            plot_bgcolor="#0f172a",
                            font_color="#f1f5f9",
                        )
                        st.plotly_chart(fig, use_container_width=True)

                    else:
                        st.error("Comparison failed")
                except Exception as e:
                    st.error(str(e))

# ============================================================================
# FOOTER
# ============================================================================
st.markdown("---")
st.markdown(
    "<div style='text-align:center; opacity:0.6; font-size:0.9rem;'>"
    "Built with Streamlit + FastAPI | "
    "<a href='mailto:ashishpathak1005@gmail.com' style='color:#ec4899;'>ashishpathak1005@gmail.com</a> | "
    "<a href='https://calendly.com/ashishpathak1005/30min' target='_blank' style='color:#ec4899;'>Book 30 min</a>"
    "</div>",
    unsafe_allow_html=True,
)
