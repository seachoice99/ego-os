"""ADR-0014: QA is a real gate, and every terminal ProductTask state gets
a Report. Covers: PASS, REVISE->PASS, REVISE->REVISE (-> needs_owner_review),
a malformed first verdict, the three Owner decisions from needs_owner_review
(accept draft / retry / close), a capability-gap rejection, a Skill
resolution failure, and invalid-transition enforcement -- none of these
call a real model (fake_model_complete) and none touch a real DB
(temp_env/app_client isolation, per conftest.py).
"""

import json

import pytest


def _submit(app_client, owner_credentials, csrf_headers, text="a task"):
    response = app_client.post(
        "/tasks", data={"request_text": text, "project_id": 1},
        auth=owner_credentials, headers=csrf_headers, follow_redirects=False,
    )
    return int(response.headers["location"].rsplit("/", 1)[-1])


def _counter(*values):
    """Returns a callable usable as a fake_model_complete.responses[...]
    entry -- yields each value in turn, then keeps returning the last one."""
    state = {"i": 0}

    def _next(prompt):
        i = min(state["i"], len(values) - 1)
        state["i"] += 1
        return values[i]
    return _next


def test_qa_pass_on_first_review_delivers(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task):
    from ego_os import store

    fake_model_complete.responses["delegation"] = ("writer", 5, 1, 0.00001)
    fake_model_complete.responses["business_communication"] = ("Done.", 10, 5, 0.00005)
    fake_model_complete.responses["critique"] = ("PASS", 5, 1, 0.00001)

    task_id = _submit(app_client, owner_credentials, csrf_headers)
    process_task(task_id)

    task = store.get_task(task_id)
    assert task["status"] == "delivered"
    report = store.get_report(task_id)
    assert report["terminal_status"] == "delivered"
    assert report["terminal_reason"] is None


def test_qa_revise_then_pass_delivers_after_exactly_one_retry(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task):
    from ego_os import store

    fake_model_complete.responses["delegation"] = ("writer", 5, 1, 0.00001)
    fake_model_complete.responses["business_communication"] = _counter(
        ("First draft.", 10, 5, 0.00005), ("Corrected draft.", 10, 5, 0.00005),
    )
    fake_model_complete.responses["critique"] = _counter(
        ("REVISE: too short", 5, 1, 0.00001), ("PASS", 5, 1, 0.00001),
    )

    task_id = _submit(app_client, owner_credentials, csrf_headers)
    process_task(task_id)

    task = store.get_task(task_id)
    assert task["status"] == "delivered"
    report = store.get_report(task_id)
    assert report["result_text"] == "Corrected draft."
    assert report["terminal_status"] == "delivered"


def test_qa_revise_then_revise_again_goes_to_needs_owner_review_not_delivered(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task):
    from ego_os import store

    fake_model_complete.responses["delegation"] = ("writer", 5, 1, 0.00001)
    fake_model_complete.responses["business_communication"] = _counter(
        ("First draft.", 10, 5, 0.00005), ("Second draft.", 10, 5, 0.00005),
    )
    fake_model_complete.responses["critique"] = _counter(
        ("REVISE: still missing X", 5, 1, 0.00001), ("REVISE: still missing X", 5, 1, 0.00001),
    )

    task_id = _submit(app_client, owner_credentials, csrf_headers)
    process_task(task_id)

    task = store.get_task(task_id)
    assert task["status"] == "needs_owner_review", "a second REVISE must never be silently delivered"
    assert task["run_state"] == "completed"
    reason = json.loads(task["terminal_reason"])
    assert reason["category"] == "qa_failed"
    report = store.get_report(task_id)
    assert report["terminal_status"] == "needs_owner_review"
    assert report["result_text"] == "Second draft."


def test_malformed_qa_verdict_on_first_review_fails_closed_to_needs_owner_review(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task):
    from ego_os import store

    fake_model_complete.responses["delegation"] = ("writer", 5, 1, 0.00001)
    fake_model_complete.responses["business_communication"] = ("Draft.", 10, 5, 0.00005)
    # Neither "PASS" nor "REVISE: ..." -- must never be treated as an
    # implicit PASS, and must never be guessed as a REVISE either.
    fake_model_complete.responses["critique"] = ("looks fine i guess", 5, 1, 0.00001)

    task_id = _submit(app_client, owner_credentials, csrf_headers)
    process_task(task_id)

    task = store.get_task(task_id)
    assert task["status"] == "needs_owner_review"
    reason = json.loads(task["terminal_reason"])
    assert reason["category"] == "qa_failed"
    assert "Malformed" in reason["detail"]
    report = store.get_report(task_id)
    assert report["terminal_status"] == "needs_owner_review"


def test_malformed_qa_verdict_on_second_review_also_fails_closed(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task):
    from ego_os import store

    fake_model_complete.responses["delegation"] = ("writer", 5, 1, 0.00001)
    fake_model_complete.responses["business_communication"] = _counter(
        ("First draft.", 10, 5, 0.00005), ("Second draft.", 10, 5, 0.00005),
    )
    fake_model_complete.responses["critique"] = _counter(
        ("REVISE: fix it", 5, 1, 0.00001), ("uh, sure??", 5, 1, 0.00001),
    )

    task_id = _submit(app_client, owner_credentials, csrf_headers)
    process_task(task_id)

    task = store.get_task(task_id)
    assert task["status"] == "needs_owner_review"
    reason = json.loads(task["terminal_reason"])
    assert "second review" in reason["detail"]


# --- Owner decisions from needs_owner_review --------------------------------

def _drive_to_needs_owner_review(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task):
    fake_model_complete.responses["delegation"] = ("writer", 5, 1, 0.00001)
    fake_model_complete.responses["business_communication"] = ("Draft.", 10, 5, 0.00005)
    fake_model_complete.responses["critique"] = _counter(
        ("REVISE: x", 5, 1, 0.00001), ("REVISE: x", 5, 1, 0.00001),
    )
    task_id = _submit(app_client, owner_credentials, csrf_headers)
    process_task(task_id)
    return task_id


def test_owner_accepts_draft_from_needs_owner_review(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task):
    from ego_os import store

    task_id = _drive_to_needs_owner_review(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task)
    res = app_client.post(f"/tasks/{task_id}/accept-draft", auth=owner_credentials, headers=csrf_headers)
    assert res.status_code in (200, 303)

    task = store.get_task(task_id)
    assert task["status"] == "delivered"
    report = store.get_report(task_id)
    assert report["terminal_status"] == "delivered"
    # the report row is the SAME one created at needs_owner_review time --
    # never a second insert (which reports.task_id's PRIMARY KEY forbids).
    assert report["result_text"] == "Draft."


def test_owner_requests_another_attempt_from_needs_owner_review(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task):
    from ego_os import store

    task_id = _drive_to_needs_owner_review(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task)
    # Script a clean PASS for the re-run the retry route triggers.
    fake_model_complete.responses["critique"] = ("PASS", 5, 1, 0.00001)
    res = app_client.post(f"/tasks/{task_id}/retry-after-review", auth=owner_credentials, headers=csrf_headers)
    assert res.status_code in (200, 303)

    task = store.get_task(task_id)
    assert task["run_state"] == "queued", "retry only enqueues -- the actual re-run needs its own process_task call"
    process_task(task_id)
    task = store.get_task(task_id)
    assert task["status"] == "delivered"


def test_owner_closes_task_from_needs_owner_review(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task):
    from ego_os import store

    task_id = _drive_to_needs_owner_review(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task)
    res = app_client.post(f"/tasks/{task_id}/close", auth=owner_credentials, headers=csrf_headers)
    assert res.status_code in (200, 303)

    task = store.get_task(task_id)
    assert task["status"] == "cancelled"
    reason = json.loads(task["terminal_reason"])
    assert reason["category"] == "owner_cancelled"
    report = store.get_report(task_id)
    assert report["terminal_status"] == "cancelled"


def test_owner_decision_routes_reject_a_task_not_awaiting_review(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task):
    fake_model_complete.responses["delegation"] = ("writer", 5, 1, 0.00001)
    fake_model_complete.responses["business_communication"] = ("Done.", 10, 5, 0.00005)
    fake_model_complete.responses["critique"] = ("PASS", 5, 1, 0.00001)
    task_id = _submit(app_client, owner_credentials, csrf_headers)
    process_task(task_id)  # already delivered -- not awaiting review

    for path in ("accept-draft", "retry-after-review", "close"):
        res = app_client.post(f"/tasks/{task_id}/{path}", auth=owner_credentials, headers=csrf_headers)
        assert res.status_code == 400


# --- capability gap rejection creates a terminal Report ---------------------

def test_gap_rejected_creates_a_terminal_report(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task):
    from ego_os import store

    fake_model_complete.responses["delegation"] = ("NO_MATCH: nothing fits", 5, 1, 0.00001)
    task_id = _submit(app_client, owner_credentials, csrf_headers)
    process_task(task_id)
    task = store.get_task(task_id)
    assert task["status"] == "awaiting_approval"
    assert store.get_report(task_id) is None, "awaiting_approval is not terminal -- no report yet"

    proposal = store.get_proposal_by_task(task_id)
    res = app_client.post(f"/proposals/{proposal['id']}/reject", auth=owner_credentials, headers=csrf_headers)
    assert res.status_code in (200, 303)

    task = store.get_task(task_id)
    assert task["status"] == "gap_rejected"
    report = store.get_report(task_id)
    assert report is not None
    assert report["terminal_status"] == "gap_rejected"


def test_gap_approved_creates_an_employee_provisioning_task_not_an_employee(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task):
    from ego_os import store

    fake_model_complete.responses["delegation"] = ("NO_MATCH: nothing fits", 5, 1, 0.00001)
    task_id = _submit(app_client, owner_credentials, csrf_headers)
    process_task(task_id)
    proposal = store.get_proposal_by_task(task_id)

    res = app_client.post(f"/proposals/{proposal['id']}/approve", auth=owner_credentials, headers=csrf_headers)
    assert res.status_code in (200, 303)

    task = store.get_task(task_id)
    assert task["status"] == "gap_approved"
    provisioning = store.get_employee_provisioning_task(1)
    assert provisioning is not None
    assert provisioning["proposal_id"] == proposal["id"]
    assert provisioning["task_id"] == task_id
    assert provisioning["status"] == "pending"


# --- Skill resolution failure creates a terminal Report ---------------------

def test_skill_resolution_failure_marks_task_failed_with_a_report(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task, monkeypatch):
    from ego_os import lifecycle, skills, store

    fake_model_complete.responses["delegation"] = ("writer", 5, 1, 0.00001)

    def boom(skill_refs, task_id=None, specialist_id=None):
        raise skills.SkillError("simulated missing skill")
    monkeypatch.setattr(lifecycle, "_resolve_employee_skills", boom)

    task_id = _submit(app_client, owner_credentials, csrf_headers)
    process_task(task_id)

    task = store.get_task(task_id)
    assert task["status"] == "failed"
    assert task["run_state"] == "failed"
    reason = json.loads(task["terminal_reason"])
    assert reason["category"] == "tool_failure"
    report = store.get_report(task_id)
    assert report is not None
    assert report["terminal_status"] == "failed"


# --- transition enforcement --------------------------------------------------

def test_invalid_task_transition_raises(temp_env):
    from ego_os import store

    store.init_db()
    project_id = store.ensure_default_project()
    task_id = store.create_task("x", project_id)  # starts at 'intake'
    with pytest.raises(store.TaskTransitionError):
        store.update_task_status(task_id, "delivered")  # intake -> delivered is not a real transition
    # A same-status no-op is always allowed.
    store.update_task_status(task_id, "intake")
    assert store.get_task(task_id)["status"] == "intake"


def test_update_report_terminal_outcome_requires_an_existing_report(temp_env):
    from ego_os import store

    store.init_db()
    project_id = store.ensure_default_project()
    task_id = store.create_task("x", project_id)
    with pytest.raises(ValueError):
        store.update_report_terminal_outcome(task_id, "delivered")
