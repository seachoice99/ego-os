"""Execution observability + Employee version traceability (v0.4.1):
execution_events are written incrementally as the lifecycle proceeds
(not just once at the end like reports.timeline), and a report records
the actual Employee Definition version that performed the work -- stable
even after that employee's YAML is later bumped (ADR-0002)."""

import json


def _submit(app_client, owner_credentials, csrf_headers, request_text, project_id=1):
    response = app_client.post(
        "/tasks",
        data={"request_text": request_text, "project_id": project_id},
        auth=owner_credentials,
        headers=csrf_headers,
        follow_redirects=False,
    )
    return int(response.headers["location"].rsplit("/", 1)[-1])


def test_execution_events_cover_the_full_lifecycle(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task):
    from ego_os import store

    fake_model_complete.responses["delegation"] = ("writer", 5, 1, 0.00001)
    fake_model_complete.responses["business_communication"] = ("Done.", 10, 5, 0.00005)
    fake_model_complete.responses["critique"] = ("PASS", 5, 1, 0.00001)

    task_id = _submit(app_client, owner_credentials, csrf_headers, "Write a short note")
    process_task(task_id)

    events = store.get_execution_events(task_id)
    steps = [e["step"] for e in events]
    assert steps == ["intake", "planning", "staffing", "execution", "qa", "delivery"]

    execution_event = next(e for e in events if e["step"] == "execution")
    assert execution_event["employee_id"] == "writer"
    assert execution_event["employee_version"] is not None
    assert execution_event["model"] == "anthropic/claude-haiku-4.5"
    assert execution_event["duration_ms"] is not None and execution_event["duration_ms"] >= 0
    assert execution_event["cost"] == 0.00005


def test_execution_events_survive_incrementally_even_if_task_later_fails(app_client, owner_credentials, csrf_headers, fake_model_complete, monkeypatch, process_task):
    """The whole point of writing events as they happen: even if the
    lifecycle later raises, the steps that already ran are still on
    record -- not silently lost the way reports.timeline (written once,
    at the very end) would lose them."""
    from ego_os import lifecycle, store

    fake_model_complete.responses["delegation"] = ("writer", 5, 1, 0.00001)

    def crash_after_staffing(*args, **kwargs):
        raise RuntimeError("simulated crash mid-execution")

    monkeypatch.setattr(lifecycle, "_run_specialist", crash_after_staffing)

    task_id = _submit(app_client, owner_credentials, csrf_headers, "Write a short note")
    process_task(task_id)

    task = store.get_task(task_id)
    assert task["run_state"] == "failed"
    assert store.get_report(task_id) is None  # no report was ever written -- crashed first

    # But intake/planning/staffing are still visible, recorded before the crash.
    events = store.get_execution_events(task_id)
    steps = [e["step"] for e in events]
    assert steps == ["intake", "planning", "staffing"]


def test_tool_use_event_has_tool_name_and_json_safe_args(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task):
    from ego_os import store

    fake_model_complete.responses["delegation"] = ("cfo", 5, 1, 0.00001)
    fake_model_complete.responses["cost_accounting"] = (
        'TOOL_REQUEST: create_spreadsheet {"filename": "report.xlsx", "data": [["A","B"],["1","2"]]}',
        10, 5, 0.00005,
    )
    fake_model_complete.responses["critique"] = ("PASS", 5, 1, 0.00001)

    task_id = _submit(app_client, owner_credentials, csrf_headers, "As CFO, create a cost report")
    process_task(task_id)

    events = store.get_execution_events(task_id)
    tool_event = next(e for e in events if e["step"] == "tool_use")
    assert tool_event["tool_name"] == "create_spreadsheet"
    assert tool_event["status"] == "ok"
    # A safe, JSON-serialized representation -- round-trips cleanly, not a raw repr.
    args = json.loads(tool_event["tool_args_summary"])
    assert args["filename"] == "report.xlsx"


def test_employee_version_preserved_after_registry_is_later_bumped(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task):
    """The core ADR-0002 guarantee: updating an employee's YAML later
    must not silently rewrite what an already-delivered report says
    performed the work."""
    from ego_os import store

    fake_model_complete.responses["delegation"] = ("writer", 5, 1, 0.00001)
    fake_model_complete.responses["business_communication"] = ("Done.", 10, 5, 0.00005)
    fake_model_complete.responses["critique"] = ("PASS", 5, 1, 0.00001)

    task_id = _submit(app_client, owner_credentials, csrf_headers, "Write a short note")
    process_task(task_id)

    report = store.get_report(task_id)
    original_version = report["employee_versions"]["writer"]
    assert original_version is not None

    # Simulate a later registry update -- writer.yaml bumped to a new version.
    writer = store.get_employee("writer")
    store.upsert_employee(
        id="writer", name=writer["name"], title=writer["title"], department=writer["department"],
        mission=writer["mission"], required_capabilities=json.loads(writer["required_capabilities"]),
        permissions=json.loads(writer["permissions"]), version="99.0",
    )

    assert store.get_employee("writer")["version"] == "99.0"  # the registry moved on...
    report_after_bump = store.get_report(task_id)
    assert report_after_bump["employee_versions"]["writer"] == original_version  # ...but history didn't
