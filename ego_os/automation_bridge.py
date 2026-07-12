"""Thin, mostly-read bridge from Ego OS to the local runner control server
(automation/control_server.js). Deliberately does not re-implement task
loading, the runner's state machine, or command validation -- it only
calls that server's own existing HTTP API on 127.0.0.1 and shapes the
result for a template. Every function degrades to an explicit
"unavailable" result rather than raising, so a control server that isn't
running (or isn't installed at all, e.g. in the test environment) never
turns /automation into a 500 -- the same fail-closed-but-not-fail-crashed
principle the runner itself already uses for a missing/malformed task file.

CONTROL_SERVER_URL defaults to the control server's own documented
loopback-only default (automation/control_server.js: 127.0.0.1:4756).
Only ever talks to 127.0.0.1/localhost -- this module has no code path
that accepts an external host.
"""

import os
import re

import httpx

CONTROL_SERVER_URL = os.environ.get("EGO_OS_CONTROL_SERVER_URL", "http://127.0.0.1:4756")
_TIMEOUT = 5.0

# Mirrors automation/runner_control.js's SAFE_TASK_ID_RE exactly -- a
# second, independent validation on the Python side before a task id ever
# reaches an HTTP call, not a replacement for the control server's own check.
_SAFE_TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def is_safe_task_id(task_id: str) -> bool:
    return bool(task_id) and len(task_id) <= 128 and bool(_SAFE_TASK_ID_RE.match(task_id))


def _get(path: str, params: dict | None = None) -> dict:
    try:
        resp = httpx.get(f"{CONTROL_SERVER_URL}{path}", params=params, timeout=_TIMEOUT)
        try:
            data = resp.json()
        except ValueError:
            data = None
        return {"ok": resp.status_code < 400, "status_code": resp.status_code, "data": data}
    except httpx.HTTPError as exc:
        return {"ok": False, "status_code": None, "data": None, "error": str(exc)}


def _post(path: str, json_body: dict | None = None) -> dict:
    try:
        resp = httpx.post(f"{CONTROL_SERVER_URL}{path}", json=json_body or {}, timeout=_TIMEOUT)
        try:
            data = resp.json()
        except ValueError:
            data = None
        return {"ok": resp.status_code < 400, "status_code": resp.status_code, "data": data}
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
