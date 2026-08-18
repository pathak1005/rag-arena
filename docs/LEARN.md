# Hands-on: Neo4j and ChromaDB

A guided tour of the two real databases, using the data this project already produces.
Everything here is runnable.

---

## Part 1 — Neo4j

### Start it and load data

```bash
docker compose up -d neo4j
# wait ~20s for the health check to go green
docker compose ps
```

Point the app at it and load the corpus:

```bash
GRAPH_BACKEND=neo4j .venv/Scripts/python -m uvicorn app.main:app --port 8000
curl -X POST http://127.0.0.1:8000/seed_demo
```

Open **http://localhost:7474** — user `neo4j`, password `helios-dev-password`.

### The schema you just built

```
(:Entity {id, label, type, aliases, mentions})
(:Chunk  {id, doc_id, doc_title})

(:Entity)-[:REL {type, confidence, chunk_ids, evidence}]->(:Entity)
(:Entity)-[:MENTIONED_IN]->(:Chunk)
```

### Queries, in increasing order of interest

**1. What's in here?**

```cypher
MATCH (n) RETURN labels(n) AS label, count(*) AS count;
```

**2. See the graph.** Neo4j Browser renders this visually — this is the query to run first.

```cypher
MATCH p = (:Entity)-[:REL]->(:Entity)
RETURN p LIMIT 100;
```

**3. What relation types were extracted?**

```cypher
MATCH ()-[r:REL]->()
RETURN r.type AS relation, count(*) AS count
ORDER BY count DESC;
```

**4. The multi-hop chain the demo is built around.** This is the query that graph RAG exists
to answer, written out by hand:

```cypher
MATCH path = (s:Entity {label: 'checkout-api'})-[:REL*1..3]-(target:Entity)
WHERE target.type = 'Person'
RETURN [n IN nodes(path) | n.label]        AS chain,
       [r IN relationships(path) | r.type]  AS relations,
       length(path)                         AS hops
ORDER BY hops;
```

You should see `checkout-api → payments-gateway → Team Meridian → Priya Raman`.

**5. The bridge back to text.** This is the step that makes it retrieval rather than a
knowledge graph — traversal finds entities, `MENTIONED_IN` converts them to chunks:

```cypher
MATCH (s:Entity {label: 'checkout-api'})
MATCH p = shortestPath((s)-[:REL*0..3]-(e:Entity))
MATCH (e)-[:MENTIONED_IN]->(c:Chunk)
RETURN c.doc_title            AS document,
       length(p)              AS hops,
       [n IN nodes(p) | n.label] AS path,
       count(*)               AS mentions
ORDER BY hops, document
LIMIT 25;
```

This is exactly what `Neo4jGraphStore.traverse()` runs. Compare it to
[`app/retrieval/graph_neo4j.py`](../app/retrieval/graph_neo4j.py).

**6. Blast radius — what breaks if `ledger-service` goes down?**

```cypher
MATCH (target:Entity {label: 'ledger-service'})<-[:REL {type: 'DEPENDS_ON'}*1..3]-(affected:Entity)
RETURN DISTINCT affected.label AS affected_service;
```

**7. Find the entity-resolution failures.** This is the diagnostic that matters most —
entities that look like duplicates of each other:

```cypher
MATCH (a:Entity), (b:Entity)
WHERE a.id < b.id
  AND (toLower(a.label) CONTAINS toLower(b.label)
       OR toLower(b.label) CONTAINS toLower(a.label))
RETURN a.label AS entity_a, b.label AS entity_b,
       a.mentions AS a_mentions, b.mentions AS b_mentions
ORDER BY a_mentions + b_mentions DESC
LIMIT 20;
```

Every row is a merge that step 4 of the resolution ladder (embedding clustering) would have
caught. This is the ~42-component problem from `docs/DECISIONS.md` D9, made concrete.

**8. Orphans — entities with no relationships.** These are reachable only by direct mention,
never by traversal:

```cypher
MATCH (e:Entity)
WHERE NOT (e)-[:REL]-()
RETURN e.label, e.type, e.mentions
ORDER BY e.mentions DESC
LIMIT 20;
```

**9. Which chunks are graph-reachable at all?**

```cypher
MATCH (c:Chunk)
OPTIONAL MATCH (e:Entity)-[:MENTIONED_IN]->(c)
WITH c, count(e) AS entity_count
RETURN entity_count = 0 AS invisible_to_graph, count(*) AS chunks
ORDER BY invisible_to_graph;
```

Chunks with zero entities can never be retrieved by the graph lane, no matter how relevant.
That is not a bug — it is why routing exists.

### Cleanup

```cypher
MATCH (n) WHERE n:Entity OR n:Chunk DETACH DELETE n;
```

Or `docker compose down -v` to drop the volume entirely.

### Things worth noticing

- **`shortestPath` vs `[:REL*0..3]`.** The unbounded form returns *every* path between two
  nodes, which grows combinatorially. `shortestPath` returns one — the cheapest explanation
  of why a chunk is relevant, which is what you want for ranking.
- **Direction is unspecified** (`-[:REL]-` not `-[:REL]->`) because "who owns the thing that
  X depends on" has to traverse `DEPENDS_ON` forwards and `OWNED_BY` forwards from a
  different node.
- **The write pattern is naive.** `add_mention` issues one transaction per entity per chunk.
  Fine for 51 chunks, wrong for 50,000 — you would batch with `UNWIND`. Noted in
  INFRASTRUCTURE.md.

---

## Part 2 — ChromaDB

### Switch to it

```bash
VECTOR_BACKEND=chroma .venv/Scripts/python -m uvicorn app.main:app --port 8000
curl -X POST http://127.0.0.1:8000/seed_demo
curl http://127.0.0.1:8000/backends
```

Data persists to `data/chroma/`.

### Inspect the collection directly

```python
import chromadb
client = chromadb.PersistentClient(path="data/chroma")

print(client.list_collections())

col = client.get_collection("helios_chunks")
print("vectors:", col.count())
print("metadata:", col.metadata)          # includes hnsw:space and the embedder name

peek = col.peek(limit=2)
print(peek["ids"])
print(len(peek["embeddings"][0]), "dimensions")
```

### Query it yourself

```python
from app.embed import get_embedder
embedder = get_embedder()

q = embedder.encode(["Who do I page when payments fail?"])[0]
res = col.query(query_embeddings=[q.tolist()], n_results=3,
                include=["documents", "metadatas", "distances"])

for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
    print(f"{1 - dist:.4f}  {meta['doc_title']}  {doc[:80]}")
```

Note `1 - dist`: Chroma returns cosine **distance**, not similarity. Getting this backwards
silently inverts your ranking and is one of the more common bugs in first-time Chroma code.

### Metadata filtering — the thing vector DBs give you over a numpy matrix

```python
col.query(
    query_embeddings=[q.tolist()],
    n_results=3,
    where={"doc_title": "03_oncall_escalation.md"},
)
```

Pre-filtering by metadata before the ANN search is the main practical reason to run a vector
database rather than a matrix. At 51 chunks it buys nothing; at 5 million it is the
difference between a working product and a slow one.

### Exact vs approximate — run the experiment

Chroma uses HNSW, an **approximate** nearest-neighbour index. The numpy backend is exact.
Run the same query against both and compare:

```bash
VECTOR_BACKEND=numpy  curl -s -X POST localhost:8000/chat \
  -d '{"question":"How do we stop customer data leaking into logs?","strategy":"vector"}' \
  -H 'Content-Type: application/json' | jq '.result.sources[].chunk_id'

VECTOR_BACKEND=chroma curl -s -X POST localhost:8000/chat \
  -d '{"question":"How do we stop customer data leaking into logs?","strategy":"vector"}' \
  -H 'Content-Type: application/json' | jq '.result.sources[].chunk_id'
```

Any difference is ANN recall loss, made visible. At this corpus size it should be zero — HNSW
is exact when the graph is small enough. That is itself the lesson: the approximation only
starts costing you at a scale where you also can't afford exact search.

### Things worth noticing

- **Embeddings are supplied explicitly**, not delegated to Chroma's default model. If
  documents were embedded with one model and queries with another, every score would be
  meaningless — and it would fail *silently*, returning plausible-looking neighbours.
- **The collection is rebuilt, not upserted**, on every ingest. At this scale a stale vector
  left behind by a partial update is much harder to notice than a slow rebuild.

---

## Part 3 — Compare the backends end to end

```bash
# in-process
GRAPH_BACKEND=networkx VECTOR_BACKEND=numpy  .venv/Scripts/python -m uvicorn app.main:app --port 8000

# real databases
GRAPH_BACKEND=neo4j    VECTOR_BACKEND=chroma .venv/Scripts/python -m uvicorn app.main:app --port 8000
```

Then run the same three demo questions through the Evaluation Arena in both configurations
and compare `retrieval_ms` and the returned `chunk_id`s.

What you should find: results are essentially identical, and the in-process backends are
*faster* at this scale. That is the honest conclusion — the databases earn their place at
scale, on persistence, and on concurrent access, not on small-corpus quality. Anyone claiming
Neo4j made their 50-chunk demo more accurate is measuring noise.
