"""
One-page portfolio homepage for Ashish Pathak — Knowledge Architect.
Combines narrative + working GraphRAG demo with 4 interactive tabs.
"""
from __future__ import annotations

import json
import os
import time
from io import BytesIO

import streamlit as st
import requests
import plotly.graph_objects as go
import pandas as pd

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
    .block-container {max-width:1100px; margin:0 auto; padding-top:1.5rem; padding-left:24px; padding-right:24px; padding-bottom:2rem;}
    [data-testid='stMetricDelta'] {display:none;}
    header {margin-top: 0; padding-top: 0;}
    main {margin-top: 0; padding-top: 0;}

    .hero {font-size:3rem; font-weight:700; background:linear-gradient(135deg, #6366f1, #8b5cf6);
            -webkit-background-clip:text; -webkit-text-fill-color:transparent; line-height:1.2; margin-bottom:16px;}
    .subheader {font-size:1.2rem; opacity:0.8; font-weight:400; margin-bottom:32px;}
    .metric-card {background:#f9fafb; border-radius:12px; padding:24px; margin:16px 0; border:1px solid #e5e7eb;}
    .impact-row {display:flex; gap:32px; margin:20px 0; flex-wrap:wrap;}
    .impact-item {flex:1; min-width:250px;}
    .before-after {font-size:1.1rem; margin:12px 0;}
    .before {opacity:0.6; text-decoration:line-through;}
    .after {color:#10b981; font-weight:600;}
    .arrow {color:#6366f1; margin:0 8px;}
    .case-study {background:#efe9fe; border-left:4px solid #6d28d9; padding:24px; border-radius:8px; margin:24px 0;}
    .demo-section {margin-top:40px; padding-top:32px; border-top:1px solid #e5e7eb;}
    .code-block {background:#1e293b; color:#f1f5f9; padding:16px; border-radius:8px; font-family:monospace; font-size:0.85rem; overflow-x:auto; margin:12px 0;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================================
# HERO SECTION
# ============================================================================
st.markdown(
    "<div class='hero'>I build retrieval systems that don't just answer — they prove their answer.</div>",
    unsafe_allow_html=True,
)

st.markdown(
    "<div class='subheader'>"
    "12 years of knowledge architecture. Enterprise systems that reduce search time, prevent mistakes, and scale with confidence."
    "</div>",
    unsafe_allow_html=True,
)

st.markdown(
    "I design knowledge infrastructure that **works**. From entity extraction and multi-hop graph traversal "
    "to deterministic evaluation frameworks and real-time observability — systems your teams can trust and measure."
)

st.markdown("---")

# ============================================================================
# BUSINESS IMPACT
# ============================================================================
st.markdown("### Business Impact")

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Search resolution time", "8 min", "← 40 min")
with col2:
    st.metric("Answer groundedness", "98.2%", "over 120 questions")
with col3:
    st.metric("Team adoption", "87%", "in 6 months")

st.markdown(
    "<div class='metric-card'>"
    "<strong>Context:</strong> Enterprise team (50+ engineers) handling multi-service runbooks. "
    "Old system: full-text search, then manual parsing. New system: knowledge graph + entity traversal. "
    "Result: faster resolution, fewer escalations, higher confidence in answers."
    "</div>",
    unsafe_allow_html=True,
)

st.markdown("---")

# ============================================================================
# WHAT IS GRAPHRAG EXPLAINER
# ============================================================================
st.markdown("### How It Works: GraphRAG")

st.markdown(
    "GraphRAG builds a knowledge graph from your documents — extracting entities (what things are) and relationships (how they connect). "
    "Then it answers multi-hop questions by *traversing* those relationships, not just matching keywords. "
    "You get answers that chain together facts across your corpus, with proof of where each fact came from."
)

st.markdown(
    "<div class='metric-card' style='background:#f0fdf4; border-left:4px solid #10b981;'>"
    "<strong>Example:</strong> "
    "Q: 'Who should I escalate a checkout-api outage to?' A: System walks: checkout-api → owned by Team Meridian → on-call is Priya Raman. "
    "No single doc has that answer; the graph stitches it from relationships."
    "</div>",
    unsafe_allow_html=True,
)

st.markdown("---")

# ============================================================================
# CASE STUDY
# ============================================================================
st.markdown("### Case Study: From Manual Search to Automated Knowledge Retrieval")

st.markdown(
    "<div class='case-study'>"
    "<strong>Problem:</strong> A 300-person engineering org relied on Slack threads, wiki pages, and tribal knowledge to debug incidents. "
    "Average incident resolution time: 40 minutes. Many escalations happened because context was siloed.<br><br>"

    "<strong>Solution:</strong> Built a knowledge graph from runbooks, architecture docs, and team ownership data. "
    "Deployed with graph traversal + vector fallback. Added deterministic evaluation to measure answer quality in production.<br><br>"

    "<strong>Result:</strong><br>"
    "• Incident resolution time: 40 min → 8 min (80% faster)<br>"
    "• Answer confidence: 98.2% groundedness (factual, not hallucinated)<br>"
    "• Adoption: 87% of team using it within 6 months<br>"
    "• Cost: ~5 minutes per week to maintain (graph updates on wiki/runbook changes)<br>"
    "</div>",
    unsafe_allow_html=True,
)

st.markdown("---")

# ============================================================================
# DEMO SECTION
# ============================================================================
st.markdown("<div class='demo-section'></div>", unsafe_allow_html=True)
st.markdown("### Try It Now: Upload a Document & Explore")

st.markdown(
    "Upload your own PDF, Word doc, or text file. Build a graph. Ask multi-hop questions. "
    "See how lexical, vector, and graph retrieval compare. Test prompts and evaluation metrics."
)

# Initialize session state
if "uploaded_doc_id" not in st.session_state:
    st.session_state.uploaded_doc_id = None
if "graph_data" not in st.session_state:
    st.session_state.graph_data = None
if "evaluation_metrics" not in st.session_state:
    st.session_state.evaluation_metrics = None

# Demo tabs
tab1, tab2, tab3, tab4 = st.tabs(
    ["📊 Build Graph", "💬 Chat with Graph", "⚖️ Compare Strategies", "📈 Evaluation & Prompt Testing"]
)

# ============================================================================
# TAB 1: BUILD GRAPH
# ============================================================================
with tab1:
    st.markdown("#### Step 1: Upload a Document")
    st.markdown("PDF, DOCX, or TXT — up to 5 MB. System extracts entities and relationships automatically.")

    uploaded_file = st.file_uploader("Choose a file", type=["pdf", "docx", "txt"], key="graph_builder_upload")

    if uploaded_file:
        with st.spinner("Extracting text and building graph..."):
            try:
                files = {"file": (uploaded_file.name, uploaded_file, uploaded_file.type)}
                response = requests.post(
                    f"{API_BASE}/upload",
                    files=files,
                    params={"generate_brief": False},
                    timeout=TIMEOUT,
                )
                if response.status_code == 200:
                    ingest_result = response.json()
                    st.session_state.uploaded_doc_id = ingest_result["doc_id"]

                    st.success(f"✅ Document uploaded: {ingest_result['title']}")
                    st.markdown(
                        f"**Chunks:** {ingest_result['n_chunks']} | "
                        f"**Tokens:** {ingest_result['n_tokens']} | "
                        f"**PII redacted:** {ingest_result['pii']['total_redacted']}"
                    )

                    if ingest_result["pii"]["total_redacted"] > 0:
                        st.info(
                            f"🔒 **Privacy notice:** {ingest_result['pii']['total_redacted']} PII items were detected and redacted "
                            f"(emails, phone numbers, credit cards, etc). This happens before indexing."
                        )

                    # Fetch graph snapshot
                    graph_response = requests.get(f"{API_BASE}/graph", timeout=TIMEOUT)
                    if graph_response.status_code == 200:
                        st.session_state.graph_data = graph_response.json()

                        graph_info = graph_response.json()
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Entities", graph_info["n_entities"])
                        with col2:
                            st.metric("Relationships", graph_info["n_relations"])
                        with col3:
                            st.metric("Components", graph_info["n_components"])

                        if graph_info["n_components"] > 1:
                            st.warning(
                                f"⚠️ Graph has {graph_info['n_components']} disconnected components. "
                                "Multi-hop retrieval may miss some paths. Consider linking isolated entities."
                            )

                        # Graph visualization placeholder
                        st.markdown("#### Graph Visualization")
                        st.info(
                            "Graph visualization with Plotly nodes/edges will render here. "
                            "For now, see the entity and relationship tables below."
                        )

                        # Expandable tables
                        with st.expander("📋 Extracted Entities", expanded=False):
                            if "entities" in graph_info and graph_info["entities"]:
                                entities_df = pd.DataFrame([
                                    {"Entity": e, "Type": graph_info["entities"][e].get("type", "unknown")}
                                    for e in list(graph_info["entities"].keys())[:50]
                                ])
                                st.dataframe(entities_df, use_container_width=True)
                            else:
                                st.write("No entities extracted yet.")

                        with st.expander("🔗 Sample Relationships", expanded=False):
                            if "sample_triples" in graph_info and graph_info["sample_triples"]:
                                relationships = [
                                    {"Subject": t[0], "Relation": t[1], "Object": t[2]}
                                    for t in graph_info["sample_triples"][:20]
                                ]
                                rels_df = pd.DataFrame(relationships)
                                st.dataframe(rels_df, use_container_width=True)
                            else:
                                st.write("No relationships extracted yet.")

                else:
                    st.error(f"Upload failed: {response.json().get('detail', 'Unknown error')}")
            except Exception as e:
                st.error(f"Error: {str(e)}")

# ============================================================================
# TAB 2: CHAT WITH GRAPH
# ============================================================================
with tab2:
    if not st.session_state.uploaded_doc_id:
        st.warning("📝 Please upload a document in **Build Graph** tab first.")
    else:
        st.markdown("#### Ask a Multi-Hop Question")
        st.markdown(
            "Questions that span multiple documents or require traversing relationships work best. "
            "E.g., 'Who owns service X?' or 'What causes error Y?'"
        )

        query = st.text_input("Your question:", placeholder="E.g., What is the error code for duplicate transactions?")

        if query:
            with st.spinner("Querying graph..."):
                try:
                    response = requests.post(
                        f"{API_BASE}/chat",
                        json={"question": query, "strategy": "graph", "top_k": 5},
                        timeout=TIMEOUT,
                    )
                    if response.status_code == 200:
                        chat_result = response.json()
                        result = chat_result["result"]

                        st.markdown("#### Answer")
                        st.markdown(result["answer"])

                        col1, col2, col3, col4 = st.columns(4)
                        with col1:
                            st.metric("Latency", f"{result['latency_ms']:.0f} ms")
                        with col2:
                            st.metric("Sources", len(result["sources"]))
                        with col3:
                            st.metric("Prompt tokens", result["prompt_tokens"])
                        with col4:
                            st.metric("Completion tokens", result["completion_tokens"])

                        # Sources
                        with st.expander("📄 Retrieved Sources", expanded=True):
                            for i, source in enumerate(result["sources"], 1):
                                st.markdown(f"**[{i}] {source['doc_title']}**")
                                st.markdown(source["text"][:300] + "..." if len(source["text"]) > 300 else source["text"])
                                st.caption(f"Chunk {source['chunk_id']} | Rank: {source['rank']}")

                        # Metrics
                        with st.expander("📊 Evaluation Metrics", expanded=False):
                            metrics = result.get("metrics", {})
                            col1, col2, col3, col4 = st.columns(4)
                            with col1:
                                st.metric("Groundedness", f"{metrics.get('groundedness', 0):.3f}")
                            with col2:
                                st.metric("Context relevance", f"{metrics.get('context_relevance', 0):.3f}")
                            with col3:
                                st.metric("Entity leakage", f"{metrics.get('entity_leakage', 0):.3f}")
                            with col4:
                                st.metric("Citation coverage", f"{metrics.get('citation_coverage', 0):.3f}")

                        # Trace
                        if result.get("trace"):
                            with st.expander("🔍 Retrieval Trace", expanded=False):
                                st.json(result["trace"])

                    else:
                        st.error(f"Query failed: {response.json().get('detail', 'Unknown error')}")
                except Exception as e:
                    st.error(f"Error: {str(e)}")

# ============================================================================
# TAB 3: COMPARE STRATEGIES
# ============================================================================
with tab3:
    if not st.session_state.uploaded_doc_id:
        st.warning("📝 Please upload a document in **Build Graph** tab first.")
    else:
        st.markdown("#### Compare Three Retrieval Strategies")
        st.markdown(
            "Same question, same chunks, same prompt. The only difference is retrieval. "
            "Which strategy finds the best answer?"
        )

        query = st.text_input(
            "Your question:",
            placeholder="E.g., How do we prevent customer information from ending up in logs?",
            key="compare_query",
        )

        if query:
            with st.spinner("Running all three strategies..."):
                try:
                    response = requests.post(
                        f"{API_BASE}/query_compare",
                        json={
                            "question": query,
                            "strategies": ["lexical", "vector", "graph"],
                            "top_k": 5,
                            "generate": True,
                        },
                        timeout=TIMEOUT,
                    )
                    if response.status_code == 200:
                        compare_result = response.json()

                        # Winner
                        st.markdown("#### Winner")
                        if compare_result.get("winner"):
                            st.success(f"🏆 **{compare_result['winner'].upper()}** strategy wins")
                            st.markdown(compare_result["winner_reason"])
                        else:
                            st.info("No decisive winner (all strategies tied or failed to retrieve).")

                        # Side-by-side comparison
                        st.markdown("#### Side-by-Side Results")
                        for result in compare_result["results"]:
                            with st.expander(
                                f"📊 {result['strategy'].upper()} — "
                                f"Groundedness: {result['metrics']['groundedness']:.3f}",
                                expanded=result["strategy"] == compare_result.get("winner"),
                            ):
                                st.markdown("**Answer**")
                                st.markdown(result["answer"])

                                col1, col2, col3, col4 = st.columns(4)
                                with col1:
                                    st.metric("Groundedness", f"{result['metrics']['groundedness']:.3f}")
                                with col2:
                                    st.metric("Context relevance", f"{result['metrics']['context_relevance']:.3f}")
                                with col3:
                                    st.metric("Latency", f"{result['latency_ms']:.0f} ms")
                                with col4:
                                    st.metric("Cost", f"${result['cost_usd']:.6f}")

                                with st.expander("Sources"):
                                    for i, source in enumerate(result["sources"][:3], 1):
                                        st.caption(f"[{i}] {source['doc_title']}: {source['text'][:200]}...")

                    else:
                        st.error(f"Comparison failed: {response.json().get('detail', 'Unknown error')}")
                except Exception as e:
                    st.error(f"Error: {str(e)}")

# ============================================================================
# TAB 4: EVALUATION & PROMPT TESTING
# ============================================================================
with tab4:
    if not st.session_state.uploaded_doc_id:
        st.warning("📝 Please upload a document in **Build Graph** tab first.")
    else:
        st.markdown("#### Evaluate & Test Prompts")
        st.markdown(
            "Run a query, then tweak the system prompt, temperature, or recall target. "
            "Watch how evaluation metrics change. All metrics are deterministic (no LLM grading itself)."
        )

        col1, col2 = st.columns(2)
        with col1:
            query = st.text_input("Question:", key="eval_query")
        with col2:
            strategy = st.selectbox("Strategy:", ["vector", "lexical", "graph"], key="eval_strategy")

        st.markdown("#### Configuration")
        col1, col2, col3 = st.columns(3)
        with col1:
            temperature = st.slider("Temperature (LLM creativity)", 0.0, 1.0, 0.0, 0.1)
        with col2:
            recall_target = st.slider("Recall target (%)", 50, 100, 95, 5)
        with col3:
            top_k = st.slider("Top K (sources)", 3, 20, 5)

        system_prompt = st.text_area(
            "System Prompt (edit to test):",
            value=(
                "You are a precise assistant.\n"
                "Answer ONLY from the provided context.\n"
                "Cite your sources [1] [2] etc.\n"
                "If the context doesn't contain the answer, say so."
            ),
            height=100,
            key="eval_system_prompt",
        )

        if st.button("Run Evaluation", type="primary"):
            if not query:
                st.error("Please enter a question.")
            else:
                with st.spinner("Evaluating..."):
                    try:
                        response = requests.post(
                            f"{API_BASE}/chat",
                            json={
                                "question": query,
                                "strategy": strategy,
                                "top_k": top_k,
                            },
                            timeout=TIMEOUT,
                        )
                        if response.status_code == 200:
                            chat_result = response.json()
                            result = chat_result["result"]
                            metrics = result.get("metrics", {})

                            st.markdown("#### Metrics")
                            col1, col2, col3, col4 = st.columns(4)
                            with col1:
                                st.metric(
                                    "Groundedness",
                                    f"{metrics.get('groundedness', 0):.3f}",
                                    delta="Are facts in context?" if metrics.get("groundedness", 0) > 0.8 else "⚠️ Hallucination risk",
                                )
                            with col2:
                                st.metric(
                                    "Context relevance",
                                    f"{metrics.get('context_relevance', 0):.3f}",
                                    delta="Is context relevant?" if metrics.get("context_relevance", 0) > 0.7 else "⚠️ Retrieval issue",
                                )
                            with col3:
                                st.metric(
                                    "Citation coverage",
                                    f"{metrics.get('citation_coverage', 0):.3f}",
                                    delta="Cited sources?" if metrics.get("citation_coverage", 0) > 0.8 else "⚠️ Missing citations",
                                )
                            with col4:
                                st.metric(
                                    "Entity leakage",
                                    f"{metrics.get('entity_leakage', 0):.3f}",
                                    delta="Good" if metrics.get("entity_leakage", 0) < 0.1 else "⚠️ Over-generalized",
                                )

                            st.markdown("#### Answer")
                            st.markdown(result["answer"])

                            st.markdown("#### Metric Explanations")
                            with st.expander("What do these metrics mean?"):
                                st.markdown(
                                    "**Groundedness (0-1):** Fraction of answer sentences that appear in the context. "
                                    "High = factual, no hallucination. Low = LLM invented facts.\n\n"
                                    "**Context Relevance (0-1):** Fraction of context passages that contain answer-relevant information. "
                                    "High = good retrieval. Low = wasted tokens.\n\n"
                                    "**Citation Coverage (0-1):** Fraction of answer sentences with inline citations. "
                                    "High = transparent. Low = untraced claims.\n\n"
                                    "**Entity Leakage (0-1):** Fraction of entities in the answer that don't appear in context. "
                                    "High = hallucinated entities. Low = safe.\n\n"
                                    "All metrics are deterministic — no LLM grading its own answer."
                                )

                        else:
                            st.error(f"Evaluation failed: {response.json().get('detail', 'Unknown error')}")
                    except Exception as e:
                        st.error(f"Error: {str(e)}")

# ============================================================================
# FOOTER
# ============================================================================
st.markdown("---")
st.markdown(
    "<div style='text-align:center; opacity:0.7; font-size:0.9rem;'>"
    "Built by <strong>Ashish Pathak</strong> | "
    "<a href='mailto:ashishpathak1005@gmail.com'>Get in touch</a> | "
    "<a href='https://calendly.com/ashishpathak1005/30min' target='_blank'>Book 30 min</a>"
    "</div>",
    unsafe_allow_html=True,
)
