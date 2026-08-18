"""X-API-Key authentication.

Design choices worth stating, because auth is easy to get subtly wrong:

1. **Opt-in, not opt-out.** With no `API_KEYS` set the app runs open, exactly as it does
   today for local development. Requiring a key locally would mean every contributor's
   first experience is a 401.
2. **Constant-time comparison.** A plain `==` on a secret leaks length and prefix through
   timing. `secrets.compare_digest` does not.
3. **Public endpoints stay public.** `/health` must answer without a key or Fly's health
   check fails and the machine is killed in a loop. Same for the OpenAPI schema, which is
   the documentation.
4. **Keys are labelled.** `API_KEYS` accepts `label:key` pairs so logs record *which* key
   was used without ever logging the key itself. Revoking one caller does not rotate
   everyone.

Usage:
    API_KEYS="ci:abc123,demo:def456"     # labelled
    API_KEYS="abc123"                    # unlabelled, becomes label "default"
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets

from fastapi import Header, HTTPException, Request, status

log = logging.getLogger("rag.auth")

# Endpoints that must answer without a key.
#   /health          - Fly's health check; a 401 here kills the machine on a loop
#   /openapi.json    - the schema IS the docs
#   /docs, /redoc    - Swagger UI, which fetches the schema
#   /                - service banner
PUBLIC_PATHS = {"/", "/health", "/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"}


def _load_keys() -> dict[str, str]:
    """Parse API_KEYS into {key: label}. Empty means auth is disabled."""
    raw = os.getenv("API_KEYS", "").strip()
    if not raw:
        return {}
    keys: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            label, _, key = entry.partition(":")
            label, key = label.strip(), key.strip()
        else:
            label, key = "default", entry
        if key:
            keys[key] = label
    return keys


API_KEYS = _load_keys()
AUTH_ENABLED = bool(API_KEYS)

if AUTH_ENABLED:
    log.info("API key auth ENABLED (%d key(s): %s)", len(API_KEYS), ", ".join(sorted(set(API_KEYS.values()))))
else:
    log.warning("API_KEYS not set - API is OPEN. Set API_KEYS before exposing this publicly.")


def _fingerprint(key: str) -> str:
    """Short, non-reversible key id for logs. Never log the key itself."""
    return hashlib.sha256(key.encode()).hexdigest()[:8]


def resolve_key(presented: str | None) -> str | None:
    """Return the label for a valid key, or None. Constant-time against every key."""
    if not presented:
        return None
    matched: str | None = None
    for known, label in API_KEYS.items():
        # Compare against all keys rather than breaking early, so total time does not
        # depend on which key matched or how many were checked.
        if secrets.compare_digest(presented, known):
            matched = label
    return matched


async def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> str:
    """FastAPI dependency. Returns the caller label; raises 401 otherwise."""
    if not AUTH_ENABLED:
        return "anonymous"

    path = request.url.path.rstrip("/") or "/"
    if path in PUBLIC_PATHS:
        return "public"

    # Accept `Authorization: Bearer <key>` as well - most HTTP clients and API consoles
    # send that by default, and refusing it produces confusing 401s.
    presented = x_api_key
    if not presented:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            presented = auth[7:].strip()

    label = resolve_key(presented)
    if label is None:
        log.warning(
            "[%s] 401 on %s (key_fp=%s)",
            getattr(request.state, "request_id", "?"),
            path,
            _fingerprint(presented) if presented else "none",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key. Send it as the X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    request.state.caller = label
    return label
