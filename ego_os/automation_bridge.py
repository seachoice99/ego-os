"""Thin, mostly-read bridge from Ego OS to the local runner control server
(automation/control_server.js). Deliberately does not re-implement task
loading, the runner's state machine, or command validation -- it only
calls that server's own existing HTTP API and shapes the result for a
template. Every function degrades to an explicit "unavailable" result
rather than raising, so a control server that isn't running (or isn't
installed at all, e.g. in the test environment) never turns /automation
into a 500 -- the same fail-closed-but-not-fail-crashed principle the
runner itself already uses for a missing/malformed task file.

ADR-0013 (superseding ADR-0009/architecture/015's blanket POST
prohibition, narrowly, for this exact loopback scenario): CONTROL_SERVER_URL
is validated -- after real URL parsing and DNS resolution, never by a
string-prefix check -- before every single call, not just at import time.
A value that fails validation (a non-loopback host, embedded credentials,
an unapproved port, an unparseable URL) makes every call in this module
fail closed to "unavailable", exactly like an unreachable control server
does today. `EGO_OS_CONTROL_SERVER_URL` can therefore only ever narrow the
target within the loopback/approved-port constraint -- it can never point
this module at an external host.
"""

import ipaddress
import os
import re
import socket
from urllib.parse import urlparse

import httpx

CONTROL_SERVER_URL = os.environ.get("EGO_OS_CONTROL_SERVER_URL", "http://127.0.0.1:4756")
_TIMEOUT = 5.0

# ADR-0013: the control server's one documented, approved port
# (automation/control_server.js's own default). Not env-configurable --
# that would reintroduce exactly the "arbitrary external configuration"
# risk this allowlist exists to close. A test that genuinely needs a
# different port monkeypatches this set directly.
_APPROVED_PORTS = {4756}


class ControlServerConfigError(Exception):
    """Raised (and always caught internally, never propagated to a caller)
    when CONTROL_SERVER_URL fails ADR-0013's validation. Every call site
    in this module fails closed to an "unavailable" result instead of
    letting this escape, exactly like a network-level connection failure
    already does."""


def _resolves_to_loopback_only(hostname: str) -> bool:
    """True only if EVERY address this hostname resolves to is a loopback
    address -- a hostname that resolves to a mix of loopback and non-loopback
    addresses (or fails to resolve at all) is rejected, never partially
    trusted."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except (socket.gaierror, UnicodeError):
        return False
    if not infos:
        return False
    for info in infos:
        raw_ip = info[4][0]
        try:
            addr = ipaddress.ip_address(raw_ip.split("%", 1)[0])  # strip a possible IPv6 zone id, e.g. "%eth0"
        except ValueError:
            return False
        if not addr.is_loopback:
            return False
    return True


def _validate_control_server_url(url: str) -> None:
    """Raises ControlServerConfigError for anything that is not a loopback
    host, on an approved port, with no embedded credentials. Every check
    happens after real URL parsing (urlparse) and, for the host, real DNS
    resolution -- never a string-prefix match on the configured value."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ControlServerConfigError(f"unsupported scheme: {parsed.scheme!r}")
    if parsed.username is not None or parsed.password is not None:
        raise ControlServerConfigError("URL must not contain embedded credentials (userinfo)")
    hostname = parsed.hostname
    if not hostname:
        raise ControlServerConfigError("URL has no hostname")
    if not _resolves_to_loopback_only(hostname):
        raise ControlServerConfigError(f"host {hostname!r} does not resolve exclusively to a loopback address")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in _APPROVED_PORTS:
        raise ControlServerConfigError(f"port {port} is not on the approved allowlist {_APPROVED_PORTS!r}")


def _safe_base_url():
    """Re-validates CONTROL_SERVER_URL on every call (cheap: a local
    DNS/hosts-file lookup, no network round-trip to the control server
    itself) rather than once at import time, so a value that becomes
    invalid after the process starts (or in a misconfigured production
    environment) is caught on the very next call, not just the first.
    Returns None -- callers must fail closed -- on any validation failure."""
    try:
        _validate_control_server_url(CONTROL_SERVER_URL)
        return CONTROL_SERVER_URL
    except ControlServerConfigError:
        return None


# Mirrors automation/runner_control.js's SAFE_TASK_ID_RE exactly -- a
# second, independent validation on the Python side before a task id ever
# reaches an HTTP call, not a replacement for the control server's own check.
_SAFE_TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def is_safe_task_id(task_id: str) -> bool:
    return bool(task_id) and len(task_id) <= 128 and bool(_SAFE_TASK_ID_RE.match(task_id))


def _get(path: str, params: dict | None = None) -> dict:
    base = _safe_base_url()
    if base is None:
        return {"ok": False, "status_code": None, "data": None, "error": "control server URL failed safety validation"}
    try:
        # follow_redirects is explicitly False (ADR-0013 point 5) -- never
        # relying on httpx's own default, which could change. A redirect
        # response is treated as any other non-2xx/3xx-follow response:
        # ok=False, never silently chased to a new destination.
        resp = httpx.get(f"{base}{path}", params=params, timeout=_TIMEOUT, follow_redirects=False)
        try:
            data = resp.json()
        except ValueError:
            data = None
        # 2xx only -- a 3xx here would mean a redirect response arrived
        # (follow_redirects=False never chases it), and ADR-0013 requires
        # treating that as a rejection, not a success, since this control
        # server never legitimately redirects.
        return {"ok": 200 <= resp.status_code < 300, "status_code": resp.status_code, "data": data}
    except httpx.HTTPError as exc:
        return {"ok": False, "status_code": None, "data": None, "error": str(exc)}


def _post(path: str, json_body: dict | None = None) -> dict:
    base = _safe_base_url()
    if base is None:
        return {"ok": False, "status_code": None, "data": None, "error": "control server URL failed safety validation"}
    try:
        resp = httpx.post(f"{base}{path}", json=json_body or {}, timeout=_TIMEOUT, follow_redirects=False)
        try:
            data = resp.json()
        except ValueError:
            data = None
        # 2xx only -- a 3xx here would mean a redirect response arrived
        # (follow_redirects=False never chases it), and ADR-0013 requires
        # treating that as a rejection, not a success, since this control
        # server never legitimately redirects.
        return {"ok": 200 <= resp.status_code < 300, "status_code": resp.status_code, "data": data}
    except httpx.HTTPError as exc:
        return {"ok": False, "status_code": None, "data": None, "error": str(exc)}


def get_status() -> dict:
    return _get("/api/status")


def get_tasks() -> dict:
    return _get("/api/tasks")


def get_task(task_id: str) -> dict:
    if not is_safe_task_id(task_id):
        return {"ok": False, "status_code": None, "data": None, "error": "invalid task id"}
    return _get(f"/api/tasks/{task_id}")


def get_events(limit: int = 100) -> dict:
    return _get("/api/events", params={"limit": limit})


def get_logs(file: str) -> dict:
    return _get("/api/logs", params={"file": file})


def get_usage() -> dict:
    return _get("/api/usage")


_RUNNER_COMMANDS = {"start", "pause", "resume", "stop-after-stage", "emergency-stop"}


def post_runner_command(command: str, body: dict | None = None) -> dict:
    if command not in _RUNNER_COMMANDS:
        return {"ok": False, "status_code": None, "data": None, "error": f"unknown runner command: {command}"}
    return _post(f"/api/runner/{command}", body)


_TASK_ACTIONS = {"hold", "unhold", "retry", "skip"}


def post_task_action(task_id: str, action: str, body: dict | None = None) -> dict:
    if not is_safe_task_id(task_id):
        return {"ok": False, "status_code": None, "data": None, "error": "invalid task id"}
    if action not in _TASK_ACTIONS:
        return {"ok": False, "status_code": None, "data": None, "error": f"unknown task action: {action}"}
    return _post(f"/api/tasks/{task_id}/{action}", body)


def post_reorder(order: list) -> dict:
    """Forwards a new drag-and-drop order to the control server's existing
    POST /api/tasks/reorder -- validated here (every id well-formed) as a
    second, independent check before the control server's own
    validateReorder() (ready-only, depends_on-respecting), not a
    replacement for it."""
    if not isinstance(order, list) or not order or any(not is_safe_task_id(x) for x in order):
        return {"ok": False, "status_code": None, "data": None, "error": "invalid order: must be a non-empty list of valid task ids"}
    return _post("/api/tasks/reorder", {"order": order})
