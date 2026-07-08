import re
from pathlib import Path

import markdown as md
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

load_dotenv()

from ego_os import employees, lifecycle, store  # noqa: E402

app = FastAPI(title="Ego OS")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _render_artifact(result_text: str) -> dict:
    """Turn a specialist's raw text result into a labeled, rendered artifact
    instead of a plain text blob, per the roadmap's v0.2 emphasis on
    structured artifacts over inline text."""
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
    return {"html": html, "kind": kind}


@app.on_event("startup")
def on_startup():
    store.init_db()
    employees.sync_from_registry()
    store.ensure_default_project()


@app.get("/")
def home(request: Request):
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "employees": store.get_employees(),
            "tasks": store.get_tasks(),
            "total_cost": store.get_total_cost(),
        },
    )


@app.post("/tasks")
def submit_task(request_text: str = Form(...)):
    project_id = store.ensure_default_project()
    task_id = store.create_task(request_text, project_id)
    lifecycle.run(task_id, project_id, request_text)
    return RedirectResponse(url=f"/tasks/{task_id}", status_code=303)


@app.get("/tasks/{task_id}")
def task_detail(request: Request, task_id: int):
    task = store.get_task(task_id)
    report = store.get_report(task_id)
    result = _render_artifact(report["result_text"]) if report else None
    qa_html = md.markdown(report["qa_note"], extensions=["sane_lists", "nl2br"]) if report else None
    return templates.TemplateResponse(
        request,
        "task.html",
        {"task": task, "report": report, "result": result, "qa_html": qa_html},
    )
