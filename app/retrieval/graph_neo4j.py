"""Neo4j-backed graph store - the production path, and the one to learn on.

Interface-compatible with GraphStore (NetworkX), so app/store.py does not know or
care which is active. Set GRAPH_BACKEND=neo4j to use this one.

The data model is deliberately the same one described in the README migration
playbook, because the point is that it is not a toy:

    (:Entity {id, label, type, aliases})
    (:Chunk  {id, doc_id, doc_title})
    (:Entity)-[:REL {type, confidence, chunk_ids}]->(:Entity)
    (:Entity)-[:MENTIONED_IN]->(:Chunk)

MENTIONED_IN is the bridge that turns graph structure back into retrievable text.
Traversal finds entities; MENTIONED_IN converts those entities into the chunk_ids
that the generator actually reads. Without it you have a knowledge graph, not a
retrieval system.

Open http://localhost:7474 and run the queries in LEARN.md against this schema.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict

from app.models import GraphEdge, GraphNode, GraphSnapshot
from app.retrieval.graph import HOP_DECAY, Entity, Triple, guess_type, normalize_key

log = logging.getLogger("rag.neo4j")

SCHEMA_STATEMENTS = [
    "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
    "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE",
    "CREATE INDEX entity_label IF NOT EXISTS FOR (e:Entity) ON (e.label)",
    "CREATE INDEX entity_type IF NOT EXISTS FOR (e:Entity) ON (e.type)",
]


class Neo4jGraphStore:
    """Same five operations as GraphStore, backed by Cypher instead of NetworkX."""

    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j") -> None:
        from neo4j import GraphDatabase  # imported here so the dep stays optional

        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.database = database
        self.driver.verify_connectivity()

        # Local label cache. Neo4j is the source of truth for structure; this is only
        # a lookup table so the router and UI can render labels without a round trip.
        self.entities: dict[str, Entity] = {}
        self.alias_index: dict[str, str] = {}
        self.token_index: dict[str, set[str]] = defaultdict(set)
        self.stats = {"entities_added": 0, "relations_added": 0, "entities_merged": 0}

        with self.driver.session(database=self.database) as session:
            for statement in SCHEMA_STATEMENTS:
                session.run(statement)
        self._warm_cache()
        log.info("Neo4j graph store ready at %s (%d entities cached)", uri, len(self.entities))

    # ------------------------------------------------------------------
    def close(self) -> None:
        try:
            self.driver.close()
        except Exception:  # noqa: BLE001
            pass

    def reset_delta(self) -> None:
        self.stats = {"entities_added": 0, "relations_added": 0, "entities_merged": 0}

    def _warm_cache(self) -> None:
        query = "MATCH (e:Entity) RETURN e.id AS id, e.label AS label, e.type AS type, e.aliases AS aliases, e.mentions AS mentions"
        with self.driver.session(database=self.database) as session:
            for record in session.run(query):
                ent = Entity(
                    id=record["id"],
                    label=record["label"],
                    type=record["type"] or "Concept",
                    aliases=set(record["aliases"] or []),
                    mentions=int(record["mentions"] or 0),
                )
                self.entities[ent.id] = ent
                for alias in ent.aliases | {ent.label}:
                    key = normalize_key(alias)
                    if key:
                        self.alias_index[key] = ent.id
                        for tok in key.split():
                            self.token_index[tok].add(ent.id)

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    def resolve(self, surface: str) -> str:
        key = normalize_key(surface) or surface.lower().strip()
        existing = self.alias_index.get(key)
        if existing:
            ent = self.entities[existing]
            if surface not in ent.aliases:
                ent.aliases.add(surface)
                self.stats["entities_merged"] += 1
                self._write_alias(existing, surface)
            return existing

        ent_id = "e::" + key.replace(" ", "_")
        etype = guess_type(surface)
        self.entities[ent_id] = Entity(id=ent_id, label=surface.strip(), type=etype, aliases={surface})
        self.alias_index[key] = ent_id
        for tok in key.split():
            self.token_index[tok].add(ent_id)
        self.stats["entities_added"] += 1

        with self.driver.session(database=self.database) as session:
            session.run(
                """
                MERGE (e:Entity {id: $id})
                ON CREATE SET e.label = $label, e.type = $type,
                              e.aliases = [$surface], e.mentions = 0
                """,
                id=ent_id, label=surface.strip(), type=etype, surface=surface,
            )
        return ent_id

    def _write_alias(self, ent_id: str, surface: str) -> None:
        with self.driver.session(database=self.database) as session:
            session.run(
                """
                MATCH (e:Entity {id: $id})
                SET e.aliases = CASE WHEN $surface IN coalesce(e.aliases, [])
                                     THEN e.aliases
                                     ELSE coalesce(e.aliases, []) + $surface END
                """,
                id=ent_id, surface=surface,
            )

    def register_chunk(self, chunk_id: str, doc_id: str, doc_title: str) -> None:
        with self.driver.session(database=self.database) as session:
            session.run(
                "MERGE (c:Chunk {id: $id}) SET c.doc_id = $doc_id, c.doc_title = $title",
                id=chunk_id, doc_id=doc_id, title=doc_title,
            )

    def add_mention(self, surface: str, chunk_id: str) -> str:
        ent_id = self.resolve(surface)
        self.entities[ent_id].chunk_ids.add(chunk_id)
        self.entities[ent_id].mentions += 1
        with self.driver.session(database=self.database) as session:
            session.run(
                """
                MATCH (e:Entity {id: $eid})
                MERGE (c:Chunk {id: $cid})
                MERGE (e)-[:MENTIONED_IN]->(c)
                SET e.mentions = coalesce(e.mentions, 0) + 1
                """,
                eid=ent_id, cid=chunk_id,
            )
        return ent_id

    def add_triple(self, t: Triple) -> None:
        s_id = self.add_mention(t.subject, t.chunk_id)
        o_id = self.add_mention(t.obj, t.chunk_id)
        if s_id == o_id:
            return
        with self.driver.session(database=self.database) as session:
            result = session.run(
                """
                MATCH (s:Entity {id: $sid}), (o:Entity {id: $oid})
                MERGE (s)-[r:REL {type: $rtype}]->(o)
                ON CREATE SET r.confidence = $conf, r.chunk_ids = [$cid],
                              r.evidence = $evidence, r.created = true
                ON MATCH SET  r.chunk_ids = CASE WHEN $cid IN coalesce(r.chunk_ids, [])
                                                 THEN r.chunk_ids
                                                 ELSE coalesce(r.chunk_ids, []) + $cid END,
                              r.created = false
                RETURN r.created AS created
                """,
                sid=s_id, oid=o_id, rtype=t.relation, conf=t.confidence,
                cid=t.chunk_id, evidence=t.evidence,
            )
            record = result.single()
            if record and record["created"]:
                self.stats["relations_added"] += 1

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def link_query(self, question: str) -> list[tuple[str, float]]:
        """Identical linking logic to the NetworkX store - it runs on the cache, not the DB."""
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
                parts = set(normalize_key(self.entities[ent_id].label).split())
                if not parts:
                    continue
                overlap = len(q_tokens & parts) / len(parts)
                if overlap >= 0.5:
                    scored[ent_id] = max(scored.get(ent_id, 0.0), 0.55 * overlap + 0.2)

        return sorted(scored.items(), key=lambda kv: -kv[1])[:6]

    def traverse(self, seeds: list[tuple[str, float]], max_hops: int) -> dict[str, dict]:
        """Multi-hop traversal in Cypher.

        shortestPath keeps one path per reached entity, which is what we want: the
        cheapest explanation of why a chunk is relevant. Direction is left unspecified
        so 'who owns the thing that depends on X' works in both directions.
        """
        cypher = """
        MATCH (seed:Entity {id: $seed})
        MATCH p = shortestPath((seed)-[:REL*0..%d]-(e:Entity))
        MATCH (e)-[:MENTIONED_IN]->(c:Chunk)
        RETURN c.id                              AS chunk_id,
               length(p)                         AS hops,
               [n IN nodes(p) | n.label]         AS labels,
               [r IN relationships(p) | r.type]  AS rels
        """ % max(0, int(max_hops))

        chunk_scores: dict[str, dict] = {}
        with self.driver.session(database=self.database) as session:
            for seed_id, strength in seeds:
                for record in session.run(cypher, seed=seed_id):
                    hops = int(record["hops"])
                    contrib = strength * (HOP_DECAY ** hops)
                    chunk_id = record["chunk_id"]
                    path = _interleave(record["labels"], record["rels"])
                    current = chunk_scores.get(chunk_id)
                    if current is None:
                        chunk_scores[chunk_id] = {"score": contrib, "path": path, "hops": hops}
                    elif contrib > current["score"]:
                        current["score"] = contrib + current["score"] * 0.25
                        current["path"] = path
                        current["hops"] = hops
                    else:
                        current["score"] += contrib * 0.25
        return chunk_scores

    def snapshot(self, limit: int = 250) -> GraphSnapshot:
        with self.driver.session(database=self.database) as session:
            node_rows = list(session.run(
                """
                MATCH (e:Entity)
                RETURN e.id AS id, e.label AS label, e.type AS type,
                       coalesce(e.mentions, 0) AS mentions
                ORDER BY mentions DESC LIMIT $limit
                """,
                limit=limit,
            ))
            keep = {r["id"] for r in node_rows}
            edge_rows = list(session.run(
                """
                MATCH (s:Entity)-[r:REL]->(o:Entity)
                RETURN s.id AS source, o.id AS target, r.type AS relation,
                       coalesce(r.confidence, 0.8) AS confidence,
                       coalesce(r.chunk_ids, []) AS chunk_ids
                """
            ))
            totals = session.run(
                "MATCH (e:Entity) WITH count(e) AS n "
                "OPTIONAL MATCH ()-[r:REL]->() RETURN n, count(r) AS m"
            ).single()
            n_entities = int(totals["n"] or 0)
            n_relations = int(totals["m"] or 0)

            # Connected components without APOC: expand from each unvisited seed.
            comp_rows = list(session.run(
                """
                MATCH (e:Entity)
                OPTIONAL MATCH (e)-[:REL]-(nbr:Entity)
                RETURN e.id AS id, collect(DISTINCT nbr.id) AS nbrs
                """
            ))

        adjacency = {r["id"]: [n for n in r["nbrs"] if n] for r in comp_rows}
        components = _components(adjacency)
        largest = max((len(c) for c in components), default=0)

        nodes = [
            GraphNode(id=r["id"], label=r["label"], type=r["type"] or "Concept", mentions=int(r["mentions"]))
            for r in node_rows
        ]
        edges = [
            GraphEdge(
                source=r["source"], target=r["target"], relation=r["relation"],
                confidence=float(r["confidence"]), chunk_ids=list(r["chunk_ids"]),
            )
            for r in edge_rows
            if r["source"] in keep and r["target"] in keep
        ]
        return GraphSnapshot(
            nodes=nodes, edges=edges,
            n_entities=n_entities, n_relations=n_relations,
            n_components=len(components),
            largest_component_pct=round(100.0 * largest / max(1, n_entities), 1),
        )

    def clear(self) -> None:
        with self.driver.session(database=self.database) as session:
            session.run("MATCH (n) WHERE n:Entity OR n:Chunk DETACH DELETE n")
        self.entities.clear()
        self.alias_index.clear()
        self.token_index.clear()


def _interleave(labels: list[str], rels: list[str]) -> list[str]:
    """Render a Cypher path as the same ['A', '-[REL]->', 'B'] shape the UI expects."""
    path: list[str] = []
    for i, label in enumerate(labels):
        path.append(label)
        if i < len(rels):
            path.append("-[" + rels[i] + "]->")
    return path


def _components(adjacency: dict[str, list[str]]) -> list[set[str]]:
    seen: set[str] = set()
    out: list[set[str]] = []
    for node in adjacency:
        if node in seen:
            continue
        stack, comp = [node], set()
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            comp.add(cur)
            stack.extend(n for n in adjacency.get(cur, ()) if n not in seen)
        out.append(comp)
    return out
