"""Tests for the /agent/* proxy (SERVER-RUNNER-DARK-UI, Windows agent
architecture). Never starts a real control_server.js -- httpx calls are
monkeypatched, matching the project's own no-real-external-calls rule.
Proves: no Owner auth is required (a machine credential, not a human one),
only the fixed known operation set is reachable, request size is capped,
and the proxy never leaks or requires Owner/production secrets itself.
"""

import pytest


class _FakeResponse:
    def __init__(self, status_code, json_body):
        self.status_code = status_code
        self._json_body = json_body
        self.content = b"1" if json_body is not None else b""

    def json(self):
        return self._json_body


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, content=None, headers=None):
        self.calls.append({"url": url, "content": content, "headers": headers})
        return _FakeResponse(200, {"ok": True, "echo_url": url})


@pytest.fixture
def fake_httpx_client(monkeypatch):
    from ego_os import agent_routes

    fake = _FakeAsyncClient()
    monkeypatch.setattr(agent_routes.httpx, "AsyncClient", lambda *a, **k: fake)
    return fake


def test_agent_routes_do_not_require_owner_auth(app_client, fake_httpx_client):
    # No `auth=` kwarg at all -- if this required Owner Basic Auth it would 401.
    res = app_client.post("/agent/heartbeat", json={"agent_id": "x", "seq": 1})
    assert res.status_code == 200


def test_agent_routes_do_not_require_csrf_origin_header(app_client, fake_httpx_client):
    # A machine agent has no browser Origin/Referer to send -- the CSRF
    # check that protects Owner routes must not apply here at all.
    res = app_client.post("/agent/heartbeat", json={"agent_id": "x", "seq": 1})
    assert res.status_code == 200


def test_unknown_operation_is_404_before_any_proxy_call(app_client, fake_httpx_client):
    res = app_client.post("/agent/delete-everything", json={})
    assert res.status_code == 404
    assert fake_httpx_client.calls == []


@pytest.mark.parametrize("operation", [
    "register", "heartbeat", "claim", "report-state", "report-checkpoint", "report-result", "request-deploy",
])
def test_every_known_operation_is_forwarded_to_the_control_server(app_client, fake_httpx_client, operation):
    res = app_client.post(f"/agent/{operation}", json={"agent_id": "x", "seq": 1})
    assert res.status_code == 200
    assert len(fake_httpx_client.calls) == 1
    assert fake_httpx_client.calls[0]["url"] == f"http://127.0.0.1:4756/api/agent/{operation}"


def test_authorization_header_is_forwarded_unmodified(app_client, fake_httpx_client):
    app_client.post("/agent/heartbeat", json={"agent_id": "x"}, headers={"Authorization": "Bearer some-agent-token"})
    assert fake_httpx_client.calls[0]["headers"]["Authorization"] == "Bearer some-agent-token"


def test_oversized_body_is_rejected_before_proxying(app_client, fake_httpx_client):
    huge = {"agent_id": "x", "padding": "y" * (70 * 1024)}
    res = app_client.post("/agent/heartbeat", json=huge)
    assert res.status_code == 413
    assert fake_httpx_client.calls == []


def test_control_server_unavailable_is_reported_honestly_not_as_success(app_client, monkeypatch):
    import httpx as real_httpx
    from ego_os import agent_routes

    class _RefusingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *a, **k):
            raise real_httpx.ConnectError("connection refused")

    monkeypatch.setattr(agent_routes.httpx, "AsyncClient", lambda *a, **k: _RefusingClient())
    res = app_client.post("/agent/heartbeat", json={"agent_id": "x"})
    assert res.status_code == 503


def test_agent_proxy_response_never_contains_owner_or_production_secrets(app_client, fake_httpx_client, monkeypatch):
    monkeypatch.setenv("OWNER_PASSWORD", "should-never-appear-here")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-should-never-appear-here")
    res = app_client.post("/agent/heartbeat", json={"agent_id": "x"})
    assert "should-never-appear-here" not in res.text
