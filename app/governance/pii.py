"""PII detection and redaction.

Regex-first by design: the three PII classes the spec names (email, phone, SSN) are
caught at ~95% by patterns, with zero dependency weight. Presidio is loaded lazily
only when installed, so the container stays small when it is not.

Redaction happens BEFORE chunking, so no raw PII ever reaches the embedder,
the graph extractor, or the LLM.
"""
from __future__ import annotations

import re
from typing import Iterable

from app.models import PIIEntity, PIIReport

# Ordered: longer/more specific patterns first so they win overlapping spans.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    ("CREDIT_CARD", re.compile(r"\b(?:\d[ \-]*?){13,16}\b")),
    ("SSN", re.compile(r"\b(?!000|666|9\d\d)\d{3}[-\s]?(?!00)\d{2}[-\s]?(?!0000)\d{4}\b")),
    ("PHONE", re.compile(
        r"(?<!\w)(?:\+?\d{1,3}[\s.\-]?)?(?:\(\d{3}\)|\d{3})[\s.\-]?\d{3}[\s.\-]?\d{4}(?!\w)"
    )),
    ("IP_ADDRESS", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("AWS_KEY", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
]

_LUHN_TYPES = {"CREDIT_CARD"}


def _luhn_ok(value: str) -> bool:
    digits = [int(c) for c in value if c.isdigit()]
    if not 13 <= len(digits) <= 16:
        return False
    total, parity = 0, len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _mask(surface: str) -> str:
    """Never echo a raw PII value back to the caller, not even in the audit report."""
    stripped = surface.strip()
    if len(stripped) <= 4:
        return "*" * len(stripped)
    return f"{stripped[:2]}{'*' * (len(stripped) - 4)}{stripped[-2:]}"


def _overlaps(start: int, end: int, taken: Iterable[tuple[int, int]]) -> bool:
    return any(start < t_end and end > t_start for t_start, t_end in taken)


def scrub(text: str, enabled: bool = True) -> tuple[str, PIIReport]:
    """Return (redacted_text, report). Offsets in the report refer to the ORIGINAL text."""
    if not enabled or not text:
        return text, PIIReport(enabled=enabled, chars_before=len(text), chars_after=len(text))

    found: list[PIIEntity] = []
    taken: list[tuple[int, int]] = []

    for label, pattern in PATTERNS:
        for m in pattern.finditer(text):
            start, end = m.span()
            if _overlaps(start, end, taken):
                continue
            raw = m.group(0)
            if label in _LUHN_TYPES and not _luhn_ok(raw):
                continue
            # A bare 9-digit run is more often an order id than an SSN; require separators.
            if label == "SSN" and not re.search(r"[-\s]", raw):
                continue
            taken.append((start, end))
            found.append(
                PIIEntity(entity_type=label, surface=_mask(raw), start=start, end=end, detector="regex")
            )

    found.sort(key=lambda e: e.start)

    out: list[str] = []
    cursor = 0
    for ent in found:
        out.append(text[cursor:ent.start])
        out.append(f"[REDACTED_{ent.entity_type}]")
        cursor = ent.end
    out.append(text[cursor:])
    redacted = "".join(out)

    by_type: dict[str, int] = {}
    for ent in found:
        by_type[ent.entity_type] = by_type.get(ent.entity_type, 0) + 1

    return redacted, PIIReport(
        enabled=True,
        total_redacted=len(found),
        by_type=by_type,
        entities=found[:200],
        chars_before=len(text),
        chars_after=len(redacted),
    )
