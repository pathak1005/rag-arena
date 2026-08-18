"""Observability: an always-on local tracer, plus LangSmith when a key is present.

Design rule: the local tracer is the primary, not the fallback. A portfolio project whose
observability story requires someone to sign up for a SaaS account and paste a key has no
observability story - the person evaluating it will never see a trace.

So every agent run is recorded in-process and rendered in the UI regardless of configuration.
LangSmith, when LANGCHAIN_API_KEY is set, is an *additional* sink for the same spans.

Ring buffer, not a database. Traces are debugging aids with a short useful life; persisting
them would mean a schema, migrations, and retention policy for something nobody reads twice.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("rag.obs")

MAX_TRACES = 50

LANGSMITH_ENABLED = bool(os.getenv("LANGCHAIN_API_KEY", "").strip())
LANGSMITH_PROJECT = os.getenv("LANGCHAIN_PROJECT", "rag-arena")

if LANGSMITH_ENABLED:
    # LangChain reads these at import time, so they have to be set before the agent
    # module imports langchain_core.
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_PROJECT", LANGSMITH_PROJECT)
    log.info("LangSmith tracing enabled (project=%s)", LANGSMITH_PROJECT)


@dataclass
class Span:
    name: str
    started_at: float
    ended_at: float | None = None
    status: str = "running"
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        end = self.ended_at if self.ended_at is not None else time.perf_counter()
        return round((end - self.started_at) * 1000, 2)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "notes": self.notes,
        }


@dataclass
class Trace:
    trace_id: str
    question: str
    started_at: float
    spans: list[Span] = field(default_factory=list)
    ended_at: float | None = None
    result_summary: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        end = self.ended_at if self.ended_at is not None else time.perf_counter()
        return round((end - self.started_at) * 1000, 2)

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "question": self.question,
            "duration_ms": self.duration_ms,
            "n_spans": len(self.spans),
            "spans": [s.to_dict() for s in self.spans],
            "summary": self.result_summary,
            "langsmith": LANGSMITH_ENABLED,
        }


class Tracer:
    """In-process span recorder. Thread-safe; one active trace per thread."""

    def __init__(self) -> None:
        self._traces: deque[Trace] = deque(maxlen=MAX_TRACES)
        self._local = threading.local()
        self._lock = threading.Lock()

    def start_trace(self, question: str) -> Trace:
        trace = Trace(trace_id=uuid.uuid4().hex[:12], question=question,
                      started_at=time.perf_counter())
        self._local.trace = trace
        with self._lock:
            self._traces.appendleft(trace)
        return trace

    def current(self) -> Trace | None:
        return getattr(self._local, "trace", None)

    def span(self, name: str, **inputs) -> "SpanContext":
        return SpanContext(self, name, inputs)

    def end_trace(self, **summary) -> None:
        trace = self.current()
        if trace is None:
            return
        trace.ended_at = time.perf_counter()
        trace.result_summary = summary
        self._local.trace = None

    def recent(self, limit: int = 20) -> list[dict]:
        with self._lock:
            return [t.to_dict() for t in list(self._traces)[:limit]]

    def get(self, trace_id: str) -> dict | None:
        with self._lock:
            for t in self._traces:
                if t.trace_id == trace_id:
                    return t.to_dict()
        return None


class SpanContext:
    def __init__(self, tracer: Tracer, name: str, inputs: dict) -> None:
        self.tracer = tracer
        self.span = Span(name=name, started_at=time.perf_counter(), inputs=inputs)

    def __enter__(self) -> Span:
        trace = self.tracer.current()
        if trace is not None:
            trace.spans.append(self.span)
        return self.span

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.span.ended_at = time.perf_counter()
        if exc_type is not None:
            self.span.status = "error"
            self.span.notes.append(str(exc)[:300])
            log.exception("span %s failed", self.span.name)
        else:
            self.span.status = "ok"
        return False


tracer = Tracer()
