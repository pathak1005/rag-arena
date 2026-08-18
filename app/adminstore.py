"""Single-owner admin: authentication and editable site content.

Threat model, stated plainly because this ships on a public URL:

- The admin panel is reachable by anyone who guesses the query parameter. Obscurity is
  NOT the control - the password hash is. `/admin/ashish` being unlisted only keeps it
  out of casual view and out of the tab bar.
- Signup is locked to one email address. A second signup attempt is refused even with a
  valid form, so the panel cannot be claimed by whoever finds it first before the owner
  registers. Register immediately after first deploy.
- Passwords are stored as scrypt hashes with a per-user random salt. scrypt is memory-hard,
  so a leaked credentials file is expensive to attack offline. stdlib only - no bcrypt or
  passlib dependency.
- Login attempts are throttled per process. Not a substitute for a WAF, but it turns an
  online guessing attack from minutes into weeks.
- Sessions live in Streamlit's server-side session_state. Nothing authentication-related
  is put in a cookie or a URL, so there is no token for a client to forge or replay.
  The cost is that a browser refresh logs you out, which is an acceptable trade for a
  panel used a few times a week.

What this is NOT: multi-user auth, RBAC, or anything you should protect genuinely
sensitive data with. It protects a personal site's content from casual defacement.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("rag.admin")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CREDENTIALS_PATH = Path(os.getenv("ADMIN_CRED_PATH", DATA_DIR / "admin_credentials.json"))
CONTENT_PATH = Path(os.getenv("PORTFOLIO_PATH", DATA_DIR / "portfolio.json"))

# The only address permitted to register. Overridable so the repo is reusable.
OWNER_EMAIL = os.getenv("ADMIN_EMAIL", "ashishpathak1005@gmail.com").strip().lower()

# The query-parameter value that reveals the admin view: ?admin=ashish
ADMIN_SLUG = os.getenv("ADMIN_SLUG", "ashish").strip()

MIN_PASSWORD_LENGTH = 12
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 900

_lock = threading.Lock()
_attempts: dict[str, list[float]] = {}


# --------------------------------------------------------------------------
# Password hashing
# --------------------------------------------------------------------------
def _hash_password(password: str, salt: bytes) -> str:
    # n=2**14 keeps login under ~100ms on a shared CPU while staying memory-hard.
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64
    ).hex()


def _load_credentials() -> dict[str, Any] | None:
    if not CREDENTIALS_PATH.exists():
        return None
    try:
        return json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.error("Could not read credentials file: %s", exc)
        return None


def is_registered() -> bool:
    return _load_credentials() is not None


def password_problems(password: str) -> list[str]:
    """Return reasons the password is unacceptable. Empty list means acceptable."""
    problems: list[str] = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"Must be at least {MIN_PASSWORD_LENGTH} characters.")
    if password.isalpha():
        problems.append("Add at least one digit or symbol.")
    if password.isdigit():
        problems.append("Add at least one letter.")
    if password.lower() in {"password", "letmein", "portfolio", "admin1234567"}:
        problems.append("That password is guessable.")
    return problems


def register(email: str, password: str) -> tuple[bool, str]:
    """Create the single owner account. Refuses if one already exists."""
    email = email.strip().lower()

    if is_registered():
        return False, "An account already exists. Sign in instead - only one account is permitted."
    if not hmac.compare_digest(email, OWNER_EMAIL):
        # Deliberately does not reveal which address IS allowed.
        log.warning("Signup refused for non-owner address")
        return False, "This address is not permitted to register."

    problems = password_problems(password)
    if problems:
        return False, " ".join(problems)

    salt = secrets.token_bytes(32)
    payload = {
        "email": email,
        "salt": salt.hex(),
        "hash": _hash_password(password, salt),
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "algorithm": "scrypt-n16384-r8-p1",
    }
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        os.chmod(CREDENTIALS_PATH, 0o600)   # best effort; a no-op on some filesystems
    except OSError:
        pass
    log.info("Owner account registered")
    return True, "Account created. You are signed in."


def _throttled(key: str) -> tuple[bool, int]:
    now = time.time()
    with _lock:
        recent = [t for t in _attempts.get(key, []) if now - t < LOCKOUT_SECONDS]
        _attempts[key] = recent
        if len(recent) >= MAX_ATTEMPTS:
            return True, int(LOCKOUT_SECONDS - (now - recent[0]))
    return False, 0


def _record_failure(key: str) -> None:
    with _lock:
        _attempts.setdefault(key, []).append(time.time())


def authenticate(email: str, password: str) -> tuple[bool, str]:
    email = email.strip().lower()

    locked, wait = _throttled(email)
    if locked:
        return False, f"Too many failed attempts. Try again in {wait // 60 + 1} minute(s)."

    creds = _load_credentials()
    if creds is None:
        return False, "No account exists yet. Register first."

    salt = bytes.fromhex(creds["salt"])
    candidate = _hash_password(password, salt)

    # Compare both fields in constant time; never short-circuit on the email.
    email_ok = hmac.compare_digest(email, creds["email"])
    hash_ok = hmac.compare_digest(candidate, creds["hash"])

    if email_ok and hash_ok:
        with _lock:
            _attempts.pop(email, None)
        return True, "Signed in."

    _record_failure(email)
    # One message for both failure modes - revealing which was wrong helps an attacker.
    return False, "Incorrect email or password."


def change_password(current: str, new: str) -> tuple[bool, str]:
    creds = _load_credentials()
    if creds is None:
        return False, "No account exists."
    ok, _ = authenticate(creds["email"], current)
    if not ok:
        return False, "Current password is incorrect."
    problems = password_problems(new)
    if problems:
        return False, " ".join(problems)
    salt = secrets.token_bytes(32)
    creds.update({"salt": salt.hex(), "hash": _hash_password(new, salt),
                  "rotated": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    CREDENTIALS_PATH.write_text(json.dumps(creds, indent=2), encoding="utf-8")
    return True, "Password changed."


# --------------------------------------------------------------------------
# Editable site content
# --------------------------------------------------------------------------
# Placeholders are written so they are OBVIOUSLY unfilled. A portfolio that ships with
# plausible-looking invented experience is worse than one that ships visibly empty.
DEFAULT_CONTENT: dict[str, Any] = {
    "profile": {
        "name": "Ashish Pathak",
        "headline": "[Add your headline in /admin]",
        "location": "",
        "email": "",
        "summary": "[Add your professional summary in the admin panel. Two or three sentences: what you do, who for, and what you are known for.]",
        "portfolio_url": "",
        "calendly_url": "",
        "linkedin_url": "",
        "github_url": "https://github.com/pathak1005",
    },
    "skills": [],
    "experience": [],
    "education": [],
    "projects": [
        {
            "name": "RAG Arena",
            "period": "2026",
            "summary": "Lexical vs vector vs graph retrieval over one identical chunk set, with deterministic evaluation, a self-correcting LangGraph agent loop, and PII governance.",
            "link": "https://github.com/pathak1005/rag-arena",
        }
    ],
    "blog": [],
    "resume": {
        "markdown": "",
        "file_name": "",
        "file_b64": "",
        "updated": "",
    },
    "meta": {"updated": "", "version": 1},
}


def load_content() -> dict[str, Any]:
    if not CONTENT_PATH.exists():
        return json.loads(json.dumps(DEFAULT_CONTENT))
    try:
        stored = json.loads(CONTENT_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.error("portfolio.json unreadable (%s); serving defaults", exc)
        return json.loads(json.dumps(DEFAULT_CONTENT))

    # Merge over defaults so a schema addition does not break an older stored file.
    merged = json.loads(json.dumps(DEFAULT_CONTENT))
    for key, value in stored.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def save_content(content: dict[str, Any]) -> tuple[bool, str]:
    try:
        content.setdefault("meta", {})
        content["meta"]["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        content["meta"]["version"] = int(content["meta"].get("version", 1)) + 1
        CONTENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp file and replace, so an interrupted write cannot leave the
        # site with a truncated content file.
        tmp = CONTENT_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(content, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(CONTENT_PATH)
        return True, "Saved."
    except OSError as exc:
        log.error("Could not save content: %s", exc)
        return False, f"Could not save: {exc}"


def is_placeholder(value: str) -> bool:
    return isinstance(value, str) and value.strip().startswith("[Add")
