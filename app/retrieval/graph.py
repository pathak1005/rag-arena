"""Graph RAG: extraction -> entity resolution -> multi-hop traversal -> CHUNKS.

The critical design choice: traversal returns chunk_ids, not raw triples. The graph
is an *index over the existing chunks*, so the generation stage is byte-identical to
the vector and lexical pipelines. That is what makes the arena a fair comparison,
and it is also what makes migrating an existing vector RAG cheap (see README).

Entity resolution gets more code than extraction on purpose. The usual failure mode
of graph RAG is not bad triples, it is 1,400 isolated nodes because "Team Meridian",
"team meridian" and "Meridian" never merged. n_components in the snapshot is the
canary for exactly that.
"""
from __future__ import annotations

import logging
import math
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field

import networkx as nx

from app.models import GraphEdge, GraphNode, GraphSnapshot, RetrievedSource

log = logging.getLogger("rag.graph")

# Per-hop score decay. Tuned on the gold set: at 0.62 a 3-hop answer scored below
# an incidental 0-hop mention, which defeats the point of traversal. At 0.85 the
# chain survives far enough for relevance to decide the ordering.
HOP_DECAY = 0.85

# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------
# Rule-based relation patterns. Deliberately explicit: on structured engineering
# docs these beat dependency parsing, and unlike an LLM they cost nothing and are
# reproducible. See README for the LLM-extraction upgrade path on prose corpora.
RELATION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("OWNED_BY", re.compile(r"(?P<s>[\w\-. ]{2,60}?)\s+is\s+owned\s+(?:and\s+operated\s+)?by\s+(?P<o>[\w\-. ]{2,60})", re.I)),
    ("OWNED_BY", re.compile(r"(?P<o>[\w\-. ]{2,60}?)\s+owns\s+(?:the\s+)?(?P<s>[\w\-. ]{2,60})", re.I)),
    ("DEPENDS_ON", re.compile(r"(?P<s>[\w\-. ]{2,60}?)\s+(?:depends\s+on|calls\s+into|is\s+backed\s+by|reads\s+from|writes\s+to)\s+(?P<o>[\w\-. ]{2,60})", re.I)),
    ("ESCALATES_TO", re.compile(r"(?P<s>[\w\-. ]{2,60}?)\s+escalat(?:es|ion)\s+(?:path\s+)?(?:to|is)\s+(?P<o>[\w\-. ]{2,60})", re.I)),
    ("PAGED_VIA", re.compile(r"(?P<s>[\w\-. ]{2,60}?)\s+is\s+paged\s+(?:via|through|in)\s+(?P<o>[\w\-.#@ ]{2,60})", re.I)),
    ("MAINTAINED_BY", re.compile(r"(?P<s>[\w\-. ]{2,60}?)\s+is\s+maintained\s+by\s+(?P<o>[\w\-. ]{2,60})", re.I)),
    ("EMITS", re.compile(r"(?P<s>[\w\-. ]{2,60}?)\s+(?:emits|raises|returns|throws)\s+(?P<o>ERR-\d+|[A-Z][A-Z0-9_\-]{3,30})", re.I)),
    ("RUNS_ON", re.compile(r"(?P<s>[\w\-. ]{2,60}?)\s+runs\s+on\s+(?P<o>[\w\-. ]{2,60})", re.I)),
    ("MEMBER_OF", re.compile(r"(?P<s>[\w\-. ]{2,60}?)\s+(?:leads|is\s+the\s+lead\s+for|is\s+on)\s+(?P<o>[\w\-. ]{2,60})", re.I)),
    ("GOVERNED_BY", re.compile(r"(?P<s>[\w\-. ]{2,60}?)\s+(?:is\s+governed\s+by|must\s+comply\s+with|follows)\s+(?P<o>[\w\-. ]{2,60})", re.I)),
]

# Surface forms that look like entities in engineering docs.
ENTITY_HINTS = [
    re.compile(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+){1,3}\b"),   # kebab-case service names
    re.compile(r"\bTeam\s+[A-Z][a-zA-Z]+\b"),                # Team Meridian
    re.compile(r"\bERR-\d{3,5}\b"),                          # error codes
    re.compile(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b"),            # Person Names
    re.compile(r"#[a-z0-9\-]{3,30}\b"),                      # slack channels
]

_NOISE_PREFIX = re.compile(
    r"^(?:the|a|an|this|that|its|their|our|all|any|each|which|who|when|and|or|but|"
    r"service|system|note|however|therefore|because|if|for)\s+",
    re.I,
)
_TRAILING = re.compile(r"[\s,.;:]+$")

# A captured span like "payments-gateway for authorisation of every order" is one
# entity followed by a subordinate clause. Cutting at the first connector keeps the
# entity and discards the clause. Without this the graph fills with unmergeable
# pseudo-entities and the component count explodes - the single biggest quality
# lever in the whole extractor.
_PHRASE_BOUNDARY = re.compile(
    r"\s+(?:for|during|with|that|which|because|before|after|so|when|rather|than|"
    r"while|until|unless|through|from|into|about|as|and|or|but|also|only|per|"
    r"within|across|via|using|based|whose|where|if|then|plus)\b.*$",
    re.I,
)
_LEADING_ARTICLE = re.compile(r"^(?:the|a|an|its|their|our|all|every|each)\s+", re.I)

STOP_ENTITIES = {
    "it", "they", "this", "that", "the service", "the team", "the system",
    "note", "example", "see also", "on call", "oncall",
}


def _clean_surface(raw: str) -> str:
    s = _TRAILING.sub("", raw.strip())
    prev = None
    while prev != s:
        prev = s
        s = _NOISE_PREFIX.sub("", s).strip()
    s = _PHRASE_BOUNDARY.sub("", s).strip()
    s = _LEADING_ARTICLE.sub("", s).strip()
    s = _TRAILING.sub("", s)
    # Entities are short. Anything past four words is a clause that slipped through.
    words = s.split()
    if len(words) > 4:
        s = " ".join(words[:4])
    return s.strip()


def normalize_key(surface: str) -> str:
    """Canonicalisation key. Step 1 of the entity-resolution ladder."""
    s = surface.lower().strip()
    s = re.sub(r"[^\w\s\-#]", " ", s)
    s = re.sub(r"\b(?:inc|llc|ltd|corp|corporation|company|the)\b", " ", s)
    s = re.sub(r"\s+(?:service|svc|system)$", " ", s)
    s = re.sub(r"[\s_]+", " ", s).strip()
    return s


def guess_type(surface: str) -> str:
    s = surface.strip()
    if s.lower().startswith("team "):
        return "Team"
    if s.startswith("#"):
        return "Channel"
    if re.fullmatch(r"ERR-\d+", s, re.I):
        return "ErrorCode"
    if "-" in s and s.islower():
        return "Service"
    if re.fullmatch(r"[A-Z][a-z]+\s+[A-Z][a-z]+", s):
        return "Person"
    if re.fullmatch(r"[A-Z][A-Z0-9_\-]{3,}", s):
        return "Policy"
    return "Concept"


@dataclass
class Triple:
    subject: str
    relation: str
    obj: str
    chunk_id: str
    evidence: str
    confidence: float = 0.8


def extract_triples(chunk_id: str, text: str) -> list[Triple]:
    triples: list[Triple] = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
        sentence = sentence.strip()
        if len(sentence) < 8:
            continue
        for relation, pattern in RELATION_PATTERNS:
            for m in pattern.finditer(sentence):
                subj = _clean_surface(m.group("s"))
                obj = _clean_surface(m.group("o"))
                if not subj or not obj:
                    continue
                if normalize_key(subj) in STOP_ENTITIES or normalize_key(obj) in STOP_ENTITIES:
                    continue
                if len(subj) < 2 or len(obj) < 2 or normalize_key(subj) == normalize_key(obj):
                    continue
                triples.append(
                    Triple(subj, relation, obj, chunk_id, sentence[:240], confidence=0.85)
                )
    return triples


def extract_mentions(text: str) -> set[str]:
    """Entity surface forms present in a chunk, for MENTIONED_IN adjacency."""
    out: set[str] = set()
    for pattern in ENTITY_HINTS:
        for m in pattern.finditer(text):
            surface = _clean_surface(m.group(0))
            if surface and normalize_key(surface) not in STOP_ENTITIES and len(surface) > 2:
                out.add(surface)
    return out


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------
@dataclass
class Entity:
    id: str
    label: str
    type: str
    aliases: set[str] = field(default_factory=set)
    chunk_ids: set[str] = field(default_factory=set)
    mentions: int = 0


class GraphStore:
    """NetworkX-backed. Swap for Neo4j by reimplementing this class only."""

    def __init__(self) -> None:
        self.g = nx.MultiDiGraph()
        self.entities: dict[str, Entity] = {}
        self.alias_index: dict[str, str] = {}                       # normalised alias -> entity id
        self.token_index: dict[str, set[str]] = defaultdict(set)    # token -> entity ids
        self.chunk_entities: dict[str, set[str]] = defaultdict(set) # chunk -> entity ids
        self.stats = {"entities_added": 0, "relations_added": 0, "entities_merged": 0}

    def reset_delta(self) -> None:
        self.stats = {"entities_added": 0, "relations_added": 0, "entities_merged": 0}

    # -- resolution ladder -------------------------------------------------
    def resolve(self, surface: str) -> str:
        """Ladder steps 1-3: normalise, alias lookup, then cheap variant matching."""
        key = normalize_key(surface)
        if not key:
            key = surface.lower().strip()

        existing = self.alias_index.get(key)
        if existing:
            ent = self.entities[existing]
            if surface not in ent.aliases:
                ent.aliases.add(surface)
                self.stats["entities_merged"] += 1
            return existing

        for cand_key, ent_id in list(self.alias_index.items()):
            if _is_variant(key, cand_key):
                self.alias_index[key] = ent_id
                self.entities[ent_id].aliases.add(surface)
                self.stats["entities_merged"] += 1
                for tok in key.split():
                    self.token_index[tok].add(ent_id)
                return ent_id

        ent_id = "e::" + key.replace(" ", "_")
        etype = guess_type(surface)
        self.entities[ent_id] = Entity(id=ent_id, label=surface.strip(), type=etype, aliases={surface})
        self.alias_index[key] = ent_id
        for tok in key.split():
            self.token_index[tok].add(ent_id)
        self.g.add_node(ent_id, label=surface.strip(), type=etype)
        self.stats["entities_added"] += 1
        return ent_id

    def add_mention(self, surface: str, chunk_id: str) -> str:
        ent_id = self.resolve(surface)
        ent = self.entities[ent_id]
        ent.chunk_ids.add(chunk_id)   # this set IS the MENTIONED_IN edge list
        ent.mentions += 1
        self.chunk_entities[chunk_id].add(ent_id)
        return ent_id

    def add_triple(self, t: Triple) -> None:
        s_id = self.add_mention(t.subject, t.chunk_id)
        o_id = self.add_mention(t.obj, t.chunk_id)
        if s_id == o_id:
            return
        for _, tgt, data in self.g.out_edges(s_id, data=True):
            if data.get("relation") == t.relation and tgt == o_id:
                data["chunk_ids"].add(t.chunk_id)
                return
        self.g.add_edge(
            s_id,
            o_id,
            relation=t.relation,
            confidence=t.confidence,
            chunk_ids={t.chunk_id},
            evidence=t.evidence,
        )
        self.stats["relations_added"] += 1

    # -- query-time entity linking ----------------------------------------
    def link_query(self, question: str) -> list[tuple[str, float]]:
        """Map a question onto seed entities. Returns (entity_id, strength)."""
        q_norm = normalize_key(question)
        q_tokens = {t for t in q_norm.split() if len(t) > 2}
        scored: dict[str, float] = {}

        for key, ent_id in self.alias_index.items():
            if not key or len(key) < 3:
                continue
            if re.search(r"(?<!\w)" + re.escape(key) + r"(?!\w)", q_norm):
                scored[ent_id] = max(scored.get(ent_id, 0.0), 1.0)

        for tok in q_tokens:
            for ent_id in self.token_index.get(tok, ()):
                ent_key = normalize_key(self.entities[ent_id].label)
                parts = set(ent_key.split())
                if not parts:
                    continue
                overlap = len(q_tokens & parts) / len(parts)
                if overlap >= 0.5:
                    scored[ent_id] = max(scored.get(ent_id, 0.0), 0.55 * overlap + 0.2)

        return sorted(scored.items(), key=lambda kv: -kv[1])[:6]

    # -- traversal ---------------------------------------------------------
    def traverse(self, seeds: list[tuple[str, float]], max_hops: int) -> dict[str, dict]:
        """BFS with hop decay. Returns chunk_id -> {score, path, hops}."""
        chunk_scores: dict[str, dict] = {}
        for seed_id, strength in seeds:
            if seed_id not in self.entities:
                continue
            visited: dict[str, int] = {seed_id: 0}
            queue: deque[tuple[str, int, list[str]]] = deque(
                [(seed_id, 0, [self.entities[seed_id].label])]
            )
            while queue:
                node, hop, path = queue.popleft()
                decay = HOP_DECAY ** hop
                ent = self.entities.get(node)
                if ent:
                    for cid in ent.chunk_ids:
                        # Normalise by how many entities the chunk mentions. A document
                        # header naming twenty services is reachable from everywhere but
                        # is *about* nothing; without this it outranks the specific chunk
                        # that actually answers the question. Same idea as TF saturation.
                        saturation = max(1.0, len(self.chunk_entities.get(cid, ())) ** 0.5)
                        contrib = strength * decay / saturation
                        cur = chunk_scores.get(cid)
                        if cur is None:
                            chunk_scores[cid] = {"score": contrib, "path": list(path), "hops": hop}
                        elif contrib > cur["score"]:
                            cur["score"] = contrib + cur["score"] * 0.25
                            cur["path"] = list(path)
                            cur["hops"] = hop
                        else:
                            cur["score"] += contrib * 0.25   # corroboration bonus
                if hop >= max_hops:
                    continue
                for _, nbr, data in self.g.out_edges(node, data=True):
                    if nbr in visited and visited[nbr] <= hop + 1:
                        continue
                    visited[nbr] = hop + 1
                    label = self.entities[nbr].label if nbr in self.entities else nbr
                    queue.append((nbr, hop + 1, path + ["-[" + data["relation"] + "]->", label]))
                for pred, _, data in self.g.in_edges(node, data=True):
                    if pred in visited and visited[pred] <= hop + 1:
                        continue
                    visited[pred] = hop + 1
                    label = self.entities[pred].label if pred in self.entities else pred
                    queue.append((pred, hop + 1, path + ["<-[" + data["relation"] + "]-", label]))
        return chunk_scores

    # -- introspection -----------------------------------------------------
    def snapshot(self, limit: int = 250) -> GraphSnapshot:
        top = sorted(self.entities.values(), key=lambda x: -x.mentions)[:limit]
        nodes = [GraphNode(id=e.id, label=e.label, type=e.type, mentions=e.mentions) for e in top]
        keep = {n.id for n in nodes}
        edges = [
            GraphEdge(
                source=u,
                target=v,
                relation=d["relation"],
                confidence=float(d.get("confidence", 0.8)),
                chunk_ids=sorted(d.get("chunk_ids", [])),
            )
            for u, v, d in self.g.edges(data=True)
            if u in keep and v in keep
        ]
        if self.g.number_of_nodes():
            components = list(nx.connected_components(self.g.to_undirected()))
        else:
            components = []
        largest = max((len(c) for c in components), default=0)
        total = max(1, self.g.number_of_nodes())
        return GraphSnapshot(
            nodes=nodes,
            edges=edges,
            n_entities=len(self.entities),
            n_relations=self.g.number_of_edges(),
            n_components=len(components),
            largest_component_pct=round(100.0 * largest / total, 1),
        )


def _is_variant(a: str, b: str) -> bool:
    """Conservative near-duplicate test. Wrong merges are worse than missed merges."""
    if not a or not b or abs(len(a) - len(b)) > 4 or min(len(a), len(b)) < 4:
        return False
    if a == b + "s" or b == a + "s":
        return True
    a_t, b_t = a.split(), b.split()
    if len(a_t) > 1 and len(b_t) > 1 and a_t[-1] == b_t[-1] and a_t[0][:1] == b_t[0][:1]:
        return a_t[0].startswith(b_t[0]) or b_t[0].startswith(a_t[0])
    return False


_REL_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "are", "for", "on", "with",
    "as", "by", "at", "be", "this", "that", "it", "from", "we", "our", "you", "your",
    "how", "what", "which", "who", "when", "do", "does", "can", "should", "if", "i",
}


def _stem(word: str) -> str:
    """Suffix stripping, not linguistics. Without it "escalate" in the question fails
    to match "escalates" in the chunk, and the multi-hop answer is scored as
    irrelevant - a silent, and very common, retrieval bug."""
    for suffix in ("ations", "ation", "ing", "ies", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _terms(text: str) -> set[str]:
    return {
        _stem(w) for w in re.findall(r"[a-z][a-z0-9\-]{2,}", text.lower())
        if w not in _REL_STOP
    }


def _idf_table(store, chunks: dict) -> dict[str, float]:
    """IDF over the chunk corpus, cached until the corpus size changes.

    Unweighted term overlap treats "escalate" and "problem" as equally informative,
    which is wrong: the rare term is the one that identifies the answer. This is the
    same weighting BM25 applies, reused here so the graph lane ranks by how
    *diagnostic* a shared term is rather than how many were shared.
    """
    cached = getattr(store, "_idf_cache", None)
    if cached is not None and cached[0] == len(chunks):
        return cached[1]

    n_docs = max(1, len(chunks))
    df: dict[str, int] = {}
    for chunk in chunks.values():
        for term in _terms(chunk.text):
            df[term] = df.get(term, 0) + 1
    idf = {t: math.log(1.0 + (n_docs - c + 0.5) / (c + 0.5)) for t, c in df.items()}
    store._idf_cache = (len(chunks), idf)
    return idf


def retrieve_graph(
    store: GraphStore,
    question: str,
    chunks: dict,
    top_k: int,
    max_hops: int,
) -> tuple[list[RetrievedSource], dict]:
    """Two-factor ranking: the graph decides what is REACHABLE, terms decide what is
    RELEVANT among the reachable set.

    Reachability alone is not enough. Hop decay makes seed-adjacent chunks dominate,
    so a 3-hop answer ("...escalates to Priya Raman") is buried under 0-hop chunks
    that merely mention the seed entity. Multiplying by query-term relevance keeps the
    graph's job - candidate generation across document boundaries, which flat
    retrieval cannot do - while letting the question decide the ordering within it.

    Both factors are reported separately in `why` so the ranking stays inspectable
    rather than becoming an opaque blend.
    """
    seeds = store.link_query(question)
    if not seeds:
        return [], {"seeds": [], "reason": "no entity in the query matched the graph"}

    reach = store.traverse(seeds, max_hops)
    idf = _idf_table(store, chunks)

    # Query terms absent from the corpus ("problem", "because") can never be matched
    # by any chunk, so counting them in the denominator only flattens the scores.
    q_terms = {t for t in _terms(question) if t in idf}
    q_mass = sum(idf[t] for t in q_terms) or 1.0

    combined: list[tuple[str, dict, float, float]] = []
    for chunk_id, info in reach.items():
        chunk = chunks.get(chunk_id)
        if chunk is None:
            continue
        matched = q_terms & _terms(chunk.text)
        relevance = sum(idf[t] for t in matched) / q_mass
        reachability = float(info["score"])
        # Floor at 0.10 so a reachable-but-lexically-dissimilar chunk is demoted,
        # never eliminated - that case is exactly where graph beats the other lanes.
        final = reachability * (0.10 + 0.90 * relevance)
        combined.append((chunk_id, info, final, relevance))

    combined.sort(key=lambda row: -row[2])
    ranked = combined[:top_k]

    sources: list[RetrievedSource] = []
    for rank, (chunk_id, info, final, relevance) in enumerate(ranked, start=1):
        chunk = chunks[chunk_id]
        path_str = " ".join(info["path"])
        sources.append(
            RetrievedSource(
                chunk_id=chunk_id,
                doc_id=chunk.doc_id,
                doc_title=chunk.doc_title,
                rank=rank,
                score=round(float(final), 4),
                text=chunk.text,
                why=(
                    "Reached in " + str(info["hops"]) + " hop(s): " + path_str
                    + "  |  reachability " + format(info["score"], ".3f")
                    + " x relevance " + format(relevance, ".3f")
                ),
                graph_path=info["path"],
            )
        )

    trace = {
        "seeds": [
            {"entity": store.entities[e].label, "strength": round(s, 3)} for e, s in seeds
        ],
        "max_hops": max_hops,
        "chunks_reached": len(reach),
        "ranking": "reachability/sqrt(entities in chunk) x (0.10 + 0.90 * idf-weighted relevance)",
        "max_hops_used": max((info["hops"] for _, info, _, _ in ranked), default=0),
        "paths": [s.graph_path for s in sources],
    }
    return sources, trace
