"""LLM layer (Groq) with a deterministic extractive fallback.

The fallback is not a nicety. Without it the whole arena is unusable when there is no
API key, when Groq rate-limits, or when the demo is run offline - and every result is
still comparable because the fallback is identical across strategies. Degraded runs
are flagged as degraded=True in the response rather than silently passed off as
generated answers.

One prompt template is shared by all strategies. If lexical and graph used different
prompts, the arena would be measuring prompt engineering, not retrieval.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

from app.config import (
    COST_PER_1M_INPUT,
    COST_PER_1M_OUTPUT,
    GROQ_API_KEY,
    GROQ_MODEL,
    LLM_TIMEOUT_S,
)

log = logging.getLogger("rag.llm")

SYSTEM_PROMPT = (
    "You are a precise enterprise documentation assistant.\n"
    "Rules:\n"
    "1. Answer ONLY from the numbered context passages provided.\n"
    "2. Cite the passages you used inline, like [1] or [2].\n"
    "3. If the context does not contain the answer, say exactly: "
    "'The provided context does not contain this information.' Do not guess.\n"
    "4. Never invent names, numbers, error codes, team names, or channels.\n"
    "5. Be concise: three sentences or fewer unless the question needs a chain of steps.\n"
    "6. Text marked [REDACTED_*] was removed by the PII layer. Never speculate about it."
)

ANSWER_TEMPLATE = (
    "Context passages:\n{context}\n\n"
    "Question: {question}\n\n"
    "Answer using only the passages above, with inline citations."
)

_SENT = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[A-Za-z][A-Za-z\-']+|\d+")
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "are", "for", "on", "with",
    "as", "by", "at", "be", "this", "that", "it", "from", "we", "our", "you", "your",
    "how", "what", "which", "who", "when", "do", "does", "can", "should", "if",
}


@dataclass
class Completion:
    text: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: float
    degraded: bool
    model: str


_client = None
_client_checked = False


def _get_client():
    global _client, _client_checked
    if _client_checked:
        return _client
    _client_checked = True
    if not GROQ_API_KEY:
        log.warning("GROQ_API_KEY not set - extractive fallback will be used.")
        return None
    try:
        from groq import Groq  # type: ignore

        _client = Groq(api_key=GROQ_API_KEY, timeout=LLM_TIMEOUT_S)
        log.info("Groq client ready (%s)", GROQ_MODEL)
    except Exception as exc:  # noqa: BLE001
        log.error("Groq client init failed: %s", exc)
        _client = None
    return _client


def llm_available() -> bool:
    return _get_client() is not None


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _cost(prompt_tokens: int, completion_tokens: int) -> float:
    return round(
        prompt_tokens / 1_000_000 * COST_PER_1M_INPUT
        + completion_tokens / 1_000_000 * COST_PER_1M_OUTPUT,
        8,
    )


def _keywords(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text) if w.lower() not in _STOP and len(w) > 2}


def _extractive_answer(question: str, context_blocks: list[str]) -> str:
    """Deterministic fallback: rank sentences by query-term overlap, return the best few.

    Extractive by construction, so it cannot hallucinate - which makes it a useful
    floor for the groundedness metric as well as a working offline demo.
    """
    q_words = _keywords(question)
    scored: list[tuple[float, int, str]] = []
    for block_idx, block in enumerate(context_blocks):
        for sentence in _SENT.split(block):
            sentence = sentence.strip()
            if len(sentence) < 25:
                continue
            s_words = _keywords(sentence)
            if not s_words:
                continue
            overlap = len(q_words & s_words) / max(1, len(q_words))
            density = len(q_words & s_words) / max(1, len(s_words)) ** 0.5
            scored.append((overlap + 0.3 * density, block_idx, sentence))

    scored.sort(key=lambda x: -x[0])
    picked = [s for s in scored[:3] if s[0] > 0.05]
    if not picked:
        return "The provided context does not contain this information."

    seen: set[str] = set()
    parts: list[str] = []
    for _, block_idx, sentence in picked:
        if sentence in seen:
            continue
        seen.add(sentence)
        parts.append(sentence.rstrip(".") + " [" + str(block_idx + 1) + "].")
    return " ".join(parts)


def generate(question: str, context_blocks: list[str]) -> Completion:
    """Answer the question from context. Falls back to extraction if the LLM is unavailable."""
    context = "\n\n".join(
        "[" + str(i + 1) + "] " + block for i, block in enumerate(context_blocks)
    )
    user_prompt = ANSWER_TEMPLATE.format(context=context or "(no passages retrieved)", question=question)

    client = _get_client()
    if client is None or not context_blocks:
        start = time.perf_counter()
        text = (
            _extractive_answer(question, context_blocks)
            if context_blocks
            else "The provided context does not contain this information."
        )
        elapsed = (time.perf_counter() - start) * 1000
        return Completion(
            text=text,
            prompt_tokens=_estimate_tokens(user_prompt),
            completion_tokens=_estimate_tokens(text),
            cost_usd=0.0,
            latency_ms=round(elapsed, 2),
            degraded=True,
            model="extractive-fallback",
        )

    start = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,      # determinism matters more than variety for an eval harness
            max_tokens=420,
            top_p=1.0,
        )
        elapsed = (time.perf_counter() - start) * 1000
        text = (response.choices[0].message.content or "").strip()
        usage = getattr(response, "usage", None)
        p_tok = int(getattr(usage, "prompt_tokens", 0) or _estimate_tokens(user_prompt))
        c_tok = int(getattr(usage, "completion_tokens", 0) or _estimate_tokens(text))
        return Completion(
            text=text,
            prompt_tokens=p_tok,
            completion_tokens=c_tok,
            cost_usd=_cost(p_tok, c_tok),
            latency_ms=round(elapsed, 2),
            degraded=False,
            model=GROQ_MODEL,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("Groq call failed (%s); using extractive fallback.", exc)
        elapsed = (time.perf_counter() - start) * 1000
        text = _extractive_answer(question, context_blocks)
        return Completion(
            text=text,
            prompt_tokens=_estimate_tokens(user_prompt),
            completion_tokens=_estimate_tokens(text),
            cost_usd=0.0,
            latency_ms=round(elapsed, 2),
            degraded=True,
            model="extractive-fallback",
        )


def complete_raw(system: str, user: str, max_tokens: int = 900) -> Completion:
    """Generic completion used by the Content Brief generator."""
    client = _get_client()
    if client is None:
        return Completion("", _estimate_tokens(user), 0, 0.0, 0.0, True, "unavailable")
    start = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.2,
            max_tokens=max_tokens,
        )
        elapsed = (time.perf_counter() - start) * 1000
        text = (response.choices[0].message.content or "").strip()
        usage = getattr(response, "usage", None)
        p_tok = int(getattr(usage, "prompt_tokens", 0) or _estimate_tokens(user))
        c_tok = int(getattr(usage, "completion_tokens", 0) or _estimate_tokens(text))
        return Completion(text, p_tok, c_tok, _cost(p_tok, c_tok), round(elapsed, 2), False, GROQ_MODEL)
    except Exception as exc:  # noqa: BLE001
        log.error("Groq brief call failed: %s", exc)
        return Completion("", _estimate_tokens(user), 0, 0.0, 0.0, True, "unavailable")
