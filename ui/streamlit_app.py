"""Streamlit front end.

Pure HTTP client of the FastAPI service. It deliberately imports nothing from `app.*`:
if the UI imported the pipeline it would build a second copy of every index inside the
Streamlit process, doubling memory and letting the two copies drift apart.
"""
from __future__ import annotations

import os
import time

import requests
import streamlit as st

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000")
TIMEOUT = 120

st.set_page_config(
    page_title="RAG Architecture & Governance Engine",
    page_icon="::",
    layout="wide",
    initial_sidebar_state="expanded",
)

STRATEGY_META = {
    "lexical": ("Lexical / BM25", "#b45309", "Exact term matching. Same ranking function Elasticsearch uses."),
    "vector":  ("Dense Vector",   "#1d4ed8", "Semantic similarity. Finds paraphrases with no shared words."),
    "graph":   ("Graph / Multi-hop", "#047857", "Entity traversal. Assembles answers that span documents."),
    "hybrid":  ("Hybrid (RRF)",   "#6d28d9", "Reciprocal Rank Fusion over all three."),
}

EXAMPLES = [
    ("What causes ERR-7741?", "lexical",
     "A rare literal token. Dense embeddings compress ERR-7741 toward its 30 near-identical "
     "sibling codes; BM25 scores the exact term and wins."),
    ("How do we stop customer data leaking into our logs?", "vector",
     "The source document never says 'customer data' or 'leaking' - it says 'subscriber "
     "identifiers' and 'accidental disclosure'. No term overlap for BM25 to score."),
    ("Who should I escalate to if checkout-api is failing because of a payment problem?", "graph",
     "The answer spans three documents: checkout-api -> payments-gateway -> Team Meridian -> "
     "Priya Raman. No single chunk contains it, so flat retrieval cannot assemble it."),
]


# --------------------------------------------------------------------------
# API helpers
# --------------------------------------------------------------------------
def api_get(path: str, **params):
    try:
        r = requests.get(API_BASE + path, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        return {"__error__": "Cannot reach the API at " + API_BASE + ". Is uvicorn running?"}
    except requests.exceptions.HTTPError as exc:
        detail = ""
        try:
            detail = exc.response.json().get("detail", "")
        except Exception:  # noqa: BLE001
            detail = exc.response.text[:300]
        return {"__error__": detail or str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"__error__": str(exc)}


def api_post(path: str, payload: dict | None = None, files=None):
    try:
        r = requests.post(API_BASE + path, json=payload, files=files, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        return {"__error__": "Cannot reach the API at " + API_BASE + ". Is uvicorn running?"}
    except requests.exceptions.HTTPError as exc:
        detail = ""
        try:
            detail = exc.response.json().get("detail", "")
        except Exception:  # noqa: BLE001
            detail = exc.response.text[:300]
        return {"__error__": detail or str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"__error__": str(exc)}


def err(payload) -> str | None:
    if isinstance(payload, dict) and "__error__" in payload:
        return payload["__error__"]
    return None


# --------------------------------------------------------------------------
# Shared renderers
# --------------------------------------------------------------------------
def strategy_badge(name: str) -> str:
    label, colour, _ = STRATEGY_META.get(name, (name, "#475569", ""))
    return (
        "<span style='background:" + colour + ";color:#fff;padding:2px 10px;"
        "border-radius:10px;font-size:0.78rem;font-weight:600;'>" + label + "</span>"
    )


def render_routing(routing: dict, chosen: str | None = None) -> None:
    rec = routing["recommended"]
    header = "Router chose " + STRATEGY_META.get(rec, (rec,))[0]
    if chosen and chosen != rec:
        header += "  -  overridden to " + STRATEGY_META.get(chosen, (chosen,))[0]
    with st.expander(header + "   (confidence " + format(routing["confidence"], ".2f") + ")", expanded=False):
        st.markdown("**Query class:** `" + routing["query_class"] + "`")
        st.markdown("**Why:** " + routing["rationale"])
        scores = routing.get("scores", {})
        if scores:
            cols = st.columns(len(scores))
            for col, (name, value) in zip(cols, scores.items()):
                col.metric(STRATEGY_META.get(name, (name,))[0], format(value, ".2f"))
        signals = routing.get("signals", [])
        if signals:
            st.caption("Signals detected in the query:")
            st.dataframe(
                [
                    {
                        "signal": s["name"],
                        "matched text": s["value"],
                        "weight": s["weight"],
                        "favours": s["favors"],
                    }
                    for s in signals
                ],
                hide_index=True,
                use_container_width=True,
            )


def render_sources(sources: list[dict], key_prefix: str) -> None:
    if not sources:
        st.info("No sources retrieved for this strategy.")
        return
    for s in sources:
        title = "[" + str(s["rank"]) + "]  " + s["doc_title"] + "   -   score " + format(s["score"], ".4f")
        with st.expander(title, expanded=False):
            st.caption(s["why"])
            if s.get("graph_path"):
                st.markdown("**Traversal path**")
                st.code(" ".join(s["graph_path"]), language="text")
            st.markdown(s["text"])
            st.caption("chunk_id: `" + s["chunk_id"] + "`")


def render_metrics(result: dict, compact: bool = False) -> None:
    m = result["metrics"]
    cols = st.columns(4 if compact else 6)
    cols[0].metric("Groundedness", format(m["groundedness"], ".2f"))
    cols[1].metric("Ctx relevance", format(m["context_relevance"], ".2f"))
    cols[2].metric("Entity leakage", format(m["entity_leakage"], ".2f"),
                   help="Fraction of identifiers/numbers in the answer absent from context. Lower is better.")
    cols[3].metric("Citation cov.", format(m["citation_coverage"], ".2f"))
    if not compact:
        cols[4].metric("Latency", str(int(result["latency_ms"])) + " ms")
        cols[5].metric("Cost", "$" + format(result["cost_usd"], ".6f"))


# --------------------------------------------------------------------------
# Sidebar
# --------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### System")
    health = api_get("/health")
    health_error = err(health)
    if health_error:
        st.error(health_error)
        st.stop()

    backends = api_get("/backends")
    status_colour = "green" if health["status"] == "ok" else "orange"
    st.markdown(":" + status_colour + "[**" + health["status"].upper() + "**]  ·  v" + health["version"])

    st.caption(
        "graph: **" + backends.get("graph_backend", "?") + "**  ·  "
        "vector: **" + backends.get("vector_backend", "?") + "**"
    )
    st.caption(
        "embedder: **" + backends.get("embedder_mode", "?") + "** ("
        + str(backends.get("embedding_dim", "?")) + "d)  ·  llm: **"
        + ("groq" if health["llm_available"] else "extractive fallback") + "**"
    )
    if not health["llm_available"]:
        st.warning("No GROQ_API_KEY set. Answers use the deterministic extractive fallback.", icon=":")

    c1, c2, c3 = st.columns(3)
    c1.metric("Docs", health["n_documents"])
    c2.metric("Chunks", health["n_chunks"])
    c3.metric("Entities", health["n_entities"])

    st.divider()
    if health["n_chunks"] == 0:
        st.warning("No documents indexed yet.")
    if st.button("Load demo corpus", use_container_width=True, type="primary"):
        with st.spinner("Ingesting, redacting, extracting..."):
            result = api_post("/seed_demo")
        if err(result):
            st.error(err(result))
        else:
            st.success("Loaded " + str(len(result["loaded"])) + " documents, "
                       + str(result["n_relations"]) + " relations.")
            st.rerun()

    if st.button("Clear index", use_container_width=True):
        api_post("/reset")
        st.session_state.pop("messages", None)
        st.rerun()

    st.divider()
    st.markdown("### Retrieval")
    override = st.selectbox(
        "Strategy",
        ["Auto (router decides)", "lexical", "vector", "graph", "hybrid"],
        help="Auto lets the router classify the query and pick. Override to force one lane.",
    )
    top_k = st.slider("Top-K chunks", 1, 8, 3)

    # ---- author / links -------------------------------------------------
    AUTHOR_NAME = os.getenv("AUTHOR_NAME", "Ashish Pathak")
    AUTHOR_TAGLINE = os.getenv(
        "AUTHOR_TAGLINE", "Documentation, Knowledge Management & Content Engineering"
    )
    LINKS = [
        ("Portfolio", os.getenv("PORTFOLIO_URL", "")),
        ("Book a call", os.getenv("CALENDLY_URL", "")),
        ("LinkedIn", os.getenv("LINKEDIN_URL", "")),
        ("Source", os.getenv("GITHUB_URL", "")),
    ]
    active_links = [(label, url) for label, url in LINKS if url.strip()]

    st.divider()
    st.markdown("**" + AUTHOR_NAME + "**")
    st.caption(AUTHOR_TAGLINE)
    if active_links:
        st.markdown(
            "  ·  ".join("[" + label + "](" + url + ")" for label, url in active_links)
        )
    else:
        st.caption(
            "Set PORTFOLIO_URL and CALENDLY_URL in `.env` to show your links here."
        )


# --------------------------------------------------------------------------
# Tabs
# --------------------------------------------------------------------------
(
    tab_chat, tab_agent, tab_arena, tab_readiness, tab_playground,
    tab_graph, tab_ingest, tab_about,
) = st.tabs([
    "Chat", "Agent Pipeline", "Evaluation Arena", "RAG Readiness", "API Playground",
    "Knowledge Graph", "Ingestion & Governance", "Architecture",
])


# ========================= AGENT PIPELINE =================================
with tab_agent:
    st.markdown("#### Multi-agent pipeline (LangGraph)")
    st.caption(
        "Five agents with one responsibility each. The part that matters: if the grader "
        "judges retrieval too weak, the planner re-routes to a different strategy and retries "
        "instead of letting the generator paper over bad context."
    )

    st.code(
        "plan ──> retrieve ──> grade ──┬── context good ──> synthesize ──> verify ──> END\n"
        "  ▲                           │\n"
        "  └── re-route ◄──────────────┘  context weak, attempts remain",
        language="text",
    )

    c1, c2 = st.columns([3, 1])
    agent_q = c1.text_input(
        "Question",
        value="Who should I escalate to if checkout-api is failing because of a payment problem?",
        key="agent_q",
    )
    force = c2.selectbox("Force lane", ["Auto (self-correcting)", "lexical", "vector", "graph", "hybrid"])

    st.caption(
        "Try an out-of-corpus question (e.g. \"What is the capital of Mars?\") to watch the "
        "self-correction loop exhaust all three lanes and then abstain honestly."
    )

    if st.button("Run agent", type="primary", key="run_agent"):
        if health["n_chunks"] == 0:
            st.error("No documents indexed. Load the demo corpus from the sidebar first.")
        else:
            payload = {"question": agent_q, "top_k": top_k}
            if force != "Auto (self-correcting)":
                payload["strategy"] = force
            with st.spinner("Running plan / retrieve / grade / synthesize / verify..."):
                st.session_state["agent_result"] = api_post("/agent_query", payload)

    agent_result = st.session_state.get("agent_result")
    if agent_result:
        if err(agent_result):
            st.error(err(agent_result))
        else:
            tried = agent_result.get("strategies_tried", [])
            attempts = agent_result.get("attempts", 1)

            if attempts > 1:
                st.warning(
                    "**Self-correction fired.** " + str(attempts) + " attempts: "
                    + " → ".join(tried) + ". The grader rejected the first "
                    + str(attempts - 1) + " retrieval(s) as too weak to answer from.",
                    icon="!",
                )
            else:
                st.success(
                    "Answered on the first attempt using **" + str(agent_result["strategy"])
                    + "** - the planner routed correctly and the grader accepted the context."
                )

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Attempts", attempts)
            m2.metric("Final lane", str(agent_result["strategy"]))
            m3.metric("Grade", str(agent_result.get("grade", "-")))
            m4.metric("Cost", "$" + format(agent_result.get("cost_usd", 0), ".6f"))

            st.markdown("**Answer**")
            st.markdown(agent_result["answer"])

            st.caption("Grader: " + agent_result.get("grade_reason", ""))
            st.caption("Verifier: " + agent_result.get("verify_reason", ""))

            if agent_result.get("metrics"):
                render_metrics({
                    "metrics": agent_result["metrics"],
                    "latency_ms": agent_result.get("trace", {}).get("duration_ms", 0),
                    "cost_usd": agent_result.get("cost_usd", 0),
                }, compact=False)

            trace = agent_result.get("trace") or {}
            spans = trace.get("spans", [])
            if spans:
                st.markdown("##### Execution trace")
                st.caption(
                    "Recorded in-process - no external observability account required. "
                    + ("LangSmith is also receiving these spans."
                       if trace.get("langsmith") else
                       "Set LANGCHAIN_API_KEY to mirror these spans to LangSmith as well.")
                )
                colours = {"plan": "#6d28d9", "retrieve": "#1d4ed8", "grade": "#b45309",
                           "synthesize": "#047857", "verify": "#0f766e"}
                total = max(1.0, sum(s["duration_ms"] for s in spans))
                for i, s in enumerate(spans, start=1):
                    colour = colours.get(s["name"], "#475569")
                    width = max(2.0, s["duration_ms"] / total * 100)
                    st.markdown(
                        "<div style='display:flex;align-items:center;gap:10px;margin-bottom:4px;'>"
                        "<div style='width:26px;opacity:0.5;font-size:0.75rem;'>" + str(i) + "</div>"
                        "<div style='width:96px;font-weight:600;color:" + colour + ";'>" + s["name"] + "</div>"
                        "<div style='flex:1;background:rgba(128,128,128,0.15);border-radius:4px;height:16px;'>"
                        "<div style='width:" + format(width, ".1f") + "%;background:" + colour +
                        ";height:16px;border-radius:4px;'></div></div>"
                        "<div style='width:80px;text-align:right;font-size:0.8rem;opacity:0.7;'>"
                        + format(s["duration_ms"], ".2f") + " ms</div></div>",
                        unsafe_allow_html=True,
                    )
                    if s.get("notes"):
                        st.caption("        " + s["notes"][0])

                with st.expander("Full span detail (inputs / outputs)"):
                    st.json(spans)

            if agent_result.get("sources"):
                st.markdown("**Document sources**")
                render_sources(agent_result["sources"], "agent")

    st.divider()
    st.markdown("##### Recent traces")
    traces = api_get("/traces", limit=10)
    if err(traces):
        st.caption(err(traces))
    elif not traces.get("traces"):
        st.caption("No agent runs yet.")
    else:
        st.caption(
            "LangSmith: " + ("connected (project " + str(traces.get("langsmith_project")) + ")"
                             if traces.get("langsmith_enabled") else "not configured - local tracer active")
        )
        st.dataframe(
            [
                {
                    "trace_id": t["trace_id"],
                    "question": t["question"][:60] + ("..." if len(t["question"]) > 60 else ""),
                    "spans": t["n_spans"],
                    "attempts": t.get("summary", {}).get("attempts", "-"),
                    "lanes tried": ", ".join(t.get("summary", {}).get("tried", []) or []),
                    "ms": round(t["duration_ms"], 1),
                }
                for t in traces["traces"]
            ],
            hide_index=True, use_container_width=True,
        )


# ============================== CHAT ======================================
with tab_chat:
    st.markdown("#### Ask the corpus")
    st.caption(
        "The router classifies each question and picks a retrieval strategy, showing its reasoning. "
        "Every answer lists the exact source chunks it was built from."
    )

    with st.container(border=True):
        st.markdown("**When does each strategy win?** Click a question to see it happen.")
        cols = st.columns(3)
        for col, (question, expected, why) in zip(cols, EXAMPLES):
            with col:
                st.markdown(strategy_badge(expected), unsafe_allow_html=True)
                st.caption(why)
                if st.button(question, key="ex_" + expected, use_container_width=True):
                    st.session_state["pending"] = question

    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    for msg in st.session_state["messages"]:
        with st.chat_message(msg["role"]):
            if msg["role"] == "user":
                st.markdown(msg["content"])
            else:
                st.markdown(msg["content"])
                if msg.get("routing"):
                    render_routing(msg["routing"], msg.get("strategy"))
                if msg.get("result"):
                    render_metrics(msg["result"])
                    st.markdown("**Document sources**")
                    render_sources(msg["result"]["sources"], "hist")

    typed = st.chat_input("Ask about the Helios platform...")
    question = st.session_state.pop("pending", None) or typed

    if question:
        if health["n_chunks"] == 0:
            st.error("No documents indexed. Load the demo corpus from the sidebar first.")
        else:
            st.session_state["messages"].append({"role": "user", "content": question})
            with st.chat_message("user"):
                st.markdown(question)
            with st.chat_message("assistant"):
                with st.spinner("Routing, retrieving, generating..."):
                    payload = {"question": question, "top_k": top_k}
                    if override != "Auto (router decides)":
                        payload["strategy"] = override
                    response = api_post("/chat", payload)

                if err(response):
                    st.error(err(response))
                else:
                    result = response["result"]
                    routing = response["routing"]
                    used = result["strategy"]

                    st.markdown(strategy_badge(used), unsafe_allow_html=True)
                    if result.get("degraded"):
                        st.caption("Extractive fallback - no LLM available.")
                    st.markdown(result["answer"])

                    render_routing(routing, used)
                    render_metrics(result)
                    st.markdown("**Document sources**")
                    render_sources(result["sources"], "live")

                    st.session_state["messages"].append({
                        "role": "assistant",
                        "content": result["answer"],
                        "routing": routing,
                        "result": result,
                        "strategy": used,
                    })


# ============================ ARENA =======================================
with tab_arena:
    st.markdown("#### Evaluation Arena")
    st.caption(
        "All strategies run over the same chunk set with the same prompt, so any difference "
        "is attributable to retrieval alone - not to chunking or prompt drift."
    )

    arena_q = st.text_input(
        "Question",
        value="Who should I escalate to if checkout-api is failing because of a payment problem?",
        key="arena_q",
    )
    c1, c2 = st.columns([3, 1])
    chosen = c1.multiselect(
        "Strategies", ["lexical", "vector", "graph", "hybrid"],
        default=["lexical", "vector", "graph", "hybrid"],
    )
    do_generate = c2.toggle("Generate answers", value=True,
                            help="Off = retrieval-only benchmark, no LLM cost.")

    if st.button("Run comparison", type="primary"):
        if health["n_chunks"] == 0:
            st.error("No documents indexed. Load the demo corpus from the sidebar first.")
        elif not chosen:
            st.error("Select at least one strategy.")
        else:
            with st.spinner("Running all lanes..."):
                data = api_post("/query_compare", {
                    "question": arena_q, "strategies": chosen,
                    "top_k": top_k, "generate": do_generate,
                })
            if err(data):
                st.error(err(data))
            else:
                st.session_state["arena_result"] = data

    data = st.session_state.get("arena_result")
    if data:
        render_routing(data["routing"])
        if data.get("winner"):
            st.success("**Winner: " + data["winner"] + "**  -  " + data["winner_reason"])

        st.markdown("##### Scorecard")
        st.dataframe(
            [
                {
                    "strategy": r["strategy"],
                    "grounded": round(r["metrics"]["groundedness"], 3),
                    "ctx relevance": round(r["metrics"]["context_relevance"], 3),
                    "entity leakage": round(r["metrics"]["entity_leakage"], 3),
                    "citation cov": round(r["metrics"]["citation_coverage"], 3),
                    "retrieval ms": round(r["retrieval_ms"], 1),
                    "total ms": round(r["latency_ms"], 1),
                    "cost $": round(r["cost_usd"], 6),
                    "sources": len(r["sources"]),
                }
                for r in data["results"]
            ],
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            "All metrics are Tier-1 deterministic - computed without an LLM, so they are "
            "reproducible run to run. Entity leakage: lower is better."
        )

        st.markdown("##### Side by side")
        cols = st.columns(len(data["results"]))
        for col, result in zip(cols, data["results"]):
            with col:
                st.markdown(strategy_badge(result["strategy"]), unsafe_allow_html=True)
                st.caption(STRATEGY_META.get(result["strategy"], ("", "", ""))[2])
                if result["answer"]:
                    st.markdown(result["answer"])
                else:
                    st.caption("_Retrieval-only run._")
                render_metrics(result, compact=True)
                render_sources(result["sources"], "arena_" + result["strategy"])
                with st.expander("Retrieval trace"):
                    st.json(result["trace"])


# ========================== READINESS =====================================
with tab_readiness:
    st.markdown("#### Is this page RAG-ready?")
    st.caption(
        "Paste any page - a Confluence export, a README, a product doc - and get a scored "
        "assessment before it goes anywhere near an index. Nothing is stored or indexed."
    )

    SAMPLE_BAD = """Overview

It is a seamless, world-class platform that helps teams move faster. This makes it easy
for the team to leverage our next-generation capabilities across the org.

As mentioned above, the service handles incoming requests. They are processed by the
system and returned to the user. The above process is robust and scalable.

For questions contact the team at platform-help@example.com or call 415-555-0199. See
the previous section for configuration details."""

    c1, c2 = st.columns([1, 1])
    if c1.button("Load a weak example", use_container_width=True):
        st.session_state["readiness_text"] = SAMPLE_BAD
    if c2.button("Load a strong example", use_container_width=True):
        docs_avail = api_get("/documents")
        st.session_state["readiness_text"] = (
            "# Helios Platform - Runtime Dependency Map\n\n"
            "This document records the runtime call graph between production services. It is "
            "reviewed by the architecture group each month.\n\n"
            "The checkout-api depends on payments-gateway for authorisation of every order. A "
            "failure in that path surfaces to the customer as a declined checkout.\n\n"
            "The payments-gateway depends on ledger-service for write-ahead recording of every "
            "authorisation attempt before the card network is contacted.\n\n"
            "The ledger-service depends on postgres-primary for durable storage. The "
            "ledger-service runs on the shared transactional cluster."
        )

    paste = st.text_area(
        "Paste page content",
        value=st.session_state.get("readiness_text", ""),
        height=240,
        placeholder="Paste markdown or plain text here...",
    )
    page_title = st.text_input("Page title (optional)", value="Pasted content")

    if st.button("Analyze", type="primary", disabled=not paste.strip()):
        with st.spinner("Scoring..."):
            report = api_post("/analyze_readiness", {"text": paste, "title": page_title})
        if err(report):
            st.error(err(report))
        else:
            st.session_state["readiness_report"] = report

    report = st.session_state.get("readiness_report")
    if report:
        score = report["overall_score"]
        colour = "#047857" if score >= 80 else "#b45309" if score >= 55 else "#be123c"
        st.markdown(
            "<div style='background:" + colour + ";color:#fff;padding:18px 22px;border-radius:12px;"
            "display:flex;align-items:center;gap:22px;'>"
            "<div style='font-size:3rem;font-weight:700;line-height:1;'>" + str(score) + "</div>"
            "<div><div style='font-size:0.75rem;opacity:0.85;letter-spacing:0.08em;'>RAG READINESS</div>"
            "<div style='font-size:1.05rem;font-weight:600;'>" + report["verdict"] + "</div></div></div>",
            unsafe_allow_html=True,
        )

        st.markdown("")
        c1, c2, c3 = st.columns(3)
        c1.metric("Words", report["n_words"])
        c2.metric("Paragraphs", report["n_paragraphs"])
        c3.metric("Est. chunks", report["estimated_chunks"])

        st.markdown("##### Predicted retrievability")
        st.caption("How well this page is likely to be found by each strategy, given its shape.")
        pcols = st.columns(3)
        for col, (strat, value) in zip(pcols, report["predicted_retrievability"].items()):
            with col:
                st.markdown(strategy_badge(strat), unsafe_allow_html=True)
                st.progress(value / 100.0, text=str(value) + "/100")

        st.markdown("##### Dimension scores")
        st.dataframe(
            [
                {
                    "dimension": d["name"],
                    "score": d["score"],
                    "weight": d["weight"],
                    "what it measures": d["summary"],
                }
                for d in report["dimensions"]
            ],
            hide_index=True, use_container_width=True,
        )

        st.markdown("##### Findings")
        if not report["findings"]:
            st.success("No issues detected.")
        for f in report["findings"]:
            icon = {"high": "!!", "medium": "!", "low": "-"}[f["severity"]]
            with st.expander("[" + f["severity"].upper() + "] " + f["issue"], expanded=(f["severity"] == "high")):
                st.markdown("**Found in:**")
                st.code(f["evidence"], language="text")
                st.markdown("**Fix:** " + f["fix"])
                st.caption("dimension: " + f["dimension"])


# ========================= API PLAYGROUND =================================
with tab_playground:
    st.markdown("#### API Playground")
    st.caption(
        "Send a real request, then read the response with annotations. A 200 OK with a "
        "fluent answer can still be a complete failure - this shows you where to look."
    )

    ENDPOINTS = {
        "POST /chat": {
            "method": "POST", "path": "/chat",
            "body": {"question": "Who should I escalate to if checkout-api is failing because of a payment problem?", "top_k": 3},
            "what": "Answers one question. Omit `strategy` and the router picks a lane and explains why.",
        },
        "POST /query_compare": {
            "method": "POST", "path": "/query_compare",
            "body": {"question": "What causes ERR-7741?", "strategies": ["lexical", "vector", "graph"], "top_k": 3, "generate": True},
            "what": "Runs several lanes over the same chunks with the same prompt, then scores each.",
        },
        "POST /analyze_readiness": {
            "method": "POST", "path": "/analyze_readiness",
            "body": {
                "text": (
                    "Overview\n\nIt is a seamless, world-class platform that helps teams move "
                    "faster. This makes it easy for the team to leverage our next-generation "
                    "capabilities.\n\nAs mentioned above, the service handles incoming requests. "
                    "They are processed by the system and returned to the user. The above process "
                    "is robust and scalable.\n\nFor questions contact the team at "
                    "platform-help@example.com or call 415-555-0199."
                ),
                "title": "Sample page",
            },
            "what": "Scores arbitrary content for retrieval readiness. Does not index anything.",
        },
        "GET /route": {
            "method": "GET", "path": "/route",
            "body": {"q": "Which team owns the service that checkout-api depends on?"},
            "what": "Routing decision only - no retrieval, no LLM. The cheapest way to inspect the classifier.",
        },
        "GET /graph": {
            "method": "GET", "path": "/graph",
            "body": {"limit": 40},
            "what": "Current graph state. Watch `n_components` - it is the entity-resolution canary.",
        },
        "GET /health": {
            "method": "GET", "path": "/health",
            "body": {},
            "what": "Real index state, not just liveness.",
        },
    }

    choice = st.selectbox("Endpoint", list(ENDPOINTS.keys()))
    spec = ENDPOINTS[choice]
    st.info(spec["what"])

    import json as _json

    body_text = st.text_area(
        "Request " + ("body (JSON)" if spec["method"] == "POST" else "query parameters (JSON)"),
        value=_json.dumps(spec["body"], indent=2),
        height=170,
    )

    st.markdown("**Equivalent curl**")
    if spec["method"] == "POST":
        st.code(
            "curl -X POST " + API_BASE + spec["path"] + " \\\n"
            "  -H 'Content-Type: application/json' \\\n"
            "  -d '" + _json.dumps(spec["body"]) + "'",
            language="bash",
        )
    else:
        qs = "&".join(str(k) + "=" + str(v) for k, v in spec["body"].items())
        st.code("curl '" + API_BASE + spec["path"] + ("?" + qs if qs else "") + "'", language="bash")

    if st.button("Send request", type="primary"):
        try:
            parsed = _json.loads(body_text) if body_text.strip() else {}
        except _json.JSONDecodeError as exc:
            st.error("Invalid JSON: " + str(exc))
            parsed = None

        if parsed is not None:
            started = time.time()
            if spec["method"] == "POST":
                response = api_post(spec["path"], parsed)
            else:
                response = api_get(spec["path"], **parsed)
            st.session_state["pg_response"] = response
            st.session_state["pg_elapsed"] = (time.time() - started) * 1000
            st.session_state["pg_path"] = spec["path"]

    response = st.session_state.get("pg_response")
    if response is not None:
        st.markdown("---")
        if err(response):
            st.error("Request failed: " + err(response))
            st.markdown(
                "**What this means:** the API returned a structured error, not a crash. Every error "
                "response carries a `request_id` you can grep the server logs for. A 409 means no "
                "documents are indexed; a 415 means an unsupported file type; a 422 means the body "
                "failed Pydantic validation."
            )
        else:
            st.caption("Round trip: " + str(int(st.session_state.get("pg_elapsed", 0))) + " ms")

            left, right = st.columns([1, 1])
            with left:
                st.markdown("**Raw response**")
                st.json(response, expanded=False)

            with right:
                st.markdown("**What this response tells you**")
                if st.session_state.get("pg_path") in ("/chat", "/query_compare"):
                    explanation = api_post("/explain", response)
                    if err(explanation):
                        st.warning(err(explanation))
                    else:
                        st.markdown("**" + explanation["summary"] + "**")
                        icons = {"good": "OK", "warning": "WARN", "bad": "FAIL", "info": "INFO"}
                        colours = {"good": "#047857", "warning": "#b45309",
                                   "bad": "#be123c", "info": "#475569"}
                        for o in explanation["observations"]:
                            st.markdown(
                                "<div style='border-left:4px solid " + colours[o["verdict"]] +
                                ";padding:6px 0 6px 12px;margin-bottom:10px;'>"
                                "<div style='font-size:0.72rem;font-weight:700;color:" +
                                colours[o["verdict"]] + ";letter-spacing:0.06em;'>" +
                                icons[o["verdict"]] + " &middot; " + o["field"] + "</div>"
                                "<div style='font-weight:600;margin:2px 0;'>" + o["observation"] + "</div>"
                                "<div style='opacity:0.85;font-size:0.9rem;'>" + o["meaning"] + "</div>"
                                "</div>",
                                unsafe_allow_html=True,
                            )
                elif st.session_state.get("pg_path") == "/route":
                    st.markdown(
                        "This endpoint runs **no retrieval and no LLM**. `scores` shows each lane's "
                        "weighted total and `signals` shows exactly which phrases produced them. "
                        "If `recommended` looks wrong, the fix is a routing rule, not a prompt."
                    )
                elif st.session_state.get("pg_path") == "/graph":
                    n_comp = response.get("n_components", 0)
                    n_ent = response.get("n_entities", 1) or 1
                    if n_comp > n_ent * 0.3:
                        st.warning(
                            "`n_components` is " + str(n_comp) + " against " + str(n_ent) +
                            " entities. The graph is fragmented, so multi-hop traversal will "
                            "quietly under-retrieve. This is an entity-resolution problem, not a "
                            "traversal problem - and it is the most common reason graph RAG "
                            "'underperforms' in benchmarks."
                        )
                    else:
                        st.success(
                            "`n_components` is low relative to entity count - entity resolution is "
                            "merging surface forms properly and traversal can cross documents."
                        )
                elif st.session_state.get("pg_path") == "/health":
                    st.markdown(
                        "`status: degraded` is not an error. It means something is running in "
                        "fallback: no LLM key, or the TF-IDF embedder instead of fastembed. "
                        "Retrieval metrics stay valid and comparable in either case - only answer "
                        "fluency changes."
                    )
                else:
                    st.info("No interpreter registered for this endpoint.")

    st.markdown("---")
    st.markdown(
        "Full interactive OpenAPI docs: [" + API_BASE + "/docs](" + API_BASE + "/docs)  ·  "
        "Raw schema: [" + API_BASE + "/openapi.json](" + API_BASE + "/openapi.json)"
    )


# ============================ GRAPH =======================================
with tab_graph:
    st.markdown("#### Knowledge Graph")
    st.caption(
        "Built from the same chunks the vector index uses. Entities carry the chunk_ids "
        "they were mentioned in, which is how traversal converts structure back into text."
    )

    snapshot = api_get("/graph", limit=120)
    if err(snapshot):
        st.error(err(snapshot))
    elif snapshot["n_entities"] == 0:
        st.info("Graph is empty. Load the demo corpus from the sidebar.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Entities", snapshot["n_entities"])
        c2.metric("Relations", snapshot["n_relations"])
        c3.metric("Components", snapshot["n_components"],
                  help="Disconnected islands. Many components means entity resolution is "
                       "leaving duplicates unmerged, and multi-hop traversal will under-retrieve.")
        c4.metric("Largest component", format(snapshot["largest_component_pct"], ".1f") + "%")

        if snapshot["n_components"] > snapshot["n_entities"] * 0.3:
            st.warning(
                "High component count relative to entity count. On a real corpus this is the "
                "signal to invest in entity resolution (embedding clustering, alias tables) "
                "before blaming the traversal logic.",
                icon=":",
            )

        type_filter = st.multiselect(
            "Filter by entity type",
            sorted({n["type"] for n in snapshot["nodes"]}),
            default=[],
        )

        keep = {
            n["id"] for n in snapshot["nodes"]
            if not type_filter or n["type"] in type_filter
        }
        edges = [e for e in snapshot["edges"] if e["source"] in keep and e["target"] in keep]
        labels = {n["id"]: n["label"] for n in snapshot["nodes"]}
        colours = {
            "Service": "#1d4ed8", "Team": "#047857", "Person": "#b45309",
            "ErrorCode": "#be123c", "Channel": "#6d28d9", "Policy": "#0f766e",
            "Concept": "#64748b",
        }

        if edges:
            lines = ["digraph G {", "  rankdir=LR;", "  bgcolor=\"transparent\";",
                     "  node [shape=box style=\"rounded,filled\" fontname=\"Helvetica\" "
                     "fontsize=10 fontcolor=\"#ffffff\" penwidth=0];",
                     "  edge [fontname=\"Helvetica\" fontsize=8 color=\"#94a3b8\"];"]
            drawn = {e["source"] for e in edges} | {e["target"] for e in edges}
            for node in snapshot["nodes"]:
                if node["id"] not in drawn:
                    continue
                colour = colours.get(node["type"], "#64748b")
                lines.append(
                    '  "' + node["id"] + '" [label="' + labels[node["id"]].replace('"', "") +
                    '" fillcolor="' + colour + '"];'
                )
            for e in edges[:220]:
                lines.append(
                    '  "' + e["source"] + '" -> "' + e["target"] +
                    '" [label="' + e["relation"] + '"];'
                )
            lines.append("}")
            st.graphviz_chart("\n".join(lines), use_container_width=True)
        else:
            st.info("No edges match the current filter.")

        with st.expander("Relation table"):
            st.dataframe(
                [
                    {
                        "subject": labels.get(e["source"], e["source"]),
                        "relation": e["relation"],
                        "object": labels.get(e["target"], e["target"]),
                        "confidence": e["confidence"],
                        "evidence chunks": len(e["chunk_ids"]),
                    }
                    for e in edges
                ],
                hide_index=True,
                use_container_width=True,
            )


# ========================== INGESTION =====================================
with tab_ingest:
    st.markdown("#### Ingestion & Governance")
    st.caption("PII is redacted before chunking, embedding, or any LLM contact.")

    uploaded = st.file_uploader(
        "Upload a document", type=["md", "txt", "markdown", "rst", "pdf"],
        help="Max 5 MB. Text is scrubbed of emails, phones, SSNs, cards, IPs and keys before indexing.",
    )
    if uploaded is not None and st.button("Ingest document", type="primary"):
        with st.spinner("Redacting, chunking, embedding, extracting relations..."):
            files = {"file": (uploaded.name, uploaded.getvalue())}
            result = api_post("/upload", files=files)
        if err(result):
            st.error(err(result))
        else:
            st.session_state["last_ingest"] = result
            st.rerun()

    ingest = st.session_state.get("last_ingest")
    if ingest:
        st.success("Ingested **" + ingest["title"] + "** in " + str(int(ingest["elapsed_ms"])) + " ms")
        pii = ingest["pii"]
        c1, c2, c3, c4 = st.columns(4)
        if pii["total_redacted"]:
            c1.markdown(
                "<div style='background:#be123c;color:#fff;padding:8px 14px;border-radius:8px;"
                "text-align:center;font-weight:600;'>PII SCRUBBED<br/><span style='font-size:1.6rem'>"
                + str(pii["total_redacted"]) + "</span></div>",
                unsafe_allow_html=True,
            )
        else:
            c1.markdown(
                "<div style='background:#047857;color:#fff;padding:8px 14px;border-radius:8px;"
                "text-align:center;font-weight:600;'>NO PII<br/><span style='font-size:1.6rem'>0</span></div>",
                unsafe_allow_html=True,
            )
        c2.metric("Chunks", ingest["n_chunks"])
        c3.metric("Entities added", ingest["graph"]["entities_added"])
        c4.metric("Relations added", ingest["graph"]["relations_added"])

        if pii["by_type"]:
            st.markdown("**Redacted entity types**")
            st.dataframe(
                [{"type": k, "count": v} for k, v in sorted(pii["by_type"].items(), key=lambda kv: -kv[1])],
                hide_index=True, use_container_width=True,
            )
            st.caption("Raw values are never returned by the API - the audit trail stores masked previews only.")

        if ingest["graph"]["sample_triples"]:
            st.markdown("**Sample extracted relations**")
            st.code(
                "\n".join(" --[".join([t[0], t[1] + "]--> " + t[2]]) for t in ingest["graph"]["sample_triples"]),
                language="text",
            )

        if ingest["brief_markdown"]:
            st.markdown("**Structured Content Brief**")
            st.download_button(
                "Download brief (.md)",
                data=ingest["brief_markdown"],
                file_name=ingest["doc_id"] + "_brief.md",
                mime="text/markdown",
                type="primary",
            )
            with st.expander("Preview brief"):
                st.markdown(ingest["brief_markdown"])

    st.divider()
    st.markdown("##### Indexed documents")
    docs = api_get("/documents")
    if err(docs):
        st.error(err(docs))
    elif not docs:
        st.info("Nothing indexed yet.")
    else:
        for doc in docs:
            c1, c2, c3, c4 = st.columns([4, 1, 1, 2])
            c1.markdown("**" + doc["title"] + "**  \n`" + doc["doc_id"] + "`")
            c2.metric("chunks", doc["n_chunks"])
            c3.metric("PII", doc["pii_redacted"])
            if doc["has_brief"]:
                brief_md = api_get("/brief/" + doc["doc_id"])
                if isinstance(brief_md, str):
                    c4.download_button(
                        "Brief (.md)", data=brief_md,
                        file_name=doc["doc_id"] + "_brief.md",
                        mime="text/markdown", key="dl_" + doc["doc_id"],
                        use_container_width=True,
                    )


# =========================== ABOUT ========================================
with tab_about:
    st.markdown("#### System Architecture")

    st.markdown("""
##### The load-bearing decision

Three retrievers, **one chunk table**. Documents are redacted and chunked exactly once;
lexical, vector and graph all select from that identical immutable set, and all three feed
the same prompt template.

That is what makes the comparison mean anything. Two RAG systems with different chunking
and different prompts cannot be compared - any score gap is unattributable. Here the only
variable is retrieval.

```
Document
   |
   +-- PII redaction          <- before chunking; no raw PII reaches embedder/LLM/provider
   +-- Chunk once             <- immutable chunk_id set, shared by everything downstream
         |
         +-- BM25 index       -> lexical retriever  --+
         +-- Embeddings       -> vector retriever   --+--> chunk_ids -> ONE prompt -> LLM
         +-- Entities/relations -> graph retriever  --+
                                          |
                                          +-- RRF fusion -> hybrid
```

##### When each strategy wins

| Query shape | Winner | Why the others fail |
| --- | --- | --- |
| Exact identifier (`ERR-7741`) | **Lexical** | Dense vectors compress rare tokens toward their neighbourhood; 30 near-identical sibling codes become indistinguishable |
| Conceptual paraphrase | **Vector** | Source wording shares no terms with the question, so BM25 has nothing to score |
| Multi-entity relational | **Graph** | The answer spans documents; no single chunk contains it, so flat retrieval cannot assemble it |
| Ambiguous | **Hybrid** | RRF over all three - lower variance than betting on one |

The router makes this decision explicitly and shows its signals, rather than hiding it in a
learned black box. In production the rules would be replaced by a classifier trained on the
gold set, keeping the same signal interface.

##### Graph ranking

Traversal returns **chunks, not triples**. The graph is an index over existing chunks, which
is what makes the arena fair and what makes migration cheap.

Ranking is two-factor: `reachability / sqrt(entities in chunk) x idf-weighted relevance`.
Reachability alone fails - hop decay buries a 3-hop answer under incidental 0-hop mentions,
and a document header naming twenty services is reachable from everywhere while being about
nothing. The saturation term and IDF weighting were both added after the gold set showed the
correct answer ranking fifth.

##### Evaluation honesty

Every metric shown is **Tier-1 deterministic** - no LLM in the loop, reproducible run to run.
Using the generator to grade itself is neither independent nor deterministic, and an
evaluation-literate reviewer will find that immediately.

- **Groundedness** - answer content supported by context. Catches confabulated specifics.
- **Entity leakage** - identifiers/numbers asserted but absent from context. The sharpest
  hallucination signal, because fabricated specifics are what actually cost users something.
- **Context relevance** - isolates *retrieval* failure from *generation* failure.
- **Citation coverage** - answer sentences with a supporting chunk.

An honest "I don't know" scores as grounded, not as a hallucination. Scoring abstention as
failure rewards models that bluff.

##### Known limits

- **Single uvicorn worker.** Indexes live in process memory; `--workers 2` would give each
  worker a different graph and produce phantom bugs. Fixing that means persistent Chroma and
  Neo4j - both already implemented behind the backend switches.
- **Rule-based extraction.** Excellent on structured engineering docs, weak on prose. The
  upgrade is LLM triple extraction with a JSON schema; the interface does not change.
- **Component count is the canary.** If the graph fragments, traversal quietly under-retrieves
  and graph RAG looks bad for reasons that have nothing to do with graph RAG.
""")

    st.divider()
    st.markdown("##### Live backend configuration")
    st.json(backends)
