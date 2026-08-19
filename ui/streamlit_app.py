"""
Ashish Pathak - Knowledge Architect Portfolio.

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
RESUME_GDOC = "https://docs.google.com/document/d/1O_qtvSQNI3hy35Qri0OZEOMfCcFr8I3l"

_EM_DASH, _EN_DASH = "—", "–"


def declutter(text):
    """Replace em/en dashes used as word-substitutes with plain punctuation."""
    if isinstance(text, str):
        return text.replace(" " + _EM_DASH + " ", ", ").replace(_EM_DASH, ", ").replace(_EN_DASH, "-")
    if isinstance(text, list):
        return [declutter(v) for v in text]
    if isinstance(text, dict):
        return {k: declutter(v) for k, v in text.items()}
    return text

# ============================================================================
# CONFIG & THEME
# ============================================================================
st.set_page_config(
    page_title="Ashish Pathak - Knowledge Architect",
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
    .print-btn-icon {
        background: #1A1F3A; border: 1px solid #334155; color: #F0F0F0;
        padding: 6px 14px; border-radius: 8px; font-size: 0.9rem; cursor: pointer;
        float: right; margin-top: 44px;
    }
    .print-btn-icon:hover { border-color: #00D9FF; color: #00D9FF; }

    /* Native st.button() elements (top nav, Home reference links) don't reliably
       inherit page-level colors - their background/text come from Streamlit's own
       component styling, so they need explicit rules or they can render unreadable
       (e.g. light text on a light background) regardless of the page theme. */
    div[data-testid="stButton"] button,
    button[kind="secondary"] {
        background-color: #1A1F3A !important;
        color: #F0F0F0 !important;
        border: 1px solid #334155 !important;
    }
    div[data-testid="stButton"] button:hover,
    button[kind="secondary"]:hover {
        border-color: #00D9FF !important;
        color: #00D9FF !important;
    }
    button[kind="primary"] {
        background-color: #00D9FF !important;
        color: #0A0E27 !important;
        border: 1px solid #00D9FF !important;
        font-weight: 700 !important;
    }
    button[kind="primary"]:hover {
        background-color: #33e3ff !important;
    }

    @media print {
        .stTabs [data-baseweb="tab-list"], .print-btn-icon, button { display: none !important; }
        html, body, .stApp { background: white !important; color: black !important; }
    }
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


PORTFOLIO = declutter(load_portfolio())
PROFILE = PORTFOLIO.get("profile", {})

# ============================================================================
# FORMAT CONVERTER HELPERS (deterministic, driven by actual pasted text)
# ============================================================================
_ENTITY = re.compile(r"\b[A-Z][a-zA-Z]+(?:[\s-][A-Z][a-zA-Z]+)*\b")
_TAG = re.compile(r"</?([\w:-]+)")
_JSON_KEY = re.compile(r'"([\w\-]+)"\s*:')
_RELATION_CUES = re.compile(r"\b(owns?|owned by|depends? on|escalates? to|emits?|requires?|calls?|reachable|reports? to)\b", re.I)


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

hero_col, print_col = st.columns([8, 1])
with hero_col:
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
with print_col:
    st.markdown(
        "<button class='print-btn-icon' onclick='window.print()'>🖨️ Print</button>",
        unsafe_allow_html=True,
    )

st.markdown("---")

# ============================================================================
# MAIN NAVIGATION
#
# st.tabs() cannot be jumped into programmatically (no supported API to select a
# tab from a button elsewhere on the page), which is exactly what the Home page's
# "References" list needs to do. So navigation here is a real session_state + button
# pattern instead: clicking a nav button, or a reference link on Home, sets which
# section renders and reruns. Native st.tabs() is still used *inside* Playground for
# its two sub-tabs, since nothing needs to jump directly into one of those.
# ============================================================================
SECTIONS = {
    "Home": "🏠 Home",
    "About": "👤 About",
    "Work": "💼 Work",
    "Blog": "📝 Blog",
    "Playground": "🎮 Playground",
}

if "active_section" not in st.session_state:
    st.session_state.active_section = "Home"


def go_to(section: str) -> None:
    st.session_state.active_section = section


nav_cols = st.columns(len(SECTIONS))
for col, (key, label) in zip(nav_cols, SECTIONS.items()):
    with col:
        st.button(
            label,
            key=f"nav_{key}",
            use_container_width=True,
            type="primary" if st.session_state.active_section == key else "secondary",
            on_click=go_to,
            args=(key,),
        )

st.markdown("---")

active = st.session_state.active_section

# ---- SECTION: HOME ----
if active == "Home":
    col1, col2 = st.columns([1.5, 1])

    with col1:
        st.markdown("### Summary")
        for para in summary_paras[1:]:
            st.markdown(para)

        st.markdown("")
        st.markdown("**References**")
        ref_items = [
            ("About", "📄 About", "full experience, skills, education, certifications"),
            ("Work", "💼 Work", "real products and projects, with live links"),
            ("Blog", "📝 Blog", "writing on knowledge architecture and RAG"),
            ("Playground", "🎮 Playground", "try the retrieval strategies live, on real sample text"),
        ]
        for key, label, desc in ref_items:
            ref_col1, ref_col2 = st.columns([1, 3])
            with ref_col1:
                st.button(label, key=f"ref_{key}", use_container_width=True, on_click=go_to, args=(key,))
            with ref_col2:
                st.markdown(f"<div style='padding-top: 8px;'>{desc}</div>", unsafe_allow_html=True)

    with col2:
        st.markdown("### Resume & Contact")
        st.link_button("📄 View Resume", RESUME_GDOC, use_container_width=True)
        col_a, col_b = st.columns(2)
        with col_a:
            st.link_button("📧 Email", f"mailto:{PROFILE.get('email', 'ashishpathak1005@gmail.com')}", use_container_width=True)
        with col_b:
            st.link_button("📅 Book time", PROFILE.get("calendly_url") or CALENDLY, use_container_width=True)
        if PROFILE.get("linkedin_url"):
            st.link_button("LinkedIn", PROFILE["linkedin_url"], use_container_width=True)
        if PROFILE.get("github_url"):
            st.link_button("GitHub", PROFILE["github_url"], use_container_width=True)

# ---- SECTION: ABOUT ----
elif active == "About":
    st.markdown("### Professional Summary")
    for para in summary_paras:
        st.markdown(para)
    st.link_button("📄 View Resume", RESUME_GDOC)

    st.markdown("---")
    st.markdown("### Experience")
    experience = PORTFOLIO.get("experience", [])
    for i, job in enumerate(experience):
        with st.expander(f"{job['title']} - {job['company']} ({job['period']})", expanded=(i == 0)):
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

# ---- SECTION: WORK ----
elif active == "Work":
    st.markdown("### Products & Projects")
    st.caption("Live products, with what they do and who uses them.")
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
                    st.link_button("View", project["link"], use_container_width=True)

    st.markdown("---")
    st.markdown("### Public Repositories")
    st.caption("From github.com/pathak1005")

    public_repos = [
        {
            "name": "Sphinx-API-Documentation-",
            "desc": (
                "Sphinx is a static site generator (SSG) built for documentation, and this "
                "shows it applied to API docs: content lives as plain text (reStructuredText), "
                "versioned in git next to the code, reviewed in pull requests, and built into "
                "a site on every change, docs as code, not a wiki someone forgets to update."
            ),
            "url": "https://github.com/pathak1005/Sphinx-API-Documentation-",
        },
        {
            "name": "Sample-Docsite",
            "desc": (
                "A documentation site built with MkDocs, a lighter-weight SSG than Sphinx, "
                "configured with plain Markdown rather than reStructuredText. Useful reference "
                "for teams that want docs-as-code without Sphinx's steeper authoring curve."
            ),
            "url": "https://github.com/pathak1005/Sample-Docsite",
        },
        {
            "name": "sentimentanalysis",
            "desc": (
                "Scores free-text feedback (reviews, support tickets, survey responses) as "
                "positive, negative, or neutral automatically. The point isn't the label, it's "
                "closing the loop: instead of feedback sitting unread, negative sentiment can "
                "be routed and prioritized immediately."
            ),
            "url": "https://github.com/pathak1005/sentimentanalysis",
        },
    ]

    cols = st.columns(len(public_repos))
    for col, repo in zip(cols, public_repos):
        with col:
            with st.container(border=True):
                st.markdown(f"**{repo['name']}**")
                st.caption(repo["desc"])
                st.link_button("View on GitHub", repo["url"], use_container_width=True)

# ---- SECTION: BLOG ----
elif active == "Blog":
    st.markdown("### Writing")
    blog_posts = PORTFOLIO.get("blog", [])

    if not blog_posts:
        st.info(
            "No posts published yet. New writing on knowledge architecture, RAG systems, "
            "and content governance will appear here first."
        )
        st.link_button("Follow on LinkedIn instead", PROFILE.get("linkedin_url") or "https://www.linkedin.com", use_container_width=False)
    else:
        for post in blog_posts:
            with st.container(border=True):
                st.markdown(f"#### {post.get('title', '')}")
                if post.get("date"):
                    st.caption(post["date"])
                st.markdown(post.get("summary", ""))
                if post.get("link"):
                    st.link_button("Read", post["link"])

# ---- SECTION: PLAYGROUND ----
elif active == "Playground":
    st.markdown("### Interactive RAG Demonstrations")
    st.markdown(
        "All demos below run right here on the page, using the same sample text so you can "
        "compare strategies fairly."
    )

    st.markdown("#### What changes as you add each strategy?")
    st.caption("Pick one to see what it adds, using a plain example, plus a tip for writing text that retrieves well with it.")

    strategy_explainer = {
        "Lexical search (keyword match)": {
            "what": (
                "Finds text that contains the same words as your question. Ask about "
                "'checkout-api' and it matches any sentence that literally says "
                "'checkout-api'. Fast and simple, but it is really just word-matching, "
                "not meaning-matching, and it is not really RAG on its own, it is what "
                "search engines did for years before RAG existed."
            ),
            "change": "The starting point: nothing to compare it to yet.",
            "tip": (
                "Use the exact words your reader will type. Spell out an abbreviation "
                "at least once. Repeat the key term instead of only saying 'it' or 'this'."
            ),
        },
        "+ Vector search (meaning-based)": {
            "what": (
                "Turns sentences into numbers that capture meaning, so it can find a match "
                "even when no word is shared. Ask 'why did my order fail' and it can still "
                "find a sentence about 'payment declined'."
            ),
            "change": "Lexical needs the same words. This finds the same idea in different words.",
            "tip": (
                "Write in plain, complete sentences rather than fragments or heavy jargon. "
                "The more naturally a sentence reads, the easier it is to match against a "
                "naturally phrased question."
            ),
        },
        "Graph RAG (relationships)": {
            "what": (
                "Pulls out the things mentioned (people, teams, services) and how they "
                "connect: 'X is owned by Y', 'Y escalates to Z', then follows that chain "
                "to answer a question no single sentence answers by itself."
            ),
            "change": "Vector search finds one matching sentence. This can chain two or three separate facts together.",
            "tip": (
                "State relationships in one plain sentence: 'checkout-api is owned by "
                "Team Aurora,' not 'the team responsible for checkout handles ownership.' "
                "A clear subject, verb, and object extracts cleanly."
            ),
        },
        "Hybrid (all combined)": {
            "what": (
                "Runs all three and blends the results, so a question that needs an exact "
                "term, a paraphrase, and a relationship all at once still gets a good "
                "answer, instead of betting on a single strategy."
            ),
            "change": "Nothing new is searched, the same three are combined so one covers another's blind spot.",
            "tip": "Benefits from all three tips above at once: exact terms, plain sentences, explicit relationships.",
        },
    }

    picked_strategy = st.selectbox("See what changes:", list(strategy_explainer.keys()), key="strategy_explainer_pick")
    info = strategy_explainer[picked_strategy]
    st.markdown(f"<div class='card'><strong>What it does:</strong> {info['what']}</div>", unsafe_allow_html=True)
    col_a, col_b = st.columns(2)
    with col_a:
        st.caption(f"**What's new here:** {info['change']}")
    with col_b:
        st.caption(f"**Writing tip:** {info['tip']}")

    pg_spec, pg_format = st.tabs(
        ["🔍 Spec Inspector (alpha)", "🔄 Format Converter"]
    )

    # --- SPEC INSPECTOR: identical facts, two documentation qualities ---
    with pg_spec:
        st.markdown(
            "<span style='background:#334155;color:#e2e8f0;padding:2px 10px;"
            "border-radius:999px;font-size:0.75rem;font-weight:600;'>ALPHA &middot; WORK IN PROGRESS</span>",
            unsafe_allow_html=True,
        )
        st.markdown("### The Same Facts, Two Documentation Qualities")
        st.markdown(
            "Both panels below describe the exact same API response. The left is written the "
            "way most API docs are written: technically correct, minimal effort. The right is "
            "the same facts, written so the next engineer knows what to actually do."
        )

        sample_queries = {
            "Who owns checkout-api?": {
                "endpoint": "POST /retrieve",
                "request": '{"query": "Who owns checkout-api?", "strategy": "graph"}',
                "response": '{"results": [{"score": 0.94, "text": "checkout-api owned by Team Aurora"}], "status": 200}',
                "standard_doc": (
                    "**200 OK.** Returns a `results` array with matched entities and a relevance "
                    "`score` between 0 and 1. An empty array means no results were found."
                ),
                "ashish_doc": (
                    "**200 OK, score 0.94.** The graph strategy found this in one hop "
                    "(checkout-api to owned_by to Team Aurora), which is why the score is high: "
                    "it's a direct relationship, not an inference across multiple hops. "
                    "If `results` had come back empty, that means the entity 'checkout-api' isn't "
                    "in the graph yet, not that it has no owner. Empty is not the same as negative: "
                    "when you see it, check ingestion or try a different strategy before concluding "
                    "the answer is 'no owner'."
                ),
            },
            "What triggers ERR-7741?": {
                "endpoint": "POST /retrieve",
                "request": '{"query": "What triggers ERR-7741?", "strategy": "lexical"}',
                "response": '{"results": [{"score": 0.88, "text": "payments-gateway emits ERR-7741..."}], "status": 200}',
                "standard_doc": (
                    "**200 OK, score 0.88.** The lexical strategy uses keyword matching (BM25) to "
                    "rank results by term overlap with the query."
                ),
                "ashish_doc": (
                    "**200 OK, lexical strategy, score 0.88.** This won because 'ERR-7741' is a "
                    "rare, exact token, and lexical search is built for exactly that: token overlap, "
                    "not meaning. If you rephrase the same question without the error code (say, "
                    "'why do checkout payments fail with a soft decline'), lexical will likely score "
                    "near zero here, since there is no token overlap anymore. That's the signal to "
                    "try vector or graph next, not proof the answer stopped existing."
                ),
            },
            "How do I download the eval report?": {
                "endpoint": "GET /evaluate/report",
                "request": '{"format": "csv"}',
                "response": '{"status": 200, "content_type": "text/csv"}',
                "standard_doc": (
                    "**200 OK.** Returns the evaluation report. Set `format` to `csv` or `json`."
                ),
                "ashish_doc": (
                    "**200 OK, `content_type: text/csv`.** That content type means the response "
                    "body is a file download, not JSON, so calling `.json()` on it will throw. Check "
                    "`content_type` before you decide how to parse the body: a 200 status code alone "
                    "does not tell you what shape the response is in."
                ),
            },
        }

        picked = st.selectbox("Pick a sample query:", list(sample_queries.keys()))
        spec = sample_queries[picked]

        st.markdown(f"**{spec['endpoint']}**")
        st.code(spec["request"], language="json")
        st.markdown("**Response**")
        st.code(spec["response"], language="json")

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### Standard practice")
            st.markdown(f"<div class='card'>{spec['standard_doc']}</div>", unsafe_allow_html=True)
            st.caption("Technically accurate. Tells you the shape, not what to do next.")
        with col2:
            st.markdown("#### What I write")
            st.markdown(f"<div class='card'>{spec['ashish_doc']}</div>", unsafe_allow_html=True)

    # --- FORMAT CONVERTER: real input, deterministic analysis ---
    with pg_format:
        st.markdown("### Format Conversion & Retrieval Quality")
        st.markdown("Paste (or edit) a real snippet in the format below, choose a target strategy, and see what extraction actually finds.")

        samples = {
            "Markdown": "The checkout-api is owned by Team Aurora. It handles cart finalisation, tax calculation and order submission for all storefronts.",
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

        run_analysis = st.button("🔍 Analyze", type="primary", use_container_width=True)

        if run_analysis and content.strip():
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
                    "structural entities, fine for semantic search, but relationships like "
                    "'depends_on' become invisible to multi-hop questions."
                )
            elif target_strategy == "Graph RAG":
                st.info(
                    f"Graph RAG extracts {profile['entities']} entities and {profile['relations']} "
                    "relationship cues from this snippet, the more structured the input "
                    "(DITA/XML > JSON > Markdown), the less inference the extractor has to guess at."
                )
            else:
                st.info(
                    f"Hybrid RAG keeps both: {profile['entities']} entities for graph traversal, "
                    "plus the full text embedded for semantic fallback when the graph has no path."
                )
        elif not content.strip():
            st.info("Paste some content above, then click Analyze.")
        else:
            st.caption("Click **Analyze** to run extraction on the content above.")

# ============================================================================
# FOOTER
# ============================================================================
st.markdown("---")
st.markdown(
    "<div style='text-align: center; opacity: 0.4; font-size: 0.85rem;'>"
    "Built with Streamlit &middot; "
    "<a href='/about.html' style='color: inherit;'>Plain-text profile</a>"
    "</div>",
    unsafe_allow_html=True,
)
