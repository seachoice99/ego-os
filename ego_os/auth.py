"""Owner access control (v0.4.1).

Single-owner deployment, so the simplest mechanism that's actually
correct: HTTP Basic Auth over the existing HTTPS/Let's Encrypt setup,
compared with a constant-time check. Credentials live only in
OWNER_USERNAME/OWNER_PASSWORD env vars -- never hardcoded, never
committed (see .env.example).

Applied as a global FastAPI dependency (ego_os/main.py), so every route
in this app requires it. The published presentation websites under
/p/<site_name>/ are served directly by nginx, entirely outside this app
-- they stay public on purpose, since those are client-facing
deliverables (e.g. a tender pitch), not the Owner's management surface.
"""

import os
import secrets
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

_security = HTTPBasic()

_CSRF_CHECKED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def require_owner(credentials: HTTPBasicCredentials = Depends(_security)) -> str:
    """Fail closed: if OWNER_USERNAME/OWNER_PASSWORD aren't configured at
    all, every request is rejected rather than silently accepted -- an
    unconfigured deployment must not be an open one."""
    expected_username = os.environ.get("OWNER_USERNAME", "")
    expected_password = os.environ.get("OWNER_PASSWORD", "")
    username_ok = bool(expected_username) and secrets.compare_digest(credentials.username, expected_username)
    password_ok = bool(expected_password) and secrets.compare_digest(credentials.password, expected_password)
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Owner credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def _hostname_of(value: str):
    try:
        return urlparse(value).hostname
    except ValueError:
        return None


def verify_csrf(request: Request) -> None:
    """CSRF-equivalent defense chosen instead of a session/token scheme,
    since Basic Auth has no session of its own to carry a synchronizer
    token in: verify the Origin (falling back to Referer) header on every
    state-changing request actually names this same host. A cross-site
    page triggering a background POST here will carry its own Origin, not
    ours, so this rejects it the same way a CSRF token would -- without
    introducing cookies/session state this app doesn't otherwise need."""
    if request.method not in _CSRF_CHECKED_METHODS:
        return
    expected_host = request.url.hostname
    candidate = request.headers.get("origin") or request.headers.get("referer")
    candidate_host = _hostname_of(candidate) if candidate else None
    if candidate_host is None or candidate_host != expected_host:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request rejected: missing or mismatched Origin/Referer header",
        )
