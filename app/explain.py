"""Response interpreter for the API playground.

Reading a RAG response correctly is a learned skill. A 200 OK with a fluent answer can
still be a total failure - wrong chunks, fabricated identifiers, a router that picked a
lane with no seed entity. This module turns a raw response into plain statements about
what went right and what went wrong, so the playground teaches rather than just echoing
JSON.

Thresholds below are judgement calls, documented rather than hidden. They are tuned for
a small corpus and should be recalibrated against a gold set on a real one.
"""
from __future__ import annotations

from app.models import ExplainedResponse, Observation

# Tuned on the demo corpus. On a larger corpus, groundedness drifts down (answers reuse
# fewer context words verbatim) so these would need recalibrating - which is exactly why
# they are constants in one place rather than scattered magic numbers.
GROUNDEDNESS_GOOD = 0.55
GROUNDEDNESS_BAD = 0.30
RELEVANCE_GOOD = 0.30
RELEVANCE_BAD = 0.12
LEAKAGE_BAD = 0.25
CITATION_GOOD = 0.70


def _metric_observations(result: dict) -> list[Observation]:
    obs: list[Observation] = []
    m = result.get("metrics", {})
    strategy = result.get("strategy", "?")
    sources = result.get("sources", [])

    # --- retrieval happened at all
    if not sources:
        obs.append(Observation(
            verdict="bad", field="sources",
            observation="Zero chunks retrieved for the " + strategy + " lane.",
            meaning=(
                "The answer, whatever it says, is not grounded in your corpus. For the graph "
                "lane this usually means no entity in the question matched the graph, so there "
                "was nothing to seed traversal from. Check `trace.seeds`."
            ),
        ))
        return obs

    obs.append(Observation(
        verdict="info", field="sources",
        observation="Retrieved " + str(len(sources)) + " chunks from "
                    + str(len({s["doc_id"] for s in sources})) + " document(s).",
        meaning=(
            "Chunks drawn from several documents suggest the question spans sources - the case "
            "graph traversal exists for. All chunks from one document suggests a lookup."
        ),
    ))

    # --- groundedness
    grounded = m.get("groundedness", 0.0)
    if grounded >= GROUNDEDNESS_GOOD:
        obs.append(Observation(
            verdict="good", field="metrics.groundedness",
            observation="Groundedness " + format(grounded, ".2f") + " - most answer content traces to the context.",
            meaning="The model is working from the retrieved passages rather than from memory.",
        ))
    elif grounded <= GROUNDEDNESS_BAD:
        obs.append(Observation(
            verdict="bad", field="metrics.groundedness",
            observation="Groundedness " + format(grounded, ".2f") + " - most answer content is NOT in the context.",
            meaning=(
                "Either the model is drawing on pretrained knowledge instead of your documents, "
                "or it correctly refused and the refusal wording simply shares few words with the "
                "context. Read the answer before concluding it hallucinated."
            ),
        ))
    else:
        obs.append(Observation(
            verdict="warning", field="metrics.groundedness",
            observation="Groundedness " + format(grounded, ".2f") + " - partially supported.",
            meaning="Some claims trace to context, some do not. Worth reading the answer against the sources.",
        ))

    # --- entity leakage: the sharpest signal
    leakage = m.get("entity_leakage", 0.0)
    if leakage >= LEAKAGE_BAD:
        obs.append(Observation(
            verdict="bad", field="metrics.entity_leakage",
            observation="Entity leakage " + format(leakage, ".2f") + " - the answer asserts identifiers "
                        "or numbers that do not appear in any retrieved chunk.",
            meaning=(
                "This is the most reliable hallucination signal available without an LLM judge. "
                "A fabricated error code or team name is worse than a vague answer, because it "
                "looks authoritative and a user will act on it."
            ),
        ))
    elif leakage == 0.0:
        obs.append(Observation(
            verdict="good", field="metrics.entity_leakage",
            observation="Entity leakage 0.00 - every specific value in the answer appears in the context.",
            meaning="No fabricated identifiers, codes, names, or numbers.",
        ))

    # --- context relevance separates retrieval failure from generation failure
    relevance = m.get("context_relevance", 0.0)
    if relevance <= RELEVANCE_BAD:
        obs.append(Observation(
            verdict="warning", field="metrics.context_relevance",
            observation="Context relevance " + format(relevance, ".2f") + " - retrieved chunks share little with the query.",
            meaning=(
                "This is a RETRIEVAL failure, not a generation failure. Changing the prompt or the "
                "model will not help. Try a different strategy, or check whether the corpus actually "
                "contains the answer."
            ),
        ))
    elif relevance >= RELEVANCE_GOOD:
        obs.append(Observation(
            verdict="good", field="metrics.context_relevance",
            observation="Context relevance " + format(relevance, ".2f") + " - retrieval found on-topic material.",
            meaning="Retrieval did its job. Any remaining error is attributable to generation.",
        ))

    # --- citation coverage
    citation = m.get("citation_coverage", 0.0)
    if citation < CITATION_GOOD:
        obs.append(Observation(
            verdict="warning", field="metrics.citation_coverage",
            observation="Citation coverage " + format(citation, ".2f") + " - some answer sentences have no supporting chunk.",
            meaning="Unsupported sentences are usually connective filler, but they are also where "
                    "invented claims hide. Check the sentences that lack support.",
        ))

    # --- extractiveness read in combination, never alone
    extractive = m.get("extractiveness", 0.0)
    if extractive > 0.85:
        obs.append(Observation(
            verdict="warning", field="metrics.extractiveness",
            observation="Extractiveness " + format(extractive, ".2f") + " - the answer is near-verbatim copy.",
            meaning="Safe but not synthesised. Fine for a lookup; poor for a question needing "
                    "several facts combined.",
        ))

    # --- degraded mode
    if result.get("degraded"):
        obs.append(Observation(
            verdict="warning", field="degraded",
            observation="degraded=true - the answer came from the extractive fallback, not an LLM.",
            meaning=(
                "No GROQ_API_KEY, or the API call failed. Retrieval metrics are still valid and "
                "comparable; answer fluency is not representative. Groundedness will read "
                "artificially high because extraction cannot invent text."
            ),
        ))

    # --- cost and latency
    if result.get("cost_usd", 0) == 0 and not result.get("degraded"):
        obs.append(Observation(
            verdict="info", field="cost_usd",
            observation="Cost is zero with a live LLM - token usage was not reported.",
            meaning="Groq returns usage on most calls; a zero here means the estimate fell back to "
                    "character-count approximation.",
        ))

    return obs


def explain_chat(response: dict) -> ExplainedResponse:
    result = response.get("result", {})
    routing = response.get("routing", {})
    obs: list[Observation] = []

    recommended = routing.get("recommended")
    used = result.get("strategy")
    confidence = routing.get("confidence", 0)

    if used != recommended:
        obs.append(Observation(
            verdict="info", field="routing.recommended",
            observation="Router recommended '" + str(recommended) + "' but '" + str(used) + "' was forced.",
            meaning="Useful for testing: compare a lane against the one the router would have picked.",
        ))
    elif confidence < 0.5:
        obs.append(Observation(
            verdict="warning", field="routing.confidence",
            observation="Routing confidence " + format(confidence, ".2f") + " - signals were close.",
            meaning="No lane clearly fits this question. Hybrid (RRF) is usually the safer choice "
                    "when the margin is this thin.",
        ))
    else:
        obs.append(Observation(
            verdict="good", field="routing",
            observation="Router chose '" + str(recommended) + "' with confidence "
                        + format(confidence, ".2f") + ".",
            meaning=str(routing.get("rationale", "")),
        ))

    if used == "graph":
        seeds = (result.get("trace") or {}).get("seeds", [])
        if not seeds:
            obs.append(Observation(
                verdict="bad", field="trace.seeds",
                observation="Graph lane ran with no seed entities.",
                meaning="Entity linking failed, so traversal had no starting point. Either the "
                        "question names nothing in the graph, or entity resolution failed to merge "
                        "the surface form used in the question with the node.",
            ))
        else:
            hops = (result.get("trace") or {}).get("max_hops_used", 0)
            obs.append(Observation(
                verdict="good" if hops > 0 else "warning",
                field="trace.max_hops_used",
                observation="Traversal reached " + str(hops) + " hop(s) from "
                            + str(len(seeds)) + " seed entity(ies).",
                meaning=(
                    "Multi-hop retrieval genuinely crossed document boundaries - this is the case "
                    "flat retrieval cannot serve."
                    if hops > 0 else
                    "Everything came from chunks directly mentioning the seed. The graph added no "
                    "reach here; vector or lexical would likely do the same job more cheaply."
                ),
            ))

    obs.extend(_metric_observations(result))

    bad = sum(1 for o in obs if o.verdict == "bad")
    warn = sum(1 for o in obs if o.verdict == "warning")
    if bad:
        summary = str(bad) + " serious issue(s) in this response - read them before trusting the answer."
    elif warn:
        summary = "Answer looks usable, with " + str(warn) + " caveat(s) worth understanding."
    else:
        summary = "Clean response: grounded, relevant, no fabricated specifics."

    return ExplainedResponse(endpoint="/chat", summary=summary, observations=obs)


def explain_compare(response: dict) -> ExplainedResponse:
    obs: list[Observation] = []
    results = response.get("results", [])

    empty = [r["strategy"] for r in results if not r.get("sources")]
    if empty:
        obs.append(Observation(
            verdict="warning", field="results[].sources",
            observation="These lanes retrieved nothing: " + ", ".join(empty) + ".",
            meaning="Not necessarily a bug. The graph lane legitimately returns nothing when the "
                    "question names no known entity - that is the router's signal to avoid it.",
        ))

    scored = [r for r in results if r.get("sources")]
    if len(scored) >= 2:
        overlaps = []
        for i in range(len(scored)):
            for j in range(i + 1, len(scored)):
                a = {s["chunk_id"] for s in scored[i]["sources"]}
                b = {s["chunk_id"] for s in scored[j]["sources"]}
                if a and b:
                    overlaps.append((scored[i]["strategy"], scored[j]["strategy"],
                                     len(a & b) / len(a | b)))
        if overlaps:
            mean_overlap = sum(o[2] for o in overlaps) / len(overlaps)
            if mean_overlap > 0.75:
                obs.append(Observation(
                    verdict="warning", field="results[].sources",
                    observation="Strategies returned nearly identical chunks (mean Jaccard "
                                + format(mean_overlap, ".2f") + ").",
                    meaning="This question does not discriminate between strategies. A comparison "
                            "on queries like this proves nothing - use one that targets a specific "
                            "retrieval weakness.",
                ))
            else:
                obs.append(Observation(
                    verdict="good", field="results[].sources",
                    observation="Strategies disagree on which chunks matter (mean Jaccard "
                                + format(mean_overlap, ".2f") + ").",
                    meaning="A discriminating question. The score differences below are meaningful.",
                ))

    if response.get("winner"):
        obs.append(Observation(
            verdict="info", field="winner",
            observation="Winner: " + response["winner"] + ".",
            meaning=response.get("winner_reason", ""),
        ))

    for r in results:
        for o in _metric_observations(r):
            if o.verdict in ("bad", "warning"):
                obs.append(Observation(
                    verdict=o.verdict,
                    field="[" + r["strategy"] + "] " + o.field,
                    observation=o.observation,
                    meaning=o.meaning,
                ))

    bad = sum(1 for o in obs if o.verdict == "bad")
    summary = (
        str(bad) + " lane(s) produced an untrustworthy answer." if bad
        else "No serious failures across the compared lanes."
    )
    return ExplainedResponse(endpoint="/query_compare", summary=summary, observations=obs)
