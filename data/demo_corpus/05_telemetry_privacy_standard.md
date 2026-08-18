# Helios Platform - Telemetry Privacy Standard

This standard governs what may be emitted into observability pipelines. It exists because the fastest route for regulated identifiers to escape a controlled boundary is not a breach; it is a well-intentioned debug statement that someone forgot to remove.

Structured emissions must never carry raw subscriber identifiers. Where a downstream consumer genuinely requires correlation, engineers must emit a salted surrogate key instead of the original value, and the salt must rotate on the same cadence as the signing keys.

Free-text emission is the dominant source of accidental disclosure. An engineer investigating a production anomaly will frequently attach an entire request envelope to a diagnostic statement, and that envelope routinely carries contact details, postal addresses and instrument references that were never intended to leave the transactional boundary.

Suppression is applied at three points. At the emission site, a client-side filter removes known-sensitive field names before serialisation. At the collector, a pattern-matching stage catches values that escaped the first filter. At rest, retention policy purges the diagnostic tier aggressively so that residual exposure has a bounded lifetime.

Teams frequently ask why suppression is applied at all three points rather than only the last. The answer is that each stage fails differently. Field-name filters miss values placed in unexpected fields. Pattern matchers miss formats they were never taught. Retention limits exposure duration but does nothing about who reads the record in the meantime. Defence in depth is not redundancy here; each layer covers a different failure mode of the others.

Approval to bypass any suppression stage requires written sign-off from the data governance council and is granted only for a fixed investigation window. Standing exemptions are not issued under any circumstance.

Verification is continuous rather than periodic. A synthetic canary record carrying recognisable marker values is injected hourly into every emission path, and an alert fires if a marker is observed in any downstream tier. The canary is the only mechanism that reliably detects a suppression regression before a real record is exposed.
