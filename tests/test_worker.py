"""Task states + background worker (v0.4.1): queued -> running ->
completed/failed, worker crash recovery on startup, and idempotent
processing (a task can never be run twice, so it can never produce a
duplicate report).
"""

import sqlite3

import pytest


def test_new_task_starts_queued(app_client, owner_credentials, csrf_headers):
    from ego_os import store

    response = app_client.post(
        "/tasks",
        data={"request_text": "check initial state", "project_id": 1},
        auth=owner_credentials,
        headers=csrf_headers,
    )
    assert response.status_code == 200
    task = store.get_tasks()[0]
    assert task["run_state"] == "queued"
    assert task["error_message"] is None


def test_process_one_transitions_to_completed_on_success(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task):
    from ego_os import store

    fake_model_complete.responses["delegation"] = ("writer", 5, 1, 0.00001)
    fake_model_complete.responses["business_communication"] = ("Done.", 10, 5, 0.00005)
    fake_model_complete.responses["critique"] = ("PASS", 5, 1, 0.00001)

    response = app_client.post(
        "/tasks",
        data={"request_text": "should succeed", "project_id": 1},
        auth=owner_credentials,
        headers=csrf_headers,
        follow_redirects=False,
    )
    task_id = int(response.headers["location"].rsplit("/", 1)[-1])
    process_task(task_id)

    task = store.get_task(task_id)
    assert task["run_state"] == "completed"
    assert task["status"] == "delivered"
    assert store.get_report(task_id) is not None


def test_process_one_marks_failed_on_exception_and_records_message(app_client, owner_credentials, csrf_headers, monkeypatch, process_task):
    from ego_os import lifecycle, store

    def boom(task_id, project_id, request_text):
        raise RuntimeError("simulated lifecycle crash")

    monkeypatch.setattr(lifecycle, "run", boom)

    response = app_client.post(
        "/tasks",
        data={"request_text": "should fail", "project_id": 1},
        auth=owner_credentials,
        headers=csrf_headers,
        follow_redirects=False,
    )
    task_id = int(response.headers["location"].rsplit("/", 1)[-1])
    process_task(task_id)

    task = store.get_task(task_id)
    assert task["run_state"] == "failed"
    assert "simulated lifecycle crash" in task["error_message"]

    # The failure is visible to the Owner on the task page, not swallowed.
    page = app_client.get(f"/tasks/{task_id}", auth=owner_credentials)
    assert "simulated lifecycle crash" in page.text


def test_process_one_is_idempotent_never_runs_twice(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task):
    """Calling process_one a second time for an already-processed task
    must be a no-op -- this is what prevents a duplicate report/artifact,
    since store.create_report would otherwise be called twice for the
    same task_id."""
    from ego_os import store

    fake_model_complete.responses["delegation"] = ("writer", 5, 1, 0.00001)
    fake_model_complete.responses["business_communication"] = ("Done.", 10, 5, 0.00005)
    fake_model_complete.responses["critique"] = ("PASS", 5, 1, 0.00001)

    response = app_client.post(
        "/tasks",
        data={"request_text": "idempotency check", "project_id": 1},
        auth=owner_credentials,
        headers=csrf_headers,
        follow_redirects=False,
    )
    task_id = int(response.headers["location"].rsplit("/", 1)[-1])
    process_task(task_id)
    calls_after_first_run = len(fake_model_complete.calls)

    process_task(task_id)  # second call: must be a no-op
    assert len(fake_model_complete.calls) == calls_after_first_run


def test_create_report_twice_for_same_task_is_rejected_at_db_level(temp_env):
    """Defense in depth below process_one's own guard: the schema itself
    refuses a second report for the same task_id."""
    from ego_os import store

    store.init_db()
    project_id = store.ensure_default_project()
    task_id = store.create_task("dup check", project_id)
    store.create_report(
        task_id=task_id, employees_involved=["writer"], timeline=[], input_tokens=1,
        output_tokens=1, cost=0.0, result_text="first", qa_note="PASS",
    )
    with pytest.raises(sqlite3.IntegrityError):
        store.create_report(
            task_id=task_id, employees_involved=["writer"], timeline=[], input_tokens=1,
            output_tokens=1, cost=0.0, result_text="second", qa_note="PASS",
        )


def test_recover_interrupted_tasks_marks_running_as_failed(temp_env):
    """A task left 'running' from before a restart was interrupted
    mid-lifecycle -- it must not stay in a false 'running' state forever."""
    from ego_os import store, worker

    store.init_db()
    project_id = store.ensure_default_project()
    task_id = store.create_task("interrupted mid-flight", project_id)
    store.set_task_run_state(task_id, "running")

    worker.recover_interrupted_tasks()

    task = store.get_task(task_id)
    assert task["run_state"] == "failed"
    assert "restart" in task["error_message"].lower()


def test_recover_interrupted_tasks_requeues_never_started_tasks(temp_env, fake_model_complete, process_task):
    """A task still 'queued' (the process died before the worker thread
    ever picked it up) never actually started -- safe to requeue as-is,
    and it should process normally once picked up."""
    from ego_os import employees, store, worker

    store.init_db()
    employees.sync_from_registry()  # process_task needs a real roster to staff against
    project_id = store.ensure_default_project()
    task_id = store.create_task("never started before restart", project_id)
    assert store.get_task(task_id)["run_state"] == "queued"

    fake_model_complete.responses["delegation"] = ("writer", 5, 1, 0.00001)
    fake_model_complete.responses["business_communication"] = ("Done.", 10, 5, 0.00005)
    fake_model_complete.responses["critique"] = ("PASS", 5, 1, 0.00001)

    worker.recover_interrupted_tasks()
    # recover_interrupted_tasks() enqueues it on the real queue; drive it
    # through deterministically here rather than waiting on a thread.
    process_task(task_id)

    task = store.get_task(task_id)
    assert task["run_state"] == "completed"
    assert task["status"] == "delivered"
