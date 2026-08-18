# Multi-agent architecture and observability

## Why an agent layer at all

Most "agentic RAG" is a linear pipeline wearing a costume. Adding LangGraph to a
retrieve-then-generate flow buys nothing except a dependency.

The agent layer here exists for one behaviour a linear pipeline genuinely cannot do:

> **If retrieval was bad, re-route to a different retrieval strategy and try again.**

That falls directly out of the routing thesis. If lexical, vector and graph fail in
different, predictable places, then a grader that detects "this retrieval failed" should
hand the query to a lane that fails *differently* — instead of letting the generator produce
fluent prose over irrelevant passages, which is the most dangerous failure mode in RAG
because it looks like success.

## The graph

```
plan ──> retrieve ──> grade ──┬── (context sufficient) ──> synthesize ──> verify ──> END
  ▲                           │
  └───── re-route ◄───────────┘   (context insufficient, attempts remaining)
```

| Node | Responsibility | Uses an LLM? |
| --- | --- | --- |
| `plan` | Classify the query, pick a strategy; on re-entry pick a lane not yet tried | No |
| `retrieve` | Run that strategy against the shared chunk set | No |
| `grade` | Is this context good enough to answer from? | **No** |
| `synthesize` | Generate the answer from context | Yes (or extractive fallback) |
| `verify` | Is the answer grounded in the context it was given? | **No** |

Implementation: [`app/agents/pipeline.py`](../app/agents/pipeline.py).

## Why grading and verification are deterministic

This is the design decision most likely to be questioned, so it is worth stating directly.

The conventional pattern (Self-RAG, CRAG as usually implemented) uses an LLM to grade
retrieval and again to verify the answer. Here both are deterministic functions from
`app/evaluate.py`.

Reasons:

1. **An LLM grading its own retrieval and then its own answer compounds the same bias
   twice.** If the model finds a passage plausible, it will also find its own answer from
   that passage plausible. The loop cannot detect the failure it is most likely to make.
2. **Non-determinism makes the loop unfalsifiable.** With LLM grading, the same question can
   take one attempt or three. You cannot debug a control-flow bug that only reproduces
   sometimes.
3. **Cost and latency.** Three extra LLM calls per query for grading and verification, on
   every query, to catch a minority of cases.
4. **It works.** Context relevance below 0.12 is a reliable signal that retrieval was
   off-topic, and it costs microseconds.

The honest limitation: deterministic grading catches *topical* mismatch, not *semantic*
mismatch. A chunk that shares vocabulary with the question but answers a different question
will pass the grader. Upgrading `grade` to a cross-encoder relevance model (still not a
generative LLM, so still deterministic) is the right next step — see PLAN.md Phase 9.

## Re-route order

```python
REROUTE_ORDER = {
    "graph":   ["hybrid", "vector", "lexical"],
    "vector":  ["lexical", "hybrid", "graph"],
    "lexical": ["vector", "hybrid", "graph"],
    "hybrid":  ["vector", "lexical", "graph"],
}
```

Ordered by *how differently each lane fails*. Retrying with a strategy that fails the same
way as the one that just failed is wasted work — so a failed `vector` retrieval goes to
`lexical` (exact terms, an orthogonal failure mode) before it goes to `graph`.

Capped at `MAX_ATTEMPTS = 3`. On exhaustion the pipeline synthesizes from whatever it has;
the verifier flags the result. An honestly-flagged weak answer beats an infinite loop, and
in practice the model abstains — which is the correct outcome.

`recursion_limit=25` on invoke is a second guard: a cycle bug should not become unbounded
LLM spend.

## Observed behaviour

Two runs against the demo corpus:

**In-corpus question** — `Who should I escalate to if checkout-api is failing because of a payment problem?`

```
plan        ok     5.42ms   query names 2 known entities and uses relational language
retrieve    ok     6.65ms   graph, 3 sources
grade       ok     1.59ms   context relevance 0.258 is adequate
synthesize  ok     0.32ms
verify      ok     0.77ms   answer is grounded in the retrieved context
```
One attempt, `graph`, accepted.

**Out-of-corpus question** — `What is the capital of Mars in the year 3000?`

```
plan → retrieve → grade   (lexical,  relevance 0.000, rejected)
plan → retrieve → grade   (vector,   relevance 0.000, rejected)
plan → retrieve → grade   (hybrid,   relevance 0.000, rejected)
synthesize → verify
answer: "The provided context does not contain this information."
```
Three attempts, all lanes exhausted, honest abstention. This is the behaviour the loop
exists to produce.

## Observability

Two sinks, one always available.

### Local tracer (always on)

`app/observability.py` records every span in-process: name, status, duration, inputs,
outputs, and human-readable notes. Exposed at `GET /traces` and `GET /traces/{trace_id}`,
and rendered as a waterfall in the UI's Agent Pipeline tab.

A 50-entry ring buffer, not a database. Traces are debugging aids with a short useful life;
persisting them would mean a schema, migrations, and a retention policy for something nobody
reads twice.

**Why local-first:** a portfolio project whose observability requires the reader to sign up
for a SaaS account and paste an API key has no observability story — nobody evaluating it
will ever see a trace. The local tracer is the primary; everything else is an additional
sink.

### LangSmith (optional)

Set `LANGCHAIN_API_KEY` and tracing mirrors to LangSmith automatically:

```bash
LANGCHAIN_API_KEY=ls__...
LANGCHAIN_PROJECT=rag-arena
```

`GET /traces` reports `langsmith_enabled` so you can tell which sinks are live. LangSmith's
free tier covers 5,000 traces/month, which is ample for a demo.

### Other free options

If you want a self-hosted OpenTelemetry backend instead:

- **Arize Phoenix** — `pip install arize-phoenix`, runs locally, OTel-native, no account.
- **Langfuse** — self-hostable via Docker, generous free cloud tier.
- **OpenLLMetry (Traceloop)** — OTel instrumentation that exports to any OTel collector.

None are wired in. The span model in `observability.py` maps cleanly onto OTel spans, so
adding an exporter is a small change confined to one file.

## What this is not

- **Not a tool-calling agent.** No node decides which tool to invoke from a natural-language
  description. The graph is a fixed state machine with one conditional edge. That is a
  deliberate choice: for this problem the control flow is known, and a model choosing it
  freely adds nondeterminism without adding capability.
- **Not multi-agent in the "society of agents debating" sense.** Five single-responsibility
  nodes, one control loop. Calling that "multi-agent" is already generous; the useful part is
  the loop, not the label.
- **Not using LangChain's retrievers or chains.** Retrieval is the project's own code, since
  the whole point is comparing retrieval strategies over one shared chunk set. LangGraph is
  used for orchestration only, and `langchain-core` comes along as its dependency.
