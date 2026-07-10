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

from ego_os import employees, lifecycle, store, tools  # noqa: E402
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
    .pdf deck, saved before the lifecycle runs so a specialist's tool call
    can find it by task_id."""
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

    lifecycle.run(task_id, project_id, request_text)
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
