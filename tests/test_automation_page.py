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

    calls = {"runner_commands": [], "task_actions": []}
    state = {
        "status": {"ok": True, "status_code": 200, "data": {
            "runner_state": "idle", "pid": 4242, "updated_at": "2026-07-12T10:00:00Z",
            "reason": None, "current_task": None,
        }},
        "tasks": {"ok": True, "status_code": 200, "data": {"tasks": []}},
        "events": {"ok": True, "status_code": 200, "data": {"events": []}},
        "task_detail": {"ok": True, "status_code": 200, "data": {"task": None}},
        "logs": {"ok": False, "status_code": None, "data": None},
    }

    monkeypatch.setattr(automation_bridge, "get_status", lambda: state["status"])
    monkeypatch.setattr(automation_bridge, "get_tasks", lambda: state["tasks"])
    monkeypatch.setattr(automation_bridge, "get_events", lambda limit=100: state["events"])
    monkeypatch.setattr(automation_bridge, "get_task", lambda task_id: state["task_detail"])
    monkeypatch.setattr(automation_bridge, "get_logs", lambda file: state["logs"])

    def fake_post_runner_command(command, body=None):
        calls["runner_commands"].append((command, body))
        return {"ok": True, "status_code": 202, "data": {"ok": True}}

    def fake_post_task_action(task_id, action, body=None):
        calls["task_actions"].append((task_id, action, body))
        return {"ok": True, "status_code": 200, "data": {"ok": True}}

    monkeypatch.setattr(automation_bridge, "post_runner_command", fake_post_runner_command)
    monkeypatch.setattr(automation_bridge, "post_task_action", fake_post_task_action)

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
