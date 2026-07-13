"""Tests for the /automation Owner page and its control routes
(SERVER-RUNNER-DARK-UI). Never makes a real HTTP call to the control
server -- ego_os.automation_bridge's own functions are monkeypatched with
scripted fakes, exactly like fake_model_complete mocks the model provider
elsewhere in this suite. Proves: auth, CSRF-equivalent protection, correct
forwarding of commands (including the confirm-required rule) to the
existing runner control API, path-traversal/invalid-id rejection, and that
the page never 500s when the control server is unreachable.
"""

import pytest


@pytest.fixture
def fake_bridge(monkeypatch):
    """Replaces every ego_os.automation_bridge function the routes call
    with a scripted fake -- records every call so a test can assert on
    exactly what was forwarded (e.g. did emergency-stop actually carry
    confirm:true) without ever reaching a real control server."""
    from ego_os import automation_bridge

    calls = {"runner_commands": [], "task_actions": [], "reorders": []}
    state = {
        "status": {"ok": True, "status_code": 200, "data": {
            "runner_state": "idle", "pid": 4242, "updated_at": "2026-07-12T10:00:00Z",
            "reason": None, "current_task": None,
        }},
        "tasks": {"ok": True, "status_code": 200, "data": {"tasks": []}},
        "events": {"ok": True, "status_code": 200, "data": {"events": []}},
        "task_detail": {"ok": True, "status_code": 200, "data": {"task": None}},
        "logs": {"ok": False, "status_code": None, "data": None},
        "usage": {"ok": True, "status_code": 200, "data": {"usage": {
            "claude": {"total_sessions": 0, "total_cost_usd": 0, "last_session": None},
            "codex": {"total_sessions": 0, "total_cost_usd": 0, "last_session": None},
        }}},
        "reorder_result": {"ok": True, "status_code": 200, "data": {"ok": True}},
    }

    monkeypatch.setattr(automation_bridge, "get_status", lambda: state["status"])
    monkeypatch.setattr(automation_bridge, "get_tasks", lambda: state["tasks"])
    monkeypatch.setattr(automation_bridge, "get_events", lambda limit=100: state["events"])
    monkeypatch.setattr(automation_bridge, "get_task", lambda task_id: state["task_detail"])
    monkeypatch.setattr(automation_bridge, "get_logs", lambda file: state["logs"])
    monkeypatch.setattr(automation_bridge, "get_usage", lambda: state["usage"])

    def fake_post_runner_command(command, body=None):
        calls["runner_commands"].append((command, body))
        return {"ok": True, "status_code": 202, "data": {"ok": True}}

    def fake_post_task_action(task_id, action, body=None):
        calls["task_actions"].append((task_id, action, body))
        return {"ok": True, "status_code": 200, "data": {"ok": True}}

    def fake_post_reorder(order):
        calls["reorders"].append(order)
        return state["reorder_result"]

    monkeypatch.setattr(automation_bridge, "post_runner_command", fake_post_runner_command)
    monkeypatch.setattr(automation_bridge, "post_task_action", fake_post_task_action)
    monkeypatch.setattr(automation_bridge, "post_reorder", fake_post_reorder)

    fake_bridge_obj = type("FakeBridge", (), {"calls": calls, "state": state})()
    return fake_bridge_obj


# --- auth ------------------------------------------------------------------

def test_automation_page_requires_owner_auth(app_client, fake_bridge):
    res = app_client.get("/automation")
    assert res.status_code == 401


def test_automation_page_with_owner_auth_returns_200(app_client, owner_credentials, fake_bridge):
    res = app_client.get("/automation", auth=owner_credentials)
    assert res.status_code == 200
    assert "Автоматизация" in res.text


# --- graceful degradation ---------------------------------------------------

def test_automation_page_never_500s_when_control_server_unreachable(app_client, owner_credentials, fake_bridge):
    fake_bridge.state["status"] = {"ok": False, "status_code": None, "data": None, "error": "connection refused"}
    fake_bridge.state["tasks"] = {"ok": False, "status_code": None, "data": None}
    fake_bridge.state["events"] = {"ok": False, "status_code": None, "data": None}
    res = app_client.get("/automation", auth=owner_credentials)
    assert res.status_code == 200
    assert "недоступен" in res.text


# --- CSRF-equivalent protection ---------------------------------------------

def test_runner_command_without_origin_referer_is_rejected(app_client, owner_credentials, fake_bridge):
    res = app_client.post("/automation/runner/start", auth=owner_credentials)
    assert res.status_code == 403
    assert fake_bridge.calls["runner_commands"] == []


def test_task_action_without_origin_referer_is_rejected(app_client, owner_credentials, fake_bridge):
    res = app_client.post("/automation/tasks/DA-01/hold", auth=owner_credentials)
    assert res.status_code == 403
    assert fake_bridge.calls["task_actions"] == []


def test_runner_command_without_auth_is_rejected(app_client, csrf_headers, fake_bridge):
    res = app_client.post("/automation/runner/start", headers=csrf_headers)
    assert res.status_code == 401
    assert fake_bridge.calls["runner_commands"] == []


# --- commands forward correctly to the existing control API ----------------

@pytest.mark.parametrize("command", ["start", "pause", "resume", "stop-after-stage"])
def test_ordinary_runner_commands_forward_without_requiring_confirm(app_client, owner_credentials, csrf_headers, fake_bridge, command):
    res = app_client.post(f"/automation/runner/{command}", auth=owner_credentials, headers=csrf_headers)
    assert res.status_code in (200, 303)
    assert fake_bridge.calls["runner_commands"] == [(command, {})]


def test_emergency_stop_requires_confirm_and_is_forwarded_as_confirm_true(app_client, owner_credentials, csrf_headers, fake_bridge):
    res = app_client.post(
        "/automation/runner/emergency-stop",
        auth=owner_credentials, headers=csrf_headers,
        data={"confirm": "true"},
    )
    assert res.status_code in (200, 303)
    assert fake_bridge.calls["runner_commands"] == [("emergency-stop", {"confirm": True})]


def test_emergency_stop_without_confirm_field_is_forwarded_as_confirm_false_never_silently_true(app_client, owner_credentials, csrf_headers, fake_bridge):
    # The page's own emergency-stop form always includes a hidden
    # confirm=true field behind a JS confirm() dialog -- but if a raw
    # request arrives with no confirm field at all (e.g. a hand-crafted
    # request bypassing the UI), the route must forward confirm:False,
    # never assume/default to true. The downstream control server rejects
    # confirm:False for emergency-stop -- this test proves OUR forwarding
    # never launders a missing confirmation into an approved one.
    res = app_client.post("/automation/runner/emergency-stop", auth=owner_credentials, headers=csrf_headers)
    assert fake_bridge.calls["runner_commands"] == [("emergency-stop", {"confirm": False})]


def test_unknown_runner_command_is_rejected_before_reaching_the_bridge(app_client, owner_credentials, csrf_headers, fake_bridge):
    res = app_client.post("/automation/runner/reboot-the-vps", auth=owner_credentials, headers=csrf_headers)
    assert res.status_code == 404
    assert fake_bridge.calls["runner_commands"] == []


def test_skip_requires_confirm_and_carries_a_reason(app_client, owner_credentials, csrf_headers, fake_bridge):
    res = app_client.post(
        "/automation/tasks/DA-03/skip",
        auth=owner_credentials, headers=csrf_headers,
        data={"confirm": "true", "reason": "superseded by newer task"},
    )
    assert res.status_code in (200, 303)
    assert fake_bridge.calls["task_actions"] == [("DA-03", "skip", {"reason": "superseded by newer task", "confirm": True})]


def test_hold_does_not_require_confirm(app_client, owner_credentials, csrf_headers, fake_bridge):
    res = app_client.post("/automation/tasks/DA-03/hold", auth=owner_credentials, headers=csrf_headers)
    assert res.status_code in (200, 303)
    assert fake_bridge.calls["task_actions"] == [("DA-03", "hold", {})]


# --- path traversal / invalid task id -------------------------------------

@pytest.mark.parametrize("bad_id", ["../../etc/passwd", "..%2f..%2fmain", "DA 01", "DA;rm -rf", ""])
def test_invalid_task_id_is_rejected_before_reaching_the_bridge(app_client, owner_credentials, csrf_headers, fake_bridge, bad_id):
    res = app_client.post(f"/automation/tasks/{bad_id}/hold", auth=owner_credentials, headers=csrf_headers)
    assert res.status_code in (400, 404)
    assert fake_bridge.calls["task_actions"] == []


def test_unknown_task_action_is_rejected(app_client, owner_credentials, csrf_headers, fake_bridge):
    res = app_client.post("/automation/tasks/DA-03/delete-forever", auth=owner_credentials, headers=csrf_headers)
    assert res.status_code == 404
    assert fake_bridge.calls["task_actions"] == []


# --- casual grouped queue cards ---------------------------------------------

def test_queue_renders_as_casual_groups_with_casual_name_and_raw_title_in_technical_table(app_client, owner_credentials, fake_bridge):
    fake_bridge.state["tasks"] = {"ok": True, "status_code": 200, "data": {"tasks": [
        {
            "id": "MED-01", "title": "Multi-Executor Dispatch: Codex CLI recon (read-only)",
            "display_summary": "Проверяем, что вообще умеет Codex, ничего не ломая",
            "group_key": "multi-executor", "group_name": "Клод + Кодекс работают вместе",
            "group_casual_summary": "Один раннер, который сам решает.",
            "priority": "P1", "status": "ready", "release": "no_deploy", "owner_approved": False,
            "blocked_reason": None, "sessions_count": 0,
        },
    ]}}
    res = app_client.get("/automation", auth=owner_credentials)
    assert res.status_code == 200
    assert "Клод + Кодекс работают вместе" in res.text
    assert "Один раннер, который сам решает." in res.text
    # the technical table (inside the collapsed card) always shows the raw
    # title, never the casual display_summary -- that stays reserved for
    # the current-task section and the group's own casual name/summary.
    assert "Multi-Executor Dispatch: Codex CLI recon" in res.text


def test_current_task_shows_display_summary_instead_of_raw_title_when_present(app_client, owner_credentials, fake_bridge):
    fake_bridge.state["status"] = {"ok": True, "status_code": 200, "data": {
        "runner_state": "running", "pid": 1, "updated_at": "2026-07-12T10:00:00Z", "reason": None,
        "current_task": {
            "id": "MED-01", "title": "Multi-Executor Dispatch: Codex CLI recon (read-only)",
            "display_summary": "Проверяем, что вообще умеет Codex, ничего не ломая",
            "status": "in_progress", "priority": "P1", "retry_after": None, "summary": None, "sessions_count": 1,
        },
    }}
    res = app_client.get("/automation", auth=owner_credentials)
    assert "Проверяем, что вообще умеет Codex, ничего не ломая" in res.text


def test_queue_groups_show_a_done_over_total_count(app_client, owner_credentials, fake_bridge):
    fake_bridge.state["tasks"] = {"ok": True, "status_code": 200, "data": {"tasks": [
        {"id": "DA-01", "title": "t1", "group_key": "ego-os-core", "group_name": "Развитие Ego OS",
         "group_casual_summary": "s", "priority": "P1", "status": "done", "release": "no_deploy",
         "owner_approved": False, "blocked_reason": None, "sessions_count": 1},
        {"id": "DA-02", "title": "t2", "group_key": "ego-os-core", "group_name": "Развитие Ego OS",
         "group_casual_summary": "s", "priority": "P1", "status": "ready", "release": "no_deploy",
         "owner_approved": False, "blocked_reason": None, "sessions_count": 0},
    ]}}
    res = app_client.get("/automation", auth=owner_credentials)
    assert "1/2 выполнено" in res.text


def test_a_blocked_task_flags_its_group_as_needing_attention(app_client, owner_credentials, fake_bridge):
    fake_bridge.state["tasks"] = {"ok": True, "status_code": 200, "data": {"tasks": [
        {"id": "DA-05", "title": "t", "group_key": "ego-os-core", "group_name": "Развитие Ego OS",
         "group_casual_summary": "s", "priority": "P0", "status": "blocked", "release": "no_deploy",
         "owner_approved": False, "blocked_reason": "awaiting decision", "sessions_count": 1},
    ]}}
    res = app_client.get("/automation", auth=owner_credentials)
    assert "нужно ваше внимание" in res.text


# --- Claude/Codex limits panel ----------------------------------------------

def test_limits_panel_shows_honest_no_data_before_any_session(app_client, owner_credentials, fake_bridge):
    res = app_client.get("/automation", auth=owner_credentials)
    assert res.status_code == 200
    assert "Нет данных" in res.text


def test_limits_panel_renders_real_claude_usage(app_client, owner_credentials, fake_bridge):
    fake_bridge.state["usage"] = {"ok": True, "status_code": 200, "data": {"usage": {
        "claude": {"total_sessions": 3, "total_cost_usd": 0.42, "last_session": {"task_id": "DA-01"}},
        "codex": {"total_sessions": 0, "total_cost_usd": 0, "last_session": None},
    }}}
    res = app_client.get("/automation", auth=owner_credentials)
    assert "0.4200" in res.text


def test_limits_panel_renders_real_codex_rate_limits_when_present(app_client, owner_credentials, fake_bridge):
    fake_bridge.state["usage"] = {"ok": True, "status_code": 200, "data": {"usage": {
        "claude": {"total_sessions": 0, "total_cost_usd": 0, "last_session": None},
        "codex": {"total_sessions": 0, "total_cost_usd": 0, "last_session": None, "rate_limits": {
            "status": "available", "checked_at": "2026-07-12T19:59:31.042Z", "plan_type": "pro",
            "primary": {"remaining_percent": 72, "resets_at": "2026-07-12T23:40:00.000Z"},
            "secondary": {"remaining_percent": 41, "resets_at": "2026-07-17T18:00:00.000Z"},
            "error": None,
        }},
    }}}
    res = app_client.get("/automation", auth=owner_credentials)
    assert "72% remaining" in res.text
    assert "41% remaining" in res.text
    assert "available" in res.text


# --- drag-and-drop reorder --------------------------------------------------

def test_reorder_requires_owner_auth(app_client, fake_bridge):
    res = app_client.post("/automation/tasks/reorder", json={"order": ["DA-01", "DA-02"]})
    assert res.status_code == 401
    assert fake_bridge.calls["reorders"] == []


def test_reorder_without_origin_referer_is_rejected(app_client, owner_credentials, fake_bridge):
    res = app_client.post("/automation/tasks/reorder", auth=owner_credentials, json={"order": ["DA-01", "DA-02"]})
    assert res.status_code == 403
    assert fake_bridge.calls["reorders"] == []


def test_reorder_forwards_the_order_to_the_bridge(app_client, owner_credentials, csrf_headers, fake_bridge):
    res = app_client.post(
        "/automation/tasks/reorder", auth=owner_credentials, headers=csrf_headers,
        json={"order": ["DA-02", "DA-01"]},
    )
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert fake_bridge.calls["reorders"] == [["DA-02", "DA-01"]]


def test_reorder_rejects_an_empty_or_missing_order(app_client, owner_credentials, csrf_headers, fake_bridge):
    res = app_client.post("/automation/tasks/reorder", auth=owner_credentials, headers=csrf_headers, json={})
    assert res.status_code == 400
    res2 = app_client.post("/automation/tasks/reorder", auth=owner_credentials, headers=csrf_headers, json={"order": []})
    assert res2.status_code == 400
    assert fake_bridge.calls["reorders"] == []


def test_reorder_propagates_a_control_server_rejection_as_409(app_client, owner_credentials, csrf_headers, fake_bridge):
    fake_bridge.state["reorder_result"] = {"ok": False, "status_code": 409, "data": {"error": "X depends on Y, which is not done"}}
    res = app_client.post(
        "/automation/tasks/reorder", auth=owner_credentials, headers=csrf_headers,
        json={"order": ["DA-01"]},
    )
    assert res.status_code == 409


# --- no secrets in the rendered page ----------------------------------------

def test_automation_page_never_renders_known_secret_shapes(app_client, owner_credentials, fake_bridge, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-should-never-appear-in-html")
    res = app_client.get("/automation", auth=owner_credentials)
    assert "sk-or-v1-should-never-appear-in-html" not in res.text
    assert "OWNER_PASSWORD" not in res.text


# --- existing functionality unaffected --------------------------------------

def test_dashboard_and_command_pages_still_work(app_client, owner_credentials, fake_bridge):
    assert app_client.get("/dashboard", auth=owner_credentials).status_code == 200
    assert app_client.get("/", auth=owner_credentials).status_code == 200


def test_static_theme_css_requires_auth_and_serves_css(app_client, owner_credentials):
    assert app_client.get("/static/theme.css").status_code == 401
    res = app_client.get("/static/theme.css", auth=owner_credentials)
    assert res.status_code == 200
    assert "text/css" in res.headers["content-type"]
    assert "--bg" in res.text


@pytest.mark.parametrize("bad_path", ["../main.py", "..%2fmain.py", "..\\main.py"])
def test_static_route_rejects_path_traversal(app_client, owner_credentials, bad_path):
    res = app_client.get(f"/static/{bad_path}", auth=owner_credentials)
    assert res.status_code == 404


# --- Command (/) and Dashboard (/dashboard) redesign (UI-only) -------------
# / is a chat-first Command surface (submits a ProductTask, not a live
# conversation); /dashboard is the single operational page. Both reuse
# ego_os.automation_bridge through main._runner_snapshot() -- never a new
# POST, never a new external call, never a state change of their own.

def test_command_page_requires_owner_auth(app_client, fake_bridge):
    assert app_client.get("/").status_code == 401


def test_dashboard_page_requires_owner_auth(app_client, fake_bridge):
    assert app_client.get("/dashboard").status_code == 401


def test_command_page_returns_200_when_control_server_unavailable(app_client, owner_credentials, fake_bridge):
    fake_bridge.state["status"] = {"ok": False, "status_code": None, "data": None, "error": "connection refused"}
    res = app_client.get("/", auth=owner_credentials)
    assert res.status_code == 200
    assert "недоступен" in res.text


def test_dashboard_page_returns_200_when_control_server_unavailable(app_client, owner_credentials, fake_bridge):
    fake_bridge.state["status"] = {"ok": False, "status_code": None, "data": None, "error": "connection refused"}
    fake_bridge.state["tasks"] = {"ok": False, "status_code": None, "data": None}
    fake_bridge.state["events"] = {"ok": False, "status_code": None, "data": None}
    res = app_client.get("/dashboard", auth=owner_credentials)
    assert res.status_code == 200
    assert "недоступен" in res.text


def test_command_page_renders_compact_runner_state_spend_and_task_form(app_client, owner_credentials, fake_bridge):
    res = app_client.get("/", auth=owner_credentials)
    assert res.status_code == 200
    # compact runner state (from the default fake_bridge status: idle)
    assert "idle" in res.text
    # honest spend label, never framed as a remaining budget
    assert "0.0000" in res.text
    assert "Отправить задачу" in res.text
    # not a fake live chat
    assert "не живой чат" in res.text


def test_command_page_does_not_render_administrative_surfaces(app_client, owner_credentials, fake_bridge):
    """Mandate, the projects table/create-project form, and employee
    proposals moved to /dashboard -- the Command page keeps only the
    project <select> needed to submit a task."""
    res = app_client.get("/", auth=owner_credentials)
    assert "Risk policy" not in res.text
    assert "Создать проект" not in res.text


def test_command_page_shows_last_product_task_with_report_link(app_client, owner_credentials, fake_bridge):
    from ego_os import store

    project_id = store.ensure_default_project()
    task_id = store.create_task("do the thing", project_id)
    res = app_client.get("/", auth=owner_credentials)
    assert res.status_code == 200
    assert "do the thing" in res.text
    assert f"/tasks/{task_id}" in res.text


def test_dashboard_renders_runner_summary_usage_queue_and_company_data(app_client, owner_credentials, fake_bridge):
    from ego_os import store

    store.create_mandate("Build things", 100.0, "no gambling")
    fake_bridge.state["tasks"] = {"ok": True, "status_code": 200, "data": {"tasks": [
        {
            "id": "MED-01", "title": "Some automation task",
            "display_summary": "short summary", "group_key": "g", "group_name": "Group",
            "group_casual_summary": "s", "priority": "P1", "status": "ready", "release": "no_deploy",
            "owner_approved": False, "blocked_reason": None, "sessions_count": 0,
        },
    ]}}
    res = app_client.get("/dashboard", auth=owner_credentials)
    assert res.status_code == 200
    assert "Приоритетные операции" in res.text  # runner summary
    assert "Лимиты" in res.text  # usage section
    assert "Group" in res.text  # queue (grouped)
    assert "Build things" in res.text  # mandate (company data)
    assert "Готовы (ready)" in res.text and ">1<" in res.text  # ready_count


def test_dashboard_shows_full_technical_view_link_to_automation(app_client, owner_credentials, fake_bridge):
    res = app_client.get("/dashboard", auth=owner_credentials)
    assert '/automation' in res.text


def test_emergency_stop_confirm_dialog_present_on_command_and_dashboard(app_client, owner_credentials, fake_bridge):
    for path in ("/", "/dashboard"):
        res = app_client.get(path, auth=owner_credentials)
        assert "confirm(" in res.text
        assert "Экстренная остановка" in res.text


def test_command_and_dashboard_never_render_known_secret_shapes(app_client, owner_credentials, fake_bridge, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-should-never-appear-in-html")
    for path in ("/", "/dashboard"):
        res = app_client.get(path, auth=owner_credentials)
        assert "sk-or-v1-should-never-appear-in-html" not in res.text
        assert "OWNER_PASSWORD" not in res.text


# --- redirect-target allowlist (return_to) ----------------------------------

def test_runner_command_redirects_to_allowlisted_return_to(app_client, owner_credentials, csrf_headers, fake_bridge):
    res = app_client.post(
        "/automation/runner/start", auth=owner_credentials, headers=csrf_headers,
        data={"return_to": "/dashboard"}, follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/dashboard"


def test_runner_command_return_to_command_page(app_client, owner_credentials, csrf_headers, fake_bridge):
    res = app_client.post(
        "/automation/runner/start", auth=owner_credentials, headers=csrf_headers,
        data={"return_to": "/"}, follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/"


@pytest.mark.parametrize("bad_return_to", [
    "https://evil.example/steal", "//evil.example", "/tasks", "/../etc/passwd", "javascript:alert(1)", "",
])
def test_runner_command_rejects_non_allowlisted_return_to_and_falls_back_to_automation(
    app_client, owner_credentials, csrf_headers, fake_bridge, bad_return_to,
):
    res = app_client.post(
        "/automation/runner/start", auth=owner_credentials, headers=csrf_headers,
        data={"return_to": bad_return_to}, follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/automation"


def test_runner_command_with_no_return_to_falls_back_to_automation(app_client, owner_credentials, csrf_headers, fake_bridge):
    res = app_client.post(
        "/automation/runner/start", auth=owner_credentials, headers=csrf_headers,
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/automation"


def test_task_action_redirects_to_allowlisted_return_to(app_client, owner_credentials, csrf_headers, fake_bridge):
    res = app_client.post(
        "/automation/tasks/DA-03/hold", auth=owner_credentials, headers=csrf_headers,
        data={"return_to": "/dashboard"}, follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/dashboard"


def test_task_action_rejects_non_allowlisted_return_to(app_client, owner_credentials, csrf_headers, fake_bridge):
    res = app_client.post(
        "/automation/tasks/DA-03/hold", auth=owner_credentials, headers=csrf_headers,
        data={"return_to": "https://evil.example/"}, follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/automation"


def test_return_to_does_not_change_what_is_forwarded_to_the_bridge(app_client, owner_credentials, csrf_headers, fake_bridge):
    """return_to only selects the redirect target -- it must never leak into
    the command/action body sent to automation_bridge."""
    app_client.post(
        "/automation/runner/pause", auth=owner_credentials, headers=csrf_headers,
        data={"return_to": "/dashboard"},
    )
    assert fake_bridge.calls["runner_commands"] == [("pause", {})]


# --- mandate/project/proposal forms now live on /dashboard ------------------

def test_mandate_submission_redirects_to_dashboard(app_client, owner_credentials, csrf_headers, temp_env):
    res = app_client.post(
        "/mandate", auth=owner_credentials, headers=csrf_headers,
        data={"mission": "m", "starting_capital": "10.0", "risk_policy": "r"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/dashboard"


def test_project_submission_redirects_to_dashboard(app_client, owner_credentials, csrf_headers, temp_env):
    res = app_client.post(
        "/projects", auth=owner_credentials, headers=csrf_headers,
        data={"name": "New Project", "vision": ""},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/dashboard"
