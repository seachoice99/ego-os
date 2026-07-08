from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

load_dotenv()

from ego_os import employees, lifecycle, store  # noqa: E402

app = FastAPI(title="Ego OS")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.on_event("startup")
def on_startup():
    store.init_db()
    employees.sync_from_registry()


@app.get("/")
def home(request: Request):
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "employees": store.get_employees(),
            "tasks": store.get_tasks(),
        },
    )


@app.post("/tasks")
def submit_task(request_text: str = Form(...)):
    task_id = store.create_task(request_text)
    lifecycle.run(task_id, request_text)
    return RedirectResponse(url=f"/tasks/{task_id}", status_code=303)


@app.get("/tasks/{task_id}")
def task_detail(request: Request, task_id: int):
    task = store.get_task(task_id)
    report = store.get_report(task_id)
    return templates.TemplateResponse(
        request,
        "task.html",
        {"task": task, "report": report},
    )
