"""Owner access control (v0.4.1). An unauthenticated caller must not be
able to view or change anything -- every route in ego_os/main.py carries
the require_owner dependency globally."""


def test_unauthenticated_get_is_rejected(app_client):
    response = app_client.get("/")
    assert response.status_code == 401


def test_unauthenticated_dashboard_is_rejected(app_client):
    response = app_client.get("/dashboard")
    assert response.status_code == 401


def test_wrong_password_is_rejected(app_client):
    response = app_client.get("/", auth=("test-owner", "wrong-password"))
    assert response.status_code == 401


def test_wrong_username_is_rejected(app_client):
    response = app_client.get("/", auth=("someone-else", "test-password"))
    assert response.status_code == 401


def test_correct_credentials_are_accepted(app_client, owner_credentials):
    response = app_client.get("/", auth=owner_credentials)
    assert response.status_code == 200


def test_unconfigured_credentials_fail_closed(app_client, monkeypatch, csrf_headers):
    """If OWNER_USERNAME/OWNER_PASSWORD are unset, every request must be
    rejected -- an unconfigured deployment must not default to open."""
    monkeypatch.delenv("OWNER_USERNAME", raising=False)
    monkeypatch.delenv("OWNER_PASSWORD", raising=False)
    response = app_client.get("/", auth=("test-owner", "test-password"))
    assert response.status_code == 401


def test_unauthenticated_post_is_rejected_before_any_state_change(app_client, csrf_headers, temp_env):
    """No task should be created for an unauthenticated submission -- not
    just a 401, but genuinely no state change."""
    from ego_os import store

    response = app_client.post(
        "/tasks",
        data={"request_text": "should never run", "project_id": 1},
        headers=csrf_headers,
    )
    assert response.status_code == 401
    assert store.get_tasks() == []
