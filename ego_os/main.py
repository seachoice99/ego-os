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

from ego_os import employees, skills, store, tools, worker  # noqa: E402
from ego_os.auth import require_owner, verify_csrf  # noqa: E402

app = FastAPI(title="Ego OS", dependencies=[Depends(require_owner), Depends(verify_csrf)])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

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
