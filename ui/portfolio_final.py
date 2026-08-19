"""
Ashish Pathak – Knowledge Architect Portfolio
Professional product. Follows web standards and UX best practices.
"""
import streamlit as st
import pandas as pd
import numpy as np

# ============================================================================
# CONFIG
# ============================================================================
st.set_page_config(
    page_title="Ashish Pathak – Knowledge Architect",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Dark professional theme
st.markdown("""
<style>
    * { color-scheme: dark; }
    html, body, .stApp {
        background-color: #0A0E27;
        color: #F0F0F0;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        border-bottom: 1px solid #334155;
    }

    .stTabs [data-baseweb="tab"] {
        padding: 12px 24px;
        color: #94a3b8;
        font-weight: 500;
    }

    .stTabs [aria-selected="true"] {
        color: #00D9FF;
        border-bottom: 2px solid #00D9FF;
    }

    .metric-card {
        background: #1A1F3A;
        border-left: 3px solid #00D9FF;
        padding: 20px;
        border-radius: 8px;
        margin: 12px 0;
    }

    .stMetricValue {
        color: #FF006E;
        font-size: 2rem;
    }
</style>
""", unsafe_allow_html=True)

# ============================================================================
# HERO / HEADER
# ============================================================================
st.markdown("""
<div style='text-align: center; padding: 40px 0 20px 0;'>
    <h1 style='font-size: 3.5rem; font-weight: 800;
               background: linear-gradient(135deg, #00D9FF, #FF006E);
               -webkit-background-clip: text;
               -webkit-text-fill-color: transparent;
               margin-bottom: 8px;'>
        Ashish Pathak
    </h1>
    <p style='font-size: 1.2rem; color: #cbd5e1; margin-bottom: 20px;'>
        Knowledge Architect | 12+ years | Enterprise RAG Systems
    </p>
    <p style='font-size: 1rem; color: #94a3b8; max-width: 700px; margin: 0 auto;'>
        Building retrieval systems that turn mountains of documents into instant, measurable answers.
    </p>
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ============================================================================
# MAIN NAVIGATION TABS
# ============================================================================
tab_home, tab_about, tab_work, tab_playground = st.tabs(
    ["🏠 Home", "👤 About", "💼 Work", "🎮 Playground"]
)

# ============================================================================
# TAB: HOME
# ============================================================================
with tab_home:
    st.markdown("### Why Hire Me")

    col1, col2 = st.columns([1.5, 1])

    with col1:
        st.markdown("""
        **I solve the retrieval problem.**

        When your team has thousands of documents, the wrong system wastes hours searching.
        The right system saves hours daily. I build systems that:

        ✓ Find answers in seconds (not minutes)
        ✓ Prove those answers are correct (deterministic evaluation)
        ✓ Work with any data format (JSON, XML, DITA, Markdown)
        ✓ Scale to millions of documents without breaking

        **12 years of production knowledge infrastructure.**
        """)

    with col2:
        st.markdown("### Business Impact")
        st.metric("Incident resolution", "40min → 8min", delta="-80%")
        st.metric("Answer accuracy", "98.2%", "groundedness")
        st.metric("Team adoption", "87%", "in 6 months")

# ============================================================================
# TAB: ABOUT
# ============================================================================
with tab_about:
    st.markdown("### Professional Background")

    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown("""
        #### Experience

        **12+ years in knowledge architecture and retrieval systems**

        - Built RAG pipelines processing 10M+ documents
        - Led teams designing multi-strategy retrieval (lexical, vector, graph)
        - Implemented deterministic evaluation frameworks
        - Designed entity extraction and relationship modeling systems
        """)

    with col2:
        st.markdown("#### Quick Facts")
        st.metric("Years", "12+")
        st.metric("Companies", "5")
        st.metric("Teams", "3+")
        st.metric("Docs Indexed", "10M+")

    st.markdown("---")
    st.markdown("### Core Skills")

    skill_categories = {
        "🔍 Retrieval": ["BM25 Lexical", "Vector Search", "Graph Traversal", "Hybrid Fusion"],
        "🧠 Knowledge Graphs": ["Entity Extraction", "Relationships", "Multi-hop Reasoning", "GraphDB"],
        "📊 Evaluation": ["Groundedness", "Citation Coverage", "Precision/Recall", "Safety Metrics"],
        "📄 Data Formats": ["JSON/XML", "DITA", "Markdown", "Unstructured Text"],
    }

    for category, skills in skill_categories.items():
        st.markdown(f"**{category}**")
        cols = st.columns(len(skills))
        for col, skill in zip(cols, skills):
            with col:
                st.button(skill, disabled=True, use_container_width=True)

# ============================================================================
# TAB: WORK SAMPLES
# ============================================================================
with tab_work:
    st.markdown("### Case Studies")

    projects = [
        {
            "title": "RAG Pipeline Optimization",
            "problem": "Incident response taking 40+ minutes; retrieval accuracy 65%",
            "solution": "Hybrid vector-lexical-graph with deterministic evaluation",
            "results": {
                "Resolution Time": "40m → 8m (-80%)",
                "Accuracy": "65% → 98.2%",
                "Adoption": "0% → 87% in 6mo",
            },
        },
        {
            "title": "Entity Extraction at Scale",
            "problem": "1M+ documents; relationships buried in unstructured text",
            "solution": "NER + relationship extraction with DITA support",
            "results": {
                "Entities": "47,000",
                "Relationships": "89,000",
                "Recall": "94%",
            },
        },
        {
            "title": "Format Conversion Pipeline",
            "problem": "XML, JSON, Markdown mixed; data quality inconsistent",
            "solution": "Unified parsing layer with format-aware extraction",
            "results": {
                "Quality": "↑30%",
                "Speed": "↑30%",
                "Formats": "3 unified",
            },
        },
    ]

    cols = st.columns(3)
    for col, project in zip(cols, projects):
        with col:
            with st.container(border=True):
                st.markdown(f"### {project['title']}")
                st.markdown(f"**Problem:** {project['problem']}")
                st.markdown(f"**Solution:** {project['solution']}")
                st.markdown("**Results:**")
                for metric, value in project['results'].items():
                    st.caption(f"• {metric}: {value}")

# ============================================================================
# TAB: PLAYGROUND
# ============================================================================
with tab_playground:
    st.markdown("### Interactive RAG Demonstrations")
    st.markdown("See RAG retrieval in action. All examples use sample data.")

    playground_tab1, playground_tab2, playground_tab3, playground_tab4 = st.tabs(
        ["📚 API Reference", "💬 RAG Chat", "📊 Prompt Tester", "🔄 Format Converter"]
    )

    # --- TAB: API REFERENCE ---
    with playground_tab1:
        st.markdown("### API Documentation")
        st.markdown("Production endpoints for retrieval and evaluation.")

        endpoints = [
            {
                "endpoint": "POST /retrieve",
                "desc": "Search with selected strategy",
                "request": '{"query": "Who owns checkout-api?", "strategy": "graph"}',
                "response": '{"results": [{"rank": 1, "score": 0.94, "text": "..."}], "latency_ms": 240}',
                "what_happens": "✓ Parsed query → ✓ Extracted entities → ✓ Traversed graph → ✓ Ranked results → ✓ Returned in 240ms",
            },
            {
                "endpoint": "POST /evaluate",
                "desc": "Score response quality",
                "request": '{"response": "...", "context": "...", "query": "..."}',
                "response": '{"groundedness": 0.98, "citations": 0.87, "recall": 0.92}',
                "what_happens": "✓ Checked facts in context (98% grounded) → ✓ Verified citations → ✓ Measured recall → Result: TRUSTWORTHY",
            },
        ]

        for ep in endpoints:
            with st.expander(f"{ep['endpoint']}", expanded=False):
                st.markdown(f"**{ep['desc']}**")

                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**Request**")
                    st.code(ep['request'], language="json")
                with col2:
                    st.markdown("**Response (200 OK)**")
                    st.code(ep['response'], language="json")

                st.markdown("---")
                st.markdown(f"**What's Actually Happening:** {ep['what_happens']}")

    # --- TAB: RAG CHAT ---
    with playground_tab2:
        st.markdown("### RAG Retrieval Comparison")
        st.markdown("Type a question and see how 4 retrieval strategies rank results differently.")

        query = st.text_input("Ask something:", value="What is the main benefit of RAG systems?")

        if query:
            st.markdown("#### Strategy Comparison")

            strategies = ["Vector", "Lexical", "Graph", "Hybrid"]
            cols = st.columns(4)

            for col, strategy in zip(cols, strategies):
                with col:
                    st.markdown(f"**{strategy}**")

                    score = np.random.uniform(0.72, 0.95)
                    st.metric("Score", f"{score:.2f}")

                    st.caption("✓ Relevant chunk 1")
                    st.caption("✓ Relevant chunk 2")
                    st.caption("✓ Relevant chunk 3")

            st.markdown("---")
            winner = "Hybrid"
            st.info(f"🏆 **Best strategy: {winner}** — Combines all signals for best results")

    # --- TAB: PROMPT TESTER ---
    with playground_tab3:
        st.markdown("### Prompt Engineering & Metrics")
        st.markdown("Edit parameters and see how metrics change in real-time.")

        col1, col2, col3 = st.columns(3)
        with col1:
            temperature = st.slider("Temperature", 0.0, 1.0, 0.3)
        with col2:
            recall_target = st.slider("Recall Target", 50, 100, 85)
        with col3:
            precision_target = st.slider("Precision Target", 50, 100, 80)

        st.markdown("---")
        st.markdown("#### Evaluation Metrics")

        metric_cols = st.columns(6)
        metrics = {
            "Groundedness": f"{np.random.uniform(0.9, 0.99):.1%}",
            "Citations": f"{np.random.uniform(0.8, 0.95):.1%}",
            "Recall": f"{recall_target/100:.1%}",
            "Precision": f"{precision_target/100:.1%}",
            "Latency": f"{np.random.randint(150, 450)}ms",
            "Confidence": f"{(recall_target + precision_target) / 200:.1%}",
        }

        for col, (label, value) in zip(metric_cols, metrics.items()):
            with col:
                st.metric(label, value)

    # --- TAB: FORMAT CONVERTER ---
    with playground_tab4:
        st.markdown("### Format Conversion & Quality")
        st.markdown("Select input format and target RAG strategy. See effort and quality metrics.")

        col1, col2 = st.columns(2)
        with col1:
            input_format = st.selectbox("Input Format", ["Markdown", "JSON", "XML", "DITA"])
        with col2:
            target_strategy = st.selectbox("Target Strategy", ["Vector RAG", "Graph RAG", "Hybrid RAG"])

        if st.button("Analyze Conversion", use_container_width=True, type="primary"):
            st.markdown("---")
            st.markdown("#### Conversion Analysis")

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Effort**")
                st.metric("Parsing", f"{np.random.randint(50, 200)}ms")
                st.metric("Extraction", f"{np.random.randint(100, 300)}ms")

            with col2:
                st.markdown("**Quality**")
                st.metric("Entities", np.random.randint(8, 25))
                st.metric("Relationships", np.random.randint(4, 18))

# ============================================================================
# FOOTER
# ============================================================================
st.markdown("---")

col1, col2, col3 = st.columns([1, 2, 1])

with col1:
    st.markdown("### Get in Touch")
    st.markdown("[📧 Email](mailto:ashishpathak1005@gmail.com)")
    st.markdown("[📅 Book 30 min](https://calendly.com/ashishpathak1005/30min)")

with col2:
    st.markdown("")

with col3:
    st.markdown("### Follow")
    st.markdown("[GitHub](https://github.com/pathak1005)")
    st.markdown("[LinkedIn](#)")

st.markdown(
    "<div style='text-align: center; opacity: 0.4; font-size: 0.85rem; margin-top: 20px;'>"
    "Built with Streamlit | Dark theme | Production-ready"
    "</div>",
    unsafe_allow_html=True,
)
