"""Streamlit front end.

Pure HTTP client of the FastAPI service. It deliberately imports nothing from
`app.retrieval`/`app.store`: if the UI imported the pipeline it would build a second copy
of every index inside the Streamlit process, doubling memory and letting the two copies
drift apart. It does import `app.adminstore`, which only reads/writes a JSON file - no
retrieval state there to duplicate.

Three menus, on purpose. An engineering demo with nine tabs and a sidebar full of backend
internals reads as a debug console, not a portfolio piece:

    Home            - who built this, and why (the portfolio page)
    RAG Simulator   - the actual demonstration: add content, then either ask it a
                      question (three-way retrieval comparison) or ask how retrieval-
                      ready the content itself is
    API Playground  - the same OpenAPI spec that powers /docs, with worked examples
                      and interpreted responses
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
from ui.portfolio import contact_banner, render_admin, render_portfolio

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000")
TIMEOUT = 120
MAX_EVAL_WORDS = 500

st.set_page_config(
    page_title="RAG Simulator - Ashish Pathak",
    page_icon="\U0001F50D",   # magnifying glass - single emoji, not a shortcode
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown(
    "<style>"
    "section[data-testid='stSidebar'] {display:none;}"
    ".block-container {max-width:900px; padding-top:2rem;}"
    "</style>",
    unsafe_allow_html=True,
)

STRATEGY_META = {
    "lexical":      ("Lexical (BM25)", "#b45309", "Exact keyword matching - what Elasticsearch does by default."),
    "vector":       ("Vector (semantic)", "#1d4ed8", "Meaning-based similarity - finds paraphrases with no shared words."),
    "graph":        ("Graph (multi-hop)", "#047857", "Follows entity relationships across documents."),
    "hybrid_graph": ("Hybrid RAG", "#6d28d9", "Vector search seeds the graph, then traversal expands it."),
    "hybrid":       ("Hybrid (RRF)", "#6d28d9", "Fuses the rankings of all three lanes."),
}

EXAMPLES = [
    ("What causes ERR-7741?", "lexical"),
    ("How do we stop customer data leaking into our logs?", "vector"),
    ("Who should I escalate to if checkout-api is failing because of a payment problem?", "graph"),
]


# --------------------------------------------------------------------------
# API helpers - every failure returns a small dict, never a raw traceback
# --------------------------------------------------------------------------
def api_get(path: str, **params):
    try:
        r = requests.get(API_BASE + path, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        return {"__error__": "Can't reach the backend right now."}
    except requests.exceptions.HTTPError as exc:
        try:
            detail = exc.response.json().get("detail", "")
        except Exception:  # noqa: BLE001
            detail = "Request failed."
        return {"__error__": detail}
    except Exception:  # noqa: BLE001
        return {"__error__": "Something went wrong on that request."}


def api_post(path: str, payload: dict | None = None, files=None):
    try:
        r = requests.post(API_BASE + path, json=payload, files=files, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        return {"__error__": "Can't reach the backend right now."}
    except requests.exceptions.HTTPError as exc:
        try:
            detail = exc.response.json().get("detail", "")
        except Exception:  # noqa: BLE001
            detail = "Request failed."
        return {"__error__": detail}
    except Exception:  # noqa: BLE001
        return {"__error__": "Something went wrong on that request."}


def err(payload) -> str | None:
    return payload.get("__error__") if isinstance(payload, dict) else None


def word_count(text: str) -> int:
    return len(text.split())


def truncate_words(text: str, limit: int) -> str:
    words = text.split()
    return text if len(words) <= limit else " ".join(words[:limit])


def strategy_badge(name: str) -> str:
    label, colour, _ = STRATEGY_META.get(name, (name, "#475569", ""))
    return (
        "<span style='background:" + colour + ";color:#fff;padding:2px 10px;"
        "border-radius:10px;font-size:0.78rem;font-weight:600;'>" + label + "</span>"
    )


# --------------------------------------------------------------------------
# Admin gate - reached at ?admin=<ADMIN_SLUG>. The slug keeps the panel out of
# casual view; the scrypt password hash in app/adminstore.py is the actual control.
# --------------------------------------------------------------------------
if st.query_params.get("admin") == adminstore.ADMIN_SLUG:
    render_admin()
    st.stop()


content = adminstore.load_content()

# --------------------------------------------------------------------------
# Top navigation
# --------------------------------------------------------------------------
if "nav" not in st.session_state:
    st.session_state["nav"] = "Home"

nav = st.segmented_control(
    "Navigate",
    ["Home", "RAG Simulator", "API Playground"],
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
    render_portfolio(content)

    st.divider()
    st.markdown("#### About this project")
    st.markdown(
        "**RAG Simulator** compares three ways of retrieving information from documents - "
        "keyword search, semantic search, and graph traversal - side by side on the same "
        "content, so it's visible which approach actually answers which kind of question. "
        "It also scores every answer without using an LLM to grade itself, and checks "
        "whether a piece of writing is even structured well enough to be retrieved reliably."
    )
    if st.button("Try the simulator →", type="primary"):
        st.session_state["nav"] = "RAG Simulator"
        st.rerun()
    st.caption(
        "Source code: [github.com/pathak1005/rag-arena](https://github.com/pathak1005/rag-arena)"
    )


# ============================================================================
# RAG SIMULATOR
# ============================================================================
elif nav == "RAG Simulator":
    contact_banner(content, "sim_top")

    health = api_get("/health")
    backend_down = bool(err(health))
    if backend_down:
        st.error("The backend isn't reachable, so the simulator can't run right now.")
        st.stop()

    n_chunks = health.get("n_chunks", 0)
    degraded_llm = not health.get("llm_available", False)

    # ---- workspace status, replacing what used to be a whole sidebar -------
    c1, c2, c3 = st.columns([2, 2, 1])
    c1.caption(str(health.get("n_documents", 0)) + " document(s) in the workspace")
    c2.caption(str(n_chunks) + " chunks indexed")
    if c3.button("Clear", use_container_width=True, disabled=n_chunks == 0):
        api_post("/reset")
        st.session_state.pop("sim_result", None)
        st.rerun()

    st.markdown("### 1. Add something to work with")
    source = st.segmented_control(
        "Source", ["Sample corpus", "Paste text", "Upload a file"],
        default="Sample corpus", label_visibility="collapsed",
    )

    if source == "Sample corpus":
        st.caption(
            "A small set of fictional engineering docs (service ownership, on-call, error "
            "codes) built so each retrieval strategy has a question it clearly wins."
        )
        if st.button("Load sample corpus", type="primary", disabled=n_chunks > 0):
            with st.spinner("Redacting, chunking, extracting relationships..."):
                result = api_post("/seed_demo")
            if err(result):
                st.error(err(result))
            else:
                st.rerun()
        if n_chunks > 0:
            st.success("Sample corpus is loaded. Move to step 2.")

    elif source == "Paste text":
        st.info(
            "Good practice: write for retrieval, not just for reading. Name the subject "
            "explicitly instead of using “it” or “the service” - once this "
            "text is split into chunks, a pronoun's referent may end up in a different chunk."
        )
        pasted = st.text_area("Paste markdown or plain text", height=200, key="paste_ingest")
        title = st.text_input("A short title for this content", value="Pasted content")
        if st.button("Add to workspace", type="primary", disabled=not pasted.strip()):
            with st.spinner("Redacting, chunking, extracting relationships..."):
                result = api_post("/ingest_text", {"title": title, "text": pasted, "generate_brief": False})
            if err(result):
                st.error(err(result))
            else:
                if result["pii"]["total_redacted"]:
                    st.success(str(result["pii"]["total_redacted"]) + " PII value(s) redacted before indexing.")
                st.rerun()

    else:
        uploaded = st.file_uploader("Upload a document", type=["md", "txt", "markdown", "rst", "pdf"])
        if uploaded is not None and st.button("Add to workspace", type="primary"):
            with st.spinner("Redacting, chunking, extracting relationships..."):
                # generate_brief=false: the simulator never displays briefs, and briefing
                # is one extra LLM call per document - measured up to 48s on its own.
                result = api_post("/upload?generate_brief=false", files={"file": (uploaded.name, uploaded.getvalue())})
            if err(result):
                st.error(err(result))
            else:
                if result["pii"]["total_redacted"]:
                    st.success(str(result["pii"]["total_redacted"]) + " PII value(s) redacted before indexing.")
                st.rerun()

    if n_chunks == 0:
        st.info("Add content above to continue.")
        st.stop()

    st.markdown("### 2. What do you want to do with it?")
    mode = st.segmented_control(
        "Mode", ["Ask about this content", "Evaluate content fitness"],
        default="Ask about this content", label_visibility="collapsed",
    )

    # ---------------------------------------------------------------- ask
    if mode == "Ask about this content":
        st.caption("Runs the same question through three retrieval strategies over the same chunks.")

        cols = st.columns(3)
        for col, (q, _) in zip(cols, EXAMPLES):
            if col.button(q, use_container_width=True, key="ex_" + q[:12]):
                st.session_state["sim_question"] = q

        question = st.text_input(
            "Your question", value=st.session_state.get("sim_question", ""), key="sim_question_box",
        )
        include_hybrid = st.checkbox("Also include Hybrid RAG (vector → graph)", value=False)
        top_k = st.slider("Chunks per strategy", 1, 6, 3)

        if st.button("Compare strategies", type="primary", disabled=not question.strip()):
            strategies = ["lexical", "vector", "graph"] + (["hybrid_graph"] if include_hybrid else [])
            with st.spinner("Routing, retrieving, generating..."):
                result = api_post("/query_compare", {
                    "question": question, "strategies": strategies, "top_k": top_k, "generate": True,
                })
            st.session_state["sim_result"] = None if err(result) else result
            if err(result):
                st.error(err(result))

        result = st.session_state.get("sim_result")
        if result:
            routing = result["routing"]
            st.caption(
                "If left to route itself, this question would use **"
                + STRATEGY_META.get(routing["recommended"], (routing["recommended"],))[0]
                + "** - " + routing["rationale"]
            )
            if degraded_llm:
                st.caption("No LLM key configured: answers below are extracted from context, not generated.")

            if result.get("winner"):
                st.success("Best result: **" + STRATEGY_META.get(result["winner"], (result["winner"],))[0] + "** - " + result["winner_reason"])

            cols = st.columns(len(result["results"]))
            for col, r in zip(cols, result["results"]):
                with col:
                    st.markdown(strategy_badge(r["strategy"]), unsafe_allow_html=True)
                    st.caption(STRATEGY_META.get(r["strategy"], ("", "", ""))[2])
                    if r["answer"]:
                        st.markdown(r["answer"])
                    else:
                        st.caption("No answer - nothing relevant was retrieved.")
                    m = r["metrics"]
                    mc1, mc2 = st.columns(2)
                    mc1.metric("Grounded", format(m["groundedness"], ".2f"))
                    mc2.metric("Leakage", format(m["entity_leakage"], ".2f"),
                               help="Fraction of names/numbers in the answer that aren't in the retrieved text. Lower is better.")
                    with st.expander("Sources & technical detail"):
                        if not r["sources"]:
                            st.caption("Nothing retrieved.")
                        for s in r["sources"]:
                            st.caption("[" + str(s["rank"]) + "] " + s["doc_title"] + "  ·  score " + format(s["score"], ".3f"))
                            st.caption(s["why"])
                            st.markdown(s["text"][:280] + ("..." if len(s["text"]) > 280 else ""))
                            if s.get("graph_path"):
                                st.code(" ".join(s["graph_path"]), language="text")
            st.caption(
                "This comparison is also available programmatically via a self-correcting "
                "agent pipeline that re-routes on a weak retrieval - see `/agent_query` in "
                "the API Playground."
            )

    # ---------------------------------------------------------- evaluate
    else:
        st.info(
            "Good practice: run this before publishing a page, not after. A page that scores "
            "poorly here will retrieve inconsistently no matter which strategy is used."
        )
        text = st.text_area(
            "Paste content to evaluate (max " + str(MAX_EVAL_WORDS) + " words)",
            height=220, key="eval_text",
        )
        wc = word_count(text)
        if wc > MAX_EVAL_WORDS:
            st.caption(str(wc) + " words - only the first " + str(MAX_EVAL_WORDS) + " will be evaluated.")
        elif wc:
            st.caption(str(wc) + " / " + str(MAX_EVAL_WORDS) + " words")

        if st.button("Evaluate", type="primary", disabled=not text.strip()):
            trimmed = truncate_words(text, MAX_EVAL_WORDS)
            with st.spinner("Scoring..."):
                report = api_post("/analyze_readiness", {"text": trimmed, "title": "Pasted content"})
            st.session_state["sim_readiness"] = None if err(report) else report
            if err(report):
                st.error(err(report))

        report = st.session_state.get("sim_readiness")
        if report:
            score = report["overall_score"]
            colour = "#047857" if score >= 80 else "#b45309" if score >= 55 else "#be123c"
            st.markdown(
                "<div style='background:" + colour + ";color:#fff;padding:16px 20px;border-radius:10px;"
                "display:flex;align-items:center;gap:18px;'>"
                "<div style='font-size:2.4rem;font-weight:700;'>" + str(score) + "</div>"
                "<div>" + report["verdict"] + "</div></div>",
                unsafe_allow_html=True,
            )
            st.write("")
            pcols = st.columns(3)
            for col, (strat, value) in zip(pcols, report["predicted_retrievability"].items()):
                with col:
                    st.markdown(strategy_badge(strat), unsafe_allow_html=True)
                    st.progress(value / 100.0, text=str(value) + "/100")

            if report["findings"]:
                st.markdown("**What to fix, in order**")
                for f in report["findings"][:5]:
                    with st.expander("[" + f["severity"].upper() + "] " + f["issue"]):
                        st.code(f["evidence"], language="text")
                        st.markdown(f["fix"])


# ============================================================================
# API PLAYGROUND
# ============================================================================
else:
    contact_banner(content, "api_top")

    spec = api_get("/openapi.json")
    if err(spec):
        st.error("Can't reach the backend to load the API spec right now.")
        st.stop()

    st.caption(
        "This talks to the exact OpenAPI spec served at [/openapi.json](" + API_BASE + "/openapi.json) "
        "and documented at [/docs](" + API_BASE + "/docs)."
    )

    ENDPOINTS = {
        "POST /chat": {
            "method": "POST", "path": "/chat",
            "body": {"question": "Who should I escalate to if checkout-api is failing because of a payment problem?", "top_k": 3},
            "tip": "Good practice: check `metrics.context_relevance` before trusting `metrics.groundedness`. "
                   "High groundedness with low relevance usually means the model answered from its own "
                   "training, not from your documents - the words just happened to overlap.",
        },
        "POST /query_compare": {
            "method": "POST", "path": "/query_compare",
            "body": {"question": "What causes ERR-7741?", "strategies": ["lexical", "vector", "graph"], "top_k": 3, "generate": True},
            "tip": "Good practice: compare strategies on questions designed to discriminate between them. "
                   "If every strategy returns the same chunks, the question isn't testing retrieval - "
                   "it's testing whether the corpus is small enough that everything looks relevant.",
        },
        "POST /analyze_readiness": {
            "method": "POST", "path": "/analyze_readiness",
            "body": {"text": "The service handles requests. It depends on the database.", "title": "Sample"},
            "tip": "Good practice: run this on a draft before it's published, not on live content after "
                   "users have already reported bad answers. Fixing a page in review is free; fixing it "
                   "after it's indexed and cached is not.",
        },
        "GET /route": {
            "method": "GET", "path": "/route",
            "body": {"q": "Which team owns the service that checkout-api depends on?"},
            "tip": "Good practice: log routing decisions in production. If a category of question keeps "
                   "getting misrouted, that's a cheap, inspectable signal - fix the rule or retrain the "
                   "classifier, rather than trying to fix it by prompting the generator harder.",
        },
        "POST /agent_query": {
            "method": "POST", "path": "/agent_query",
            "body": {"question": "Who owns payments-gateway?", "top_k": 3},
            "tip": "Good practice: keep the grader deterministic. An LLM grading its own retrieval and "
                   "then its own answer compounds the same bias twice - it can't reliably catch the "
                   "mistake it's most likely to make.",
        },
        "GET /health": {
            "method": "GET", "path": "/health",
            "body": {},
            "tip": "Good practice: a health check should report real state (index size, model loaded), "
                   "not just process liveness. `{\"ok\": true}` tells an on-call engineer nothing.",
        },
    }

    choice = st.selectbox("Endpoint", list(ENDPOINTS.keys()))
    ep = ENDPOINTS[choice]

    spec_entry = spec.get("paths", {}).get(ep["path"], {}).get(ep["method"].lower(), {})
    description = spec_entry.get("description") or spec_entry.get("summary") or ""
    if description:
        st.markdown(description.split("\n")[0])
    st.info(ep["tip"])

    import json as _json

    body_text = st.text_area(
        "Request " + ("body (JSON)" if ep["method"] == "POST" else "query parameters (JSON)"),
        value=_json.dumps(ep["body"], indent=2), height=140,
    )

    if ep["method"] == "POST":
        st.code(
            "curl -X POST " + API_BASE + ep["path"] + " -H 'Content-Type: application/json' -d '"
            + _json.dumps(ep["body"]) + "'",
            language="bash",
        )
    else:
        qs = "&".join(str(k) + "=" + str(v) for k, v in ep["body"].items())
        st.code("curl '" + API_BASE + ep["path"] + ("?" + qs if qs else "") + "'", language="bash")

    if st.button("Send request", type="primary"):
        try:
            parsed = _json.loads(body_text) if body_text.strip() else {}
        except _json.JSONDecodeError as exc:
            st.error("Invalid JSON: " + str(exc))
            parsed = None
        if parsed is not None:
            started = time.time()
            response = api_post(ep["path"], parsed) if ep["method"] == "POST" else api_get(ep["path"], **parsed)
            st.session_state["pg_response"] = response
            st.session_state["pg_elapsed"] = (time.time() - started) * 1000
            st.session_state["pg_path"] = ep["path"]

    response = st.session_state.get("pg_response")
    if response is not None:
        st.divider()
        if err(response):
            st.error(err(response))
        else:
            st.caption("Round trip: " + str(int(st.session_state.get("pg_elapsed", 0))) + " ms")
            left, right = st.columns(2)
            with left:
                st.markdown("**Raw response**")
                st.json(response, expanded=False)
            with right:
                st.markdown("**What this tells you**")
                if st.session_state.get("pg_path") in ("/chat", "/query_compare"):
                    explanation = api_post("/explain", response)
                    if err(explanation):
                        st.caption(err(explanation))
                    else:
                        st.markdown("**" + explanation["summary"] + "**")
                        colours = {"good": "#047857", "warning": "#b45309", "bad": "#be123c", "info": "#475569"}
                        for o in explanation["observations"]:
                            c = colours.get(o["verdict"], "#475569")
                            st.markdown(
                                "<div style='border-left:3px solid " + c + ";padding-left:10px;margin-bottom:8px;'>"
                                "<div style='font-weight:600;font-size:0.9rem;'>" + o["observation"] + "</div>"
                                "<div style='opacity:0.8;font-size:0.85rem;'>" + o["meaning"] + "</div></div>",
                                unsafe_allow_html=True,
                            )
                else:
                    st.caption("See the response body for details.")
