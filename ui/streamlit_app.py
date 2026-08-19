"""
Ashish Pathak – Knowledge Architect Portfolio.

Single-file Streamlit app. Dark theme, tabbed navigation.
Content is pulled from data/portfolio.json (real resume/profile data) and
data/demo_corpus/*.md (the same sample corpus the FastAPI backend seeds
for demo queries) so every number and answer on this page is grounded in
real text, not placeholder randomness.
"""
import json
import re
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
CALENDLY = "https://calendly.com/ashishpathak1005/30min"

# ============================================================================
# CONFIG & THEME
# ============================================================================
st.set_page_config(
    page_title="Ashish Pathak – Knowledge Architect",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    * { color-scheme: dark; }
    html, body, .stApp { background-color: #0A0E27; color: #F0F0F0; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; border-bottom: 1px solid #334155; }
    .stTabs [data-baseweb="tab"] { padding: 12px 24px; color: #94a3b8; font-weight: 500; }
    .stTabs [aria-selected="true"] { color: #00D9FF; border-bottom: 2px solid #00D9FF; }
    .card { background: #1A1F3A; border-left: 3px solid #00D9FF; padding: 20px; border-radius: 8px; margin: 12px 0; }
    .pill {
        display: inline-block; background: #1A1F3A; border: 1px solid #334155;
        color: #cbd5e1; padding: 4px 12px; border-radius: 999px; font-size: 0.82rem;
        margin: 3px; white-space: nowrap;
    }
    .answer-box { background: #10162E; border: 1px solid #00D9FF44; padding: 18px 20px; border-radius: 10px; margin: 12px 0; }
</style>
""", unsafe_allow_html=True)

# ============================================================================
# DATA LOADING (real resume + real sample corpus)
# ============================================================================
@st.cache_data
def load_portfolio() -> dict:
    path = ROOT / "data" / "portfolio.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


@st.cache_data
def load_corpus() -> list[dict]:
    """Split each demo doc into paragraph-level chunks, same corpus the API seeds."""
    chunks = []
    corpus_dir = ROOT / "data" / "demo_corpus"
    if not corpus_dir.exists():
        return chunks
    for path in sorted(corpus_dir.glob("*.md")):
        title = path.stem.replace("_", " ").title()
        paragraphs = [p.strip() for p in path.read_text(encoding="utf-8").split("\n\n") if p.strip()]
        for para in paragraphs:
            if para.startswith("#"):
                continue
            chunks.append({"doc": title, "text": para})
    return chunks


PORTFOLIO = load_portfolio()
CORPUS = load_corpus()
PROFILE = PORTFOLIO.get("profile", {})

# ============================================================================
# RETRIEVAL / SCORING HELPERS (deterministic, driven by real input — not random)
# ============================================================================
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "are", "for", "on", "with",
    "as", "by", "at", "be", "this", "that", "it", "from", "we", "our", "you", "your",
    "how", "what", "which", "who", "when", "do", "does", "can", "should", "if", "i",
}
_WORD = re.compile(r"[A-Za-z][A-Za-z\-']+|\d+")
_ENTITY = re.compile(r"\b[A-Z][a-zA-Z]+(?:[\s-][A-Z][a-zA-Z]+)*\b")
_TAG = re.compile(r"</?([\w:-]+)")
_JSON_KEY = re.compile(r'"([\w\-]+)"\s*:')
_RELATION_CUES = re.compile(r"\b(owns?|owned by|depends? on|escalates? to|emits?|requires?|calls?|reachable|reports? to)\b", re.I)


def _keywords(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text) if w.lower() not in _STOP and len(w) > 2}


def score_chunk(query_words: set[str], chunk_text: str, mode: str) -> float:
    """Approximate scoring per strategy, all derived from the actual query and chunk text."""
    chunk_words = _keywords(chunk_text)
    if not query_words or not chunk_words:
        return 0.0
    overlap = query_words & chunk_words

    if mode == "lexical":
        return len(overlap) / max(1, len(query_words))
    if mode == "vector":
        # Looser match: partial/substring overlap approximates semantic proximity.
        soft_hits = sum(
            1 for qw in query_words
            if any(qw in cw or cw in qw for cw in chunk_words)
        )
        return soft_hits / max(1, len(query_words))
    if mode == "graph":
        entities = set(e.lower() for e in _ENTITY.findall(chunk_text))
        entity_hits = sum(1 for qw in query_words if any(qw in e for e in entities))
        base = len(overlap) / max(1, len(query_words))
        return min(1.0, base + 0.35 * entity_hits)
    if mode == "hybrid":
        return max(
            score_chunk(query_words, chunk_text, "lexical"),
            score_chunk(query_words, chunk_text, "vector"),
            score_chunk(query_words, chunk_text, "graph"),
        )
    return 0.0


def retrieve(query: str, mode: str, k: int = 3) -> list[dict]:
    qwords = _keywords(query)
    scored = [
        {**c, "score": score_chunk(qwords, c["text"], mode)}
        for c in CORPUS
    ]
    scored.sort(key=lambda x: -x["score"])
    return [c for c in scored[:k] if c["score"] > 0]


def synthesize_answer(query: str, sources: list[dict]) -> str:
    """Extractive answer: same technique the real backend falls back to without an LLM."""
    if not sources:
        return "The provided context does not contain this information."
    qwords = _keywords(query)
    sentences = []
    for i, src in enumerate(sources, 1):
        for sent in re.split(r"(?<=[.!?])\s+", src["text"]):
            sent = sent.strip()
            if len(sent) < 20:
                continue
            swords = _keywords(sent)
            overlap = len(qwords & swords)
            if overlap > 0:
                sentences.append((overlap, sent, i))
    sentences.sort(key=lambda x: -x[0])
    picked = sentences[:2] or [(0, sources[0]["text"][:200], 1)]
    return " ".join(f"{s.rstrip('.')} [{i}]." for _, s, i in picked)


def evaluate_response(response: str, context: str, query: str) -> dict:
    """Deterministic metrics from actual text overlap — changes when the input changes."""
    resp_words = _keywords(response)
    ctx_words = _keywords(context)
    q_words = _keywords(query)

    groundedness = len(resp_words & ctx_words) / max(1, len(resp_words)) if resp_words else 0.0
    context_relevance = len(q_words & ctx_words) / max(1, len(q_words)) if q_words else 0.0

    sentences = [s for s in re.split(r"(?<=[.!?])\s+", response) if s.strip()]
    cited = sum(1 for s in sentences if "[" in s)
    citation_coverage = cited / max(1, len(sentences))

    unmatched_entities = [e for e in _ENTITY.findall(response) if e.lower() not in ctx_words and len(e) > 2]
    entity_leakage = min(1.0, len(unmatched_entities) / max(1, len(sentences) * 2))

    recall = len(ctx_words & q_words) / max(1, len(q_words)) if q_words else 0.0
    precision = len(resp_words & ctx_words) / max(1, len(resp_words | q_words)) if (resp_words or q_words) else 0.0

    return {
        "groundedness": min(1.0, groundedness),
        "context_relevance": min(1.0, context_relevance),
        "citation_coverage": min(1.0, citation_coverage),
        "entity_leakage": entity_leakage,
        "recall": min(1.0, recall),
        "precision": min(1.0, precision),
    }


def analyze_format(text: str, fmt: str) -> dict:
    """Conversion-effort analysis derived from the actual pasted text."""
    n_chars = len(text)
    if fmt in ("XML", "DITA"):
        tags = _TAG.findall(text)
        entities = len(set(tags))
    elif fmt == "JSON":
        keys = _JSON_KEY.findall(text)
        entities = len(set(keys))
    else:
        entities = len(set(_ENTITY.findall(text)))

    relations = len(_RELATION_CUES.findall(text))
    parsing_ms = max(15, n_chars // 8)
    extraction_ms = 40 + entities * 12 + relations * 8
    quality = min(0.97, 0.45 + 0.04 * entities + 0.03 * relations)

    return {
        "entities": entities,
        "relations": relations,
        "parsing_ms": parsing_ms,
        "extraction_ms": extraction_ms,
        "quality": quality,
    }


# ============================================================================
# HERO
# ============================================================================
name = PROFILE.get("name", "Ashish Pathak")
headline = PROFILE.get("headline", "Knowledge Architect")
summary_paras = [p for p in PROFILE.get("summary", "").split("\n\n") if p.strip()]
tagline = summary_paras[0] if summary_paras else "I engineer wisdom for humans and machines."

st.markdown(f"""
<div style='text-align: center; padding: 40px 0 20px 0;'>
    <h1 style='font-size: 3.2rem; font-weight: 800;
               background: linear-gradient(135deg, #00D9FF, #FF006E);
               -webkit-background-clip: text; -webkit-text-fill-color: transparent;
               margin-bottom: 8px;'>
        {name}
    </h1>
    <p style='font-size: 1.15rem; color: #cbd5e1; margin-bottom: 18px;'>{headline}</p>
    <p style='font-size: 1.05rem; color: #94a3b8; max-width: 760px; margin: 0 auto; line-height: 1.6;'>
        {tagline}
    </p>
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ============================================================================
# MAIN NAVIGATION
# ============================================================================
tab_home, tab_about, tab_work, tab_playground = st.tabs(
    ["🏠 Welcome", "👤 About", "💼 Work", "🎮 Playground"]
)

# ---- TAB: WELCOME ----
with tab_home:
    col1, col2 = st.columns([1.5, 1])

    with col1:
        st.markdown("### Welcome")
        for para in summary_paras[1:]:
            st.markdown(para)

        st.markdown("")
        st.markdown("**Where to go from here:**")
        st.markdown(
            "- **About** — full experience, skills, education, certifications\n"
            "- **Work** — real projects, with links\n"
            "- **Playground** — try the retrieval strategies live, on the actual sample corpus"
        )

    with col2:
        st.markdown("### Get the Resume")
        resume_md = PORTFOLIO.get("resume", {}).get("markdown", "")
        if resume_md:
            st.download_button(
                "⬇ Download Resume (.md)",
                data=resume_md,
                file_name="Ashish_Kumar_Pathak_Resume.md",
                mime="text/markdown",
                use_container_width=True,
            )
        col_a, col_b = st.columns(2)
        with col_a:
            st.link_button("📧 Email", f"mailto:{PROFILE.get('email', 'ashishpathak1005@gmail.com')}", use_container_width=True)
        with col_b:
            st.link_button("📅 Book time", PROFILE.get("calendly_url") or CALENDLY, use_container_width=True)
        if PROFILE.get("linkedin_url"):
            st.link_button("LinkedIn", PROFILE["linkedin_url"], use_container_width=True)
        if PROFILE.get("github_url"):
            st.link_button("GitHub", PROFILE["github_url"], use_container_width=True)

# ---- TAB: ABOUT ----
with tab_about:
    st.markdown("### Professional Summary")
    for para in summary_paras:
        st.markdown(para)

    resume_md = PORTFOLIO.get("resume", {}).get("markdown", "")
    if resume_md:
        st.download_button(
            "⬇ Download full resume (.md)",
            data=resume_md,
            file_name="Ashish_Kumar_Pathak_Resume.md",
            mime="text/markdown",
            key="about_resume_dl",
        )

    st.markdown("---")
    st.markdown("### Experience")
    experience = PORTFOLIO.get("experience", [])
    for i, job in enumerate(experience):
        with st.expander(f"**{job['title']}** — {job['company']} ({job['period']})", expanded=(i == 0)):
            for h in job.get("highlights", []):
                st.markdown(f"- {h}")

    st.markdown("---")
    st.markdown("### Skills")
    skills = PORTFOLIO.get("skills", [])
    if skills:
        st.markdown(
            "".join(f"<span class='pill'>{s}</span>" for s in skills),
            unsafe_allow_html=True,
        )

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("---")
        st.markdown("### Education")
        for ed in PORTFOLIO.get("education", []):
            st.markdown(f"**{ed['qualification']}**")
            st.caption(f"{ed['institution']} · {ed['period']}")

    with col2:
        st.markdown("---")
        st.markdown("### Certifications")
        for cert in PORTFOLIO.get("certifications", []):
            st.markdown(f"- {cert}")

# ---- TAB: WORK ----
with tab_work:
    st.markdown("### Projects")
    projects = PORTFOLIO.get("projects", [])

    cols = st.columns(len(projects) if projects else 1)
    for col, project in zip(cols, projects):
        with col:
            with st.container(border=True):
                st.markdown(f"### {project['name']}")
                if project.get("period"):
                    st.caption(project["period"])
                st.markdown(project.get("summary", ""))
                if project.get("link"):
                    st.link_button("View →", project["link"], use_container_width=True)

# ---- TAB: PLAYGROUND ----
with tab_playground:
    st.markdown("### Interactive RAG Demonstrations")
    st.markdown(
        f"All demos run against the same {len(CORPUS)}-chunk sample corpus the live API seeds for "
        "`/seed_demo` — a fictional platform called **Helios** with services, on-call escalation, and "
        "error codes. Nothing here calls a network endpoint; retrieval and scoring run in the page itself, "
        "so results are instant and reproducible."
    )

    pg_spec, pg_chat, pg_prompt, pg_format = st.tabs(
        ["🔍 Spec Inspector", "💬 RAG Chat", "📊 Prompt Evaluator", "🔄 Format Converter"]
    )

    # --- SPEC INSPECTOR: generic dev response vs Ashish's response, for the same query ---
    with pg_spec:
        st.markdown("### The Same Response, Two Ways")
        st.markdown(
            "Most API docs stop at the status code. Here's the difference between a response "
            "documented the ordinary way, and one documented so the *next engineer* — human or "
            "agent — knows what to do with it."
        )

        sample_queries = {
            "Who owns checkout-api?": {
                "endpoint": "POST /retrieve",
                "request": '{"query": "Who owns checkout-api?", "strategy": "graph"}',
                "raw_response": '{"results": [{"score": 0.94, "text": "checkout-api owned by Team Aurora"}], "status": 200}',
                "ashish_response": (
                    "**200 OK — but read what that means here.** The graph strategy walked "
                    "checkout-api → owned_by → Team Aurora in one hop, score 0.94 (high confidence, "
                    "direct relationship, not inferred). If this had returned **200 with an empty "
                    "results list**, that would mean the entity 'checkout-api' isn't in the graph yet — "
                    "not that the answer is 'no owner'. Empty ≠ negative; empty means *ask a different "
                    "strategy or check ingestion*."
                ),
            },
            "What triggers ERR-7741?": {
                "endpoint": "POST /retrieve",
                "request": '{"query": "What triggers ERR-7741?", "strategy": "lexical"}',
                "raw_response": '{"results": [{"score": 0.88, "text": "payments-gateway emits ERR-7741..."}], "status": 200}',
                "ashish_response": (
                    "**200 OK, lexical strategy, score 0.88.** This won on exact-token match — "
                    "'ERR-7741' is a rare, specific string, so BM25 found it directly. If you'd asked "
                    "the *semantic* version of this question ('why do checkout payments fail with a "
                    "soft decline'), lexical would likely score near zero here because there's no token "
                    "overlap — that's the case for trying vector next, not assuming the answer doesn't exist."
                ),
            },
            "How do I download the eval report?": {
                "endpoint": "GET /evaluate/report",
                "request": '{"format": "csv"}',
                "raw_response": '{"status": 200, "content_type": "text/csv"}',
                "ashish_response": (
                    "**200 with `content_type: text/csv` means the browser will download a file, "
                    "not render JSON.** If your client library shows you `200` and then errors trying "
                    "to `.json()` it, that's expected — check `content_type` before you parse. A 200 "
                    "isn't one thing; what you do next depends on what's actually in the body."
                ),
            },
        }

        picked = st.selectbox("Pick a sample query:", list(sample_queries.keys()))
        spec = sample_queries[picked]

        st.markdown(f"**{spec['endpoint']}**")
        st.code(spec["request"], language="json")

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### What most docs give you")
            st.code(spec["raw_response"], language="json")
            st.caption("Technically correct. Tells you nothing about what to do next.")
        with col2:
            st.markdown("#### What I write instead")
            st.markdown(f"<div class='card'>{spec['ashish_response']}</div>", unsafe_allow_html=True)

    # --- RAG CHAT: real retrieval + real synthesized answer ---
    with pg_chat:
        st.markdown("### Ask the Helios Corpus")
        st.markdown("Try: *Who owns checkout-api?* · *What triggers ERR-7741?* · *Who do I escalate a payments outage to?*")

        query = st.text_input("Your question:", value="Who owns checkout-api?", key="chat_query")

        if query.strip():
            strategies = ["lexical", "vector", "graph", "hybrid"]
            results = {s: retrieve(query, s, k=3) for s in strategies}

            # Generation is shared across strategies — same architecture as the live backend.
            best_sources = results["hybrid"] or results["graph"] or results["vector"] or results["lexical"]
            answer = synthesize_answer(query, best_sources)

            st.markdown("#### Answer")
            st.markdown(f"<div class='answer-box'>{answer}</div>", unsafe_allow_html=True)
            if best_sources:
                with st.expander("Cited sources"):
                    for i, src in enumerate(best_sources, 1):
                        st.caption(f"[{i}] {src['doc']}: {src['text']}")
            else:
                st.info("No chunk in the corpus overlaps with this query — try one of the suggestions above.")

            st.markdown("---")
            st.markdown("#### Retrieval by Strategy")
            st.caption("Same generation step for all four — the only variable is what each strategy retrieves.")

            cols = st.columns(4)
            for col, strategy in zip(cols, strategies):
                with col:
                    st.markdown(f"**{strategy.capitalize()}**")
                    strat_results = results[strategy]
                    if not strat_results:
                        st.caption("No match")
                        continue
                    for r in strat_results:
                        st.metric("Score", f"{r['score']:.2f}", label_visibility="collapsed")
                        st.caption(f"{r['text'][:90]}…")
        else:
            st.info("Type a question above to run retrieval.")

    # --- PROMPT EVALUATOR: real inputs, deterministic metrics ---
    with pg_prompt:
        st.markdown("### Evaluate a Response Against Context")
        st.markdown("Edit any field below — metrics recompute from the actual text, not random noise.")

        default_context = CORPUS[10]["text"] if len(CORPUS) > 10 else (CORPUS[0]["text"] if CORPUS else "")
        default_query = "What triggers ERR-7741 and what's the first remediation step?"
        default_response = (
            "ERR-7741 is emitted by payments-gateway when the card network returns a soft decline "
            "that the retry policy has already exhausted [1]. First remediation is to confirm the "
            "network status page, then release the queued authorisation batch manually [1]."
        )

        eval_query = st.text_input("Query", value=default_query, key="eval_query")
        eval_context = st.text_area("Context (retrieved passage)", value=default_context, height=100, key="eval_context")
        eval_response = st.text_area("Response to evaluate", value=default_response, height=100, key="eval_response")

        metrics = evaluate_response(eval_response, eval_context, eval_query)

        st.markdown("#### Metrics")
        cols = st.columns(6)
        display = [
            ("Groundedness", metrics["groundedness"], "Response words found in context"),
            ("Context Relevance", metrics["context_relevance"], "Query words found in context"),
            ("Citation Coverage", metrics["citation_coverage"], "Sentences with a [n] citation"),
            ("Entity Leakage", metrics["entity_leakage"], "Entities in response not in context"),
            ("Recall (approx)", metrics["recall"], "Context terms matching the query"),
            ("Precision (approx)", metrics["precision"], "Response terms matching context+query"),
        ]
        for col, (label, value, help_text) in zip(cols, display):
            with col:
                st.metric(label, f"{value:.0%}", help=help_text)

        st.markdown("---")
        st.markdown("#### Parameters (illustrative — affect risk framing, not the metrics above)")
        col1, col2, col3 = st.columns(3)
        with col1:
            temperature = st.slider("Temperature", 0.0, 1.0, 0.0, 0.1, help="0 = deterministic. Higher = more prompt-injection surface.")
        with col2:
            recall_target = st.slider("Recall target", 50, 100, 90)
        with col3:
            precision_target = st.slider("Precision target", 50, 100, 85)

        risk_note = (
            "High temperature + low citation coverage is the classic hallucination signature — "
            "watch that combination in production." if temperature > 0.5 and metrics["citation_coverage"] < 0.5
            else "Low entity leakage + high groundedness: this response stays inside its context."
            if metrics["entity_leakage"] < 0.2 and metrics["groundedness"] > 0.6
            else "Edit the response or context above to see how the risk profile shifts."
        )
        st.info(risk_note)

    # --- FORMAT CONVERTER: real input, deterministic analysis ---
    with pg_format:
        st.markdown("### Format Conversion & Retrieval Quality")
        st.markdown("Paste (or edit) a real snippet in the format below, choose a target strategy, and see what extraction actually finds.")

        samples = {
            "Markdown": CORPUS[0]["text"] if CORPUS else "The checkout-api is owned by Team Aurora.",
            "JSON": '{\n  "service": "checkout-api",\n  "owner": "Team Aurora",\n  "depends_on": ["identity-broker", "ledger-service"]\n}',
            "XML": (
                "<service name=\"checkout-api\">\n"
                "  <owner>Team Aurora</owner>\n"
                "  <dependsOn service=\"identity-broker\"/>\n"
                "  <dependsOn service=\"ledger-service\"/>\n"
                "</service>"
            ),
            "DITA": (
                "<topic id=\"checkout-api\">\n"
                "  <title>checkout-api</title>\n"
                "  <body>\n"
                "    <p>Owned by <xref keyref=\"team-aurora\"/>. Depends on identity-broker.</p>\n"
                "  </body>\n"
                "</topic>"
            ),
        }

        col1, col2 = st.columns(2)
        with col1:
            input_format = st.selectbox("Input format", list(samples.keys()), key="fmt_input")
        with col2:
            target_strategy = st.selectbox("Target strategy", ["Vector RAG", "Graph RAG", "Hybrid RAG"], key="fmt_target")

        content = st.text_area("Content to analyze", value=samples[input_format], height=160, key="fmt_content")

        if content.strip():
            profile = analyze_format(content, input_format)

            st.markdown("#### Extraction Result")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Entities found", profile["entities"])
            with col2:
                st.metric("Relation cues", profile["relations"])
            with col3:
                st.metric("Parsing effort", f"{profile['parsing_ms']}ms")
            with col4:
                st.metric("Est. quality", f"{profile['quality']:.0%}")

            if target_strategy == "Vector RAG" and profile["entities"] > 0:
                st.info(
                    f"Vector RAG will embed this as text and mostly discard the {profile['entities']} "
                    "structural entities — fine for semantic search, but relationships like "
                    "'depends_on' become invisible to multi-hop questions."
                )
            elif target_strategy == "Graph RAG":
                st.info(
                    f"Graph RAG extracts {profile['entities']} entities and {profile['relations']} "
                    "relationship cues from this snippet — the more structured the input "
                    "(DITA/XML > JSON > Markdown), the less inference the extractor has to guess at."
                )
            else:
                st.info(
                    f"Hybrid RAG keeps both: {profile['entities']} entities for graph traversal, "
                    "plus the full text embedded for semantic fallback when the graph has no path."
                )
        else:
            st.info("Paste some content above to see extraction results.")

# ============================================================================
# FOOTER
# ============================================================================
st.markdown("---")
col1, col2, col3 = st.columns([1, 2, 1])

with col1:
    st.markdown("### Get in Touch")
    st.markdown(f"[📧 Email](mailto:{PROFILE.get('email', 'ashishpathak1005@gmail.com')})")
    st.markdown(f"[📅 Book 30 min]({PROFILE.get('calendly_url') or CALENDLY})")

with col3:
    st.markdown("### Elsewhere")
    if PROFILE.get("github_url"):
        st.markdown(f"[GitHub]({PROFILE['github_url']})")
    if PROFILE.get("linkedin_url"):
        st.markdown(f"[LinkedIn]({PROFILE['linkedin_url']})")

st.markdown(
    "<div style='text-align: center; opacity: 0.4; font-size: 0.85rem; margin-top: 20px;'>"
    "Built with Streamlit | Dark theme"
    "</div>",
    unsafe_allow_html=True,
)
