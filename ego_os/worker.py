"""Background task execution (v0.4.1).

An in-process queue.Queue plus a single background thread, started at
app startup -- no Redis, no Celery, no Docker, matching the current
single-process deployment. POST /tasks only validates the upload and
enqueues; the actual Task Lifecycle (potentially several LLM calls plus
a tool call) now runs on this worker thread instead of blocking the HTTP
response. Found live: nginx's proxy_read_timeout killed a real client
connection on a heavy PDF task that took ~96s to complete server-side --
the request had been holding the entire lifecycle inline.

`process_one` is exposed separately from the loop so tests (and startup
recovery) can run a task synchronously and deterministically, without
needing a real background thread and racy waits.
"""

import queue
import threading

from ego_os import lifecycle, store

_queue: "queue.Queue[int]" = queue.Queue()
_worker_thread = None
_stop_event = threading.Event()


def enqueue(task_id: int) -> None:
    _queue.put(task_id)


def process_one(task_id: int) -> None:
    """Run exactly one task through the Task Lifecycle. Idempotent by
    construction: a task is only ever actually run while its run_state is
    still 'queued' -- already running/completed/failed/cancelled is a
    no-op, so the same task_id landing in the queue twice (or a manual
    call racing the worker thread) can never produce a duplicate report
    or double-run a tool call."""
    task = store.get_task(task_id)
    if task is None or task["run_state"] != "queued":
        return
    store.set_task_run_state(task_id, "running")
    try:
        lifecycle.run(task_id, task["project_id"], task["request_text"])
    except store.BudgetError as exc:
        # ADR-0016: automatic overspend is never permitted -- a reservation
        # that would exceed the task's own sub-limit or the remaining
        # global balance stops the call before it happens. This is a real,
        # expected outcome (not a bug), so it still gets ADR-0014's usual
        # terminal-state + Report treatment, centralized here rather than
        # at each of lifecycle.py's several model_provider.complete() call
        # sites -- every one of them raises the same exception type.
        current = store.get_task(task_id)
        if current is not None and current["status"] not in store.TASK_TERMINAL_STATUSES:
            reason = {"category": "budget_exhausted", "detail": str(exc)}
            store.update_task_status(task_id, "failed", terminal_reason=reason)
            if store.get_report(task_id) is None:
                store.create_report(
                    task_id=task_id, employees_involved=["orchestrator"],
                    timeline=[{"step": "budget", "employee": "system", "detail": str(exc)}],
                    input_tokens=0, output_tokens=0, cost=0.0, result_text=None, qa_note=None,
                    terminal_status="failed", terminal_reason=reason,
                )
        store.set_task_run_state(task_id, "failed", error_message=str(exc))
    except Exception as exc:
        store.set_task_run_state(task_id, "failed", error_message=str(exc))
    else:
        # lifecycle.run() already drove the fine-grained `status` through
        # to its real terminal value (delivered/awaiting_approval/...);
        # run_state only needs to record that the worker itself finished
        # without crashing.
        store.set_task_run_state(task_id, "completed")


def _worker_loop():
    while not _stop_event.is_set():
        try:
            task_id = _queue.get(timeout=1)
        except queue.Empty:
            continue
        try:
            process_one(task_id)
        finally:
            _queue.task_done()


def start():
    """Idempotent: calling start() when a thread is already alive is a
    no-op, so a repeated startup event (e.g. FastAPI's lifespan handling
    in some reload scenarios) never spawns a second worker thread."""
    global _worker_thread
    if _worker_thread is not None and _worker_thread.is_alive():
        return
    _stop_event.clear()
    _worker_thread = threading.Thread(target=_worker_loop, name="ego-os-worker", daemon=True)
    _worker_thread.start()


def stop():
    _stop_event.set()


def recover_interrupted_tasks():
    """Called once at startup, before start(): a task left at 'running'
    from before this boot was interrupted mid-lifecycle by a crash or
    restart and must not stay in that false state forever -- mark it
    failed with a clear, Owner-visible reason instead. A task still at
    'queued' never actually started, so it's always safe to requeue it
    exactly as-is."""
    for task in store.get_tasks_by_run_state("running"):
        store.set_task_run_state(
            task["id"],
            "failed",
            error_message="Interrupted by a server restart before completion. Please resubmit this task.",
        )
    for task in store.get_tasks_by_run_state("queued"):
        enqueue(task["id"])
