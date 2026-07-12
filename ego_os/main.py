import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional

import markdown as md
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

load_dotenv()

from ego_os import agent_routes, automation_bridge, employees, skills, store, tools, worker  # noqa: E402
from ego_os.auth import require_owner, verify_csrf  # noqa: E402

app = FastAPI(title="Ego OS", dependencies=[Depends(require_owner), Depends(verify_csrf)])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Mounted as a genuinely separate ASGI sub-application -- app.mount()
# deliberately bypasses the parent app's global require_owner/verify_csrf
# dependencies, which is exactly right here: the Windows Runner Agent is a
# machine credential (its own token, checked entirely by
# automation/control_server.js) rather than the human Owner, so it must
# never need (or be able to abuse) Owner Basic Auth. See
# ego_os/agent_routes.py's own docstring for the full reasoning.
app.mount("/agent", agent_routes.app)

_STATIC_DIR = Path(__file__).parent / "static"


@app.get("/static/{filename}")
def static_asset(filename: str):
    """A single, explicit route rather than a StaticFiles mount -- mounting
    StaticFiles as a sub-application would bypass the app-level
    require_owner/verify_csrf dependencies (they attach to path operations,
    not to a Mount()'d ASGI app), which would make ego_os/static/ the one
    unauthenticated directory in an app whose whole security model is
    "every route requires Owner auth". Path-traversal-safe: resolves and
    confirms containment before ever opening a file, exactly like the
    existing /tasks/{id}/artifacts/{filename} download route."""
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=404, detail="not found")
    resolved = (_STATIC_DIR / filename).resolve()
    if not str(resolved).startswith(str(_STATIC_DIR.resolve()) + "\\") and not str(resolved).startswith(str(_STATIC_DIR.resolve()) + "/"):
        raise HTTPException(status_code=404, detail="not found")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="not found")
    media_type = "text/css" if resolved.suffix == ".css" else "application/javascript" if resolved.suffix == ".js" else "application/octet-stream"
    return FileResponse(resolved, media_type=media_type)

# Safe file intake (v0.4.1). Matches nginx's client_max_body_size on
# production, but enforced here too since the app must not rely solely on
# an infra-level limit that doesn't apply to local/dev runs.
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
_UPLOAD_MAGIC = {
    ".zip": (b"PK\x03\x04", b"PK\x05\x06"),  # PK\x05\x06 is a valid empty archive
    ".pdf": (b"%PDF-",),
}


def _validate_and_stage_attachment(attachment: UploadFile) -> Path:
    """Validate extension, real file-type signature, and size *before* the
    task exists at all -- an invalid upload must reject cleanly with no
    task ever created, not leave an inconsistent row with no explanation
    (found live: the task used to be created first, so a rejected
    attachment left it stuck at 'intake' forever). Streams and checks in
    chunks rather than trusting Content-Length, and stages into a temp
    directory so nothing lands under the real per-task upload path until
    validation has fully passed."""
    filename = Path(attachment.filename).name
    ext = Path(filename).suffix.lower()
    if not filename or ext not in _UPLOAD_MAGIC:
        raise HTTPException(status_code=400, detail="attachment must be a .zip of slide images or a .pdf deck")

    tools.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(dir=tools.UPLOADS_DIR, prefix="_staging-"))
    target = staging_dir / filename
    written = 0
    magic_ok = False
    try:
        with target.open("wb") as f:
            while True:
                chunk = attachment.file.read(1024 * 1024)
                if not chunk:
                    break
                if not magic_ok:
                    if not chunk.startswith(_UPLOAD_MAGIC[ext]):
                        raise HTTPException(
                            status_code=400,
                            detail=f"attachment does not look like a real {ext} file",
                        )
                    magic_ok = True
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"attachment exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit",
                    )
                f.write(chunk)
        if written == 0:
            raise HTTPException(status_code=400, detail="attachment is empty")
    except HTTPException:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    return target


def _render_text_artifact(result_text: str) -> dict:
    """Turn a specialist's raw text result into a typed, rendered artifact
    instead of a plain text blob, per the roadmap's Structured Artifacts
    capability: every task output -- the main text result and any
    generated files -- is one durable, typed artifact record, not a
    special-cased "Result" section plus a separate ad hoc file list."""
    html = md.markdown(
        result_text,
        extensions=["tables", "fenced_code", "sane_lists", "nl2br"],
    )
    if "<table" in html:
        kind = "Table Report"
    elif re.search(r"<h[1-4]", html):
        kind = "Report"
    elif "<ul>" in html or "<ol>" in html:
        kind = "Checklist"
    else:
        kind = "Document"
    return {"type": "text", "kind": kind, "html": html}


@app.on_event("startup")
def on_startup():
    store.init_db()
    employees.sync_from_registry()
    store.ensure_default_project()
    # A task left 'running' from before this boot was interrupted by the
    # restart -- mark it failed rather than leaving it stuck forever.
    # A task still 'queued' never actually started, so it's safe to requeue.
    worker.recover_interrupted_tasks()
    worker.start()


@app.on_event("shutdown")
def on_shutdown():
    worker.stop()


@app.get("/")
def command(request: Request):
    """Strategy / Command Interface (v0.3): where the Owner submits work,
    approves the mandate, and reviews pending Employee Creation Proposals --
    the action surface, split out from the observe-only Dashboard."""
    return templates.TemplateResponse(
        request,
        "command.html",
        {
            "projects": store.get_projects(),
            "mandate": store.get_current_mandate(),
            "proposals": store.get_pending_proposals(),
        },
    )


@app.get("/dashboard")
def dashboard(request: Request):
    """Operations Dashboard (v0.3): observe-only -- roster, tasks, cost.
    No POST actions live here, so a future thin/mobile client could read
    this surface without server-rendered-page assumptions leaking in."""
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "employees": store.get_employees(),
            "tasks": store.get_tasks(),
            "projects": store.get_projects(),
            "total_cost": store.get_total_cost(),
        },
    )


_RUNNER_COMMAND_ROUTE_NAMES = {"start", "pause", "resume", "stop-after-stage", "emergency-stop"}
_TASK_ACTION_ROUTE_NAMES = {"hold", "unhold", "retry", "skip"}
_CONFIRM_REQUIRED_ACTIONS = {"emergency-stop", "skip", "retry"}


def _current_task_detail(current_task: dict | None) -> dict | None:
    """Full task record (result.sessions[], handoff, etc.) for whatever
    /api/status reports as the current task -- fetched once and reused for
    both the session/model display and the latest-log tail. Returns None
    (never raises) if there's no current task or the control server can't
    be reached, so the page still renders without this section."""
    if not current_task or not isinstance(current_task, dict):
        return None
    detail = automation_bridge.get_task(current_task["id"])
    if not detail["ok"] or not detail["data"]:
        return None
    return detail["data"].get("task")


def _latest_log_tail(task_detail: dict | None) -> dict | None:
    """Best-effort: the current task's own most recent session log, tailed
    through the control server's existing secret-masked /api/logs route."""
    if not task_detail:
        return None
    sessions = ((task_detail.get("result") or {}).get("sessions")) or []
    if not sessions:
        return None
    log_path = sessions[-1].get("log")
    if not log_path:
        return None
    basename = log_path.replace("\\", "/").rsplit("/", 1)[-1]
    logs = automation_bridge.get_logs(basename)
    if not logs["ok"] or not logs["data"]:
        return None
    return logs["data"]


def _group_tasks_casually(tasks: list) -> list:
    """Groups an already-summarized task list (each row already carries
    group_key/group_name/group_casual_summary/display_summary from
    runner_control.summarizeTask()) into casual project cards -- never
    re-derives the id-prefix -> project mapping itself (that logic lives
    in exactly one place, automation/project_groups.js). Order: first
    appearance in the list this server already returned, stable and
    simple rather than re-implementing a priority sort Python-side."""
    groups: dict[str, dict] = {}
    for t in tasks:
        key = t.get("group_key") or "other"
        if key not in groups:
            groups[key] = {
                "key": key,
                "name": t.get("group_name") or "Другое",
                "casual_summary": t.get("group_casual_summary") or "",
                "tasks": [],
            }
        groups[key]["tasks"].append(t)
    attention_statuses = {"blocked", "waiting_for_auth", "failed", "interrupted"}
    for g in groups.values():
        g["done_count"] = sum(1 for t in g["tasks"] if t.get("status") == "done")
        g["total_count"] = len(g["tasks"])
        g["needs_attention"] = any(t.get("status") in attention_statuses for t in g["tasks"])
    return list(groups.values())


@app.get("/automation")
def automation_page(request: Request):
    """Owner-authenticated view of the autonomous task runner -- reads the
    EXISTING RUNNER-CONTROL-UI control server (automation/control_server.js)
    over its own local, loopback-only API; never re-implements the runner's
    state machine or task loading. Degrades to an honest 'runner control
    server unavailable' state rather than a 500 when that server isn't
    running (e.g. this exact test environment, or before the systemd unit
    is installed). This is the ONLY UI for the runner -- the standalone
    local dashboard (automation/web/) was removed since the control server
    runs co-located with this app and was never reachable from the Owner's
    own browser."""
    status = automation_bridge.get_status()
    tasks_result = automation_bridge.get_tasks()
    events_result = automation_bridge.get_events(50)
    usage_result = automation_bridge.get_usage()

    current_task = (status.get("data") or {}).get("current_task") if status["ok"] else None
    task_detail = _current_task_detail(current_task)
    last_session = ((task_detail or {}).get("result") or {}).get("sessions", [])[-1:] if task_detail else []
    tasks = (tasks_result.get("data") or {}).get("tasks", []) if tasks_result["ok"] else []
    return templates.TemplateResponse(
        request,
        "automation.html",
        {
            "control_server_available": status["ok"],
            "runner_state": (status.get("data") or {}).get("runner_state") if status["ok"] else None,
            "runner_pid": (status.get("data") or {}).get("pid") if status["ok"] else None,
            "runner_updated_at": (status.get("data") or {}).get("updated_at") if status["ok"] else None,
            "runner_reason": (status.get("data") or {}).get("reason") if status["ok"] else None,
            "current_task": current_task,
            "current_task_detail": task_detail,
            "last_session": last_session[0] if last_session else None,
            "tasks": tasks,
            "groups": _group_tasks_casually(tasks),
            "usage": (usage_result.get("data") or {}).get("usage") if usage_result["ok"] else None,
            "events": list(reversed((events_result.get("data") or {}).get("events", []))) if events_result["ok"] else [],
            "latest_log": _latest_log_tail(task_detail),
            # Windows Runner Agent (SERVER-RUNNER-DARK-UI): Claude Code
            # cannot run on this VPS (confirmed external blocker) -- the
            # queue/state machine/control API stay here, execution moved to
            # the Owner's own machine. "online" is a plain heartbeat-recency
            # check (control_server.js's isAgentOnline), never inferred.
            "agents": (status.get("data") or {}).get("agents", []) if status["ok"] else [],
            "any_agent_online": (status.get("data") or {}).get("any_agent_online", False) if status["ok"] else False,
        },
    )


@app.post("/automation/runner/{command}")
def automation_runner_command(command: str, confirm: str = Form(None)):
    if command not in _RUNNER_COMMAND_ROUTE_NAMES:
        raise HTTPException(status_code=404, detail="unknown runner command")
    body = {}
    if command in _CONFIRM_REQUIRED_ACTIONS:
        body["confirm"] = confirm in ("true", "on", "1")
    automation_bridge.post_runner_command(command, body)
    return RedirectResponse(url="/automation", status_code=303)


@app.post("/automation/tasks/{task_id}/{action}")
def automation_task_action(task_id: str, action: str, reason: str = Form(None), confirm: str = Form(None)):
    if action not in _TASK_ACTION_ROUTE_NAMES:
        raise HTTPException(status_code=404, detail="unknown task action")
    if not automation_bridge.is_safe_task_id(task_id):
        raise HTTPException(status_code=400, detail="invalid task id")
    body = {}
    if reason:
        body["reason"] = reason
    if action in _CONFIRM_REQUIRED_ACTIONS:
        body["confirm"] = confirm in ("true", "on", "1")
    automation_bridge.post_task_action(task_id, action, body)
    return RedirectResponse(url="/automation", status_code=303)


@app.post("/automation/tasks/reorder")
async def automation_tasks_reorder(request: Request):
    """The one JS-initiated call on this page (drag-and-drop can't be
    expressed as a plain HTML form) -- JSON body, not Form(), since it's
    called via fetch() from automation.js, not submitted by a <form>. The
    page's own Origin/Referer already satisfies verify_csrf's global
    dependency, exactly like every other state-changing route here."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")
    order = body.get("order") if isinstance(body, dict) else None
    if not isinstance(order, list) or not order:
        raise HTTPException(status_code=400, detail="'order' must be a non-empty list of task ids")
    result = automation_bridge.post_reorder(order)
    if not result["ok"]:
        raise HTTPException(status_code=409, detail=(result.get("data") or {}).get("error") or result.get("error") or "reorder failed")
    return {"ok": True}


@app.get("/employees/{employee_id}")
def employee_detail(request: Request, employee_id: str):
    employee = store.get_employee(employee_id)
    if employee is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request,
        "employee.html",
        {
            "employee": employee,
            "capabilities": json.loads(employee["required_capabilities"]),
            "permissions": json.loads(employee["permissions"]),
            "history": store.get_employee_task_history(employee_id),
        },
    )


@app.get("/projects/{project_id}/memory")
def project_memory(request: Request, project_id: int):
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request,
        "project_memory.html",
        {"project": project, "entries": store.get_memory_entries(project_id)},
    )


@app.get("/skills")
def skills_list(request: Request):
    """Read-only (SR-04): lists every Skill under the Registry, valid or
    not. Purely observational -- viewing this page must not itself
    change the audit trail (a read-only UI mutating state as a side
    effect of being viewed is exactly the bug this route used to have).
    'last_check' reflects the last genuine operational validation (a
    real Skill resolution during task execution, or Registry sync),
    never a page view. This route never mutates the Registry, installs
    anything, or executes Skill content."""
    entries = skills.list_skills()
    rows = []
    for entry in entries:
        if "error" in entry:
            rows.append({"id": entry["id"], "version": entry["version"], "error": entry["error"]})
            continue
        last_check = store.get_last_skill_check(entry["id"])
        requirements = entry.get("requirements") or {}
        rows.append({
            "id": entry["id"],
            "name": entry.get("name"),
            "version": entry["version"],
            "trust_state": entry["trust"]["state"],
            "lifecycle_state": entry["lifecycle"]["state"],
            "origin_type": (entry.get("origin") or {}).get("type"),
            "license": (entry.get("origin") or {}).get("license"),
            "digest_status": "verified",
            "employees": store.get_employees_using_skill(entry["id"], entry["version"]),
            "requirements": requirements,
            "permissions_required": requirements.get("permissions", []),
            "last_check": last_check["created_at"] if last_check else None,
        })
    return templates.TemplateResponse(request, "skills.html", {"skills": rows})


@app.get("/skills/{skill_id}/{version}")
def skill_detail(request: Request, skill_id: str, version: str):
    """Read-only manifest detail (SR-04). A revoked Skill stays visible
    here -- it's just never resolved for execution
    (get_exact_version/resolve_compatible_version still fail closed on
    it). Never executes Skill content, never mutates the Registry."""
    try:
        manifest = skills.get_manifest_for_display(skill_id, version)
    except skills.SkillNotFoundError:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request,
        "skill_detail.html",
        {
            "manifest": manifest,
            "employees": store.get_employees_using_skill(skill_id, version),
            "audit_events": store.get_skill_audit_events(skill_id),
        },
    )


@app.post("/projects")
def submit_project(name: str = Form(...), vision: str = Form("")):
    store.create_project(name.strip(), vision.strip() or None)
    return RedirectResponse(url="/", status_code=303)


@app.post("/mandate")
def submit_mandate(mission: str = Form(...), starting_capital: float = Form(...), risk_policy: str = Form(...)):
    """The Owner authoring and submitting this form *is* the Stage 1
    Formation approval per architecture/006: 'the Owner approves the
    mission, the starting capital, and the risk policy as a single
    package.' Each submission is a new version, never an overwrite."""
    store.create_mandate(mission.strip(), starting_capital, risk_policy.strip())
    return RedirectResponse(url="/", status_code=303)


@app.post("/proposals/{proposal_id}/approve")
def approve_proposal(proposal_id: int):
    proposal = store.get_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404)
    store.update_proposal_status(proposal_id, "approved")
    store.update_task_status(proposal["task_id"], "gap_approved")
    return RedirectResponse(url="/", status_code=303)


@app.post("/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: int):
    proposal = store.get_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404)
    store.update_proposal_status(proposal_id, "rejected")
    store.update_task_status(proposal["task_id"], "gap_rejected")
    return RedirectResponse(url="/", status_code=303)


@app.post("/tasks")
def submit_task(
    request_text: str = Form(...),
    project_id: int = Form(...),
    attachment: Optional[UploadFile] = File(None),
):
    """A file attachment is optional and currently only used by the
    Presentation Website capability (v0.4): a .zip of slide images or a
    .pdf deck, staged before the task exists so a rejected upload never
    leaves an inconsistent task row.

    The Task Lifecycle itself now runs on the background worker (v0.4.1)
    instead of inline here -- this handler only validates, persists, and
    enqueues, so a heavy task (multiple LLM calls, PDF rendering) can no
    longer hold an HTTP request open long enough to hit a proxy timeout
    (found live: nginx killed a real client connection at 60s while a
    task that took ~96s kept running server-side)."""
    if store.get_project(project_id) is None:
        project_id = store.ensure_default_project()

    staged_attachment = None
    if attachment is not None and attachment.filename:
        staged_attachment = _validate_and_stage_attachment(attachment)

    task_id = store.create_task(request_text, project_id)
    if staged_attachment is not None:
        final_dir = tools.UPLOADS_DIR / str(task_id)
        final_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged_attachment), str(final_dir / staged_attachment.name))
        shutil.rmtree(staged_attachment.parent, ignore_errors=True)

    worker.enqueue(task_id)
    return RedirectResponse(url=f"/tasks/{task_id}", status_code=303)


@app.get("/tasks/{task_id}")
def task_detail(request: Request, task_id: int):
    task = store.get_task(task_id)
    report = store.get_report(task_id)
    artifacts = None
    qa_html = None
    if report:
        qa_html = md.markdown(report["qa_note"], extensions=["sane_lists", "nl2br"])
        artifacts = [_render_text_artifact(report["result_text"])] + report["artifacts"]
    proposal = store.get_proposal_by_task(task_id) if task["status"] in (
        "awaiting_approval", "gap_approved", "gap_rejected"
    ) else None
    return templates.TemplateResponse(
        request,
        "task.html",
        {"task": task, "report": report, "artifacts": artifacts, "qa_html": qa_html, "proposal": proposal},
    )


@app.get("/tasks/{task_id}/artifacts/{filename}")
def download_artifact(task_id: int, filename: str):
    task_dir = (tools.GENERATED_DIR / str(task_id)).resolve()
    target = (task_dir / filename).resolve()
    if not target.is_relative_to(task_dir) or not target.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(target, filename=filename)


def _excerpt(text, limit=140):
    if not text:
        return ""
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


@app.get("/assets")
def assets_list(request: Request):
    """Owner Asset Inbox (DA-02, architecture/013): read-only list of every
    Digital Asset, grouped by lifecycle status so Candidates awaiting an
    Owner decision are never mixed in with settled Assets. Viewing this
    page never mutates anything."""
    project_names = {p["id"]: p["name"] for p in store.get_projects()}
    groups = {"candidate": [], "accepted": [], "internally_validated": [], "rejected_archived": []}
    for asset in store.get_assets():
        row = {
            "id": asset["id"],
            "title": asset["title"],
            "asset_type": asset["asset_type"],
            "project_name": project_names.get(asset["project_id"], "—"),
            "source_task_id": asset["source_task_id"],
            "status": asset["status"],
            "created_at": asset["created_at"],
            "value_thesis_excerpt": _excerpt(asset["value_thesis"]),
        }
        bucket = "rejected_archived" if asset["status"] in ("rejected", "archived") else asset["status"]
        groups.setdefault(bucket, []).append(row)
    return templates.TemplateResponse(request, "assets.html", {"groups": groups})


@app.get("/assets/{asset_id}")
def asset_detail(request: Request, asset_id: int):
    """Owner Asset Inbox detail (DA-02): provenance, evidence, value/
    monetization thesis, and the full append-only event history for one
    Digital Asset. Read-only -- never mutates the Asset or its events."""
    asset = store.get_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404)
    project = store.get_project(asset["project_id"]) if asset["project_id"] else None
    return templates.TemplateResponse(
        request,
        "asset_detail.html",
        {
            "asset": asset,
            "project": project,
            "events": store.get_asset_events(asset_id),
        },
    )


@app.post("/assets/{asset_id}/accept")
def accept_asset(asset_id: int):
    """The only mechanism that moves a Candidate (or a previously-rejected
    Asset) to `accepted` (architecture/013 Section 10) -- a thin wrapper
    over the same store.transition_asset enforcement DA-01 already built,
    with no bypass and no provenance edit. A transition that isn't
    currently allowed (e.g. the Asset is already `accepted` or already
    `internally_validated`) raises store.DigitalAssetError, which is
    reported as a clear 400 here rather than crashing or silently
    duplicating the decision."""
    if store.get_asset(asset_id) is None:
        raise HTTPException(status_code=404)
    try:
        store.transition_asset(asset_id, "accepted", "owner_accepted", "owner")
    except store.DigitalAssetError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RedirectResponse(url=f"/assets/{asset_id}", status_code=303)


@app.post("/assets/{asset_id}/reject")
def reject_asset(asset_id: int):
    """The only mechanism that moves a Candidate to `rejected`. Never
    deletes the Asset (ADR-0007 decision 7) -- only appends a fresh
    owner_rejected event via store.transition_asset. A transition that
    isn't currently allowed raises store.DigitalAssetError, reported here
    as a clear 400."""
    if store.get_asset(asset_id) is None:
        raise HTTPException(status_code=404)
    try:
        store.transition_asset(asset_id, "rejected", "owner_rejected", "owner")
    except store.DigitalAssetError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RedirectResponse(url=f"/assets/{asset_id}", status_code=303)
