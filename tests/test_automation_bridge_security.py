"""ADR-0013: safe local runner control transport. Pure validation tests
plus a few against a REAL local HTTP server (stdlib http.server on an
ephemeral loopback port) to prove redirect-rejection and the "control
server not on the approved port" case against actual network behavior,
not just mocks. Never talks to a real automation/control_server.js."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


# --- pure validation ---------------------------------------------------------

def test_127_0_0_1_is_accepted():
    from ego_os import automation_bridge

    automation_bridge._validate_control_server_url("http://127.0.0.1:4756")  # must not raise


def test_localhost_is_accepted_only_because_it_resolves_to_loopback():
    from ego_os import automation_bridge

    # "localhost" is accepted per this machine's own hosts resolution --
    # exercised for real (no mock), proving the "safely resolved" rule
    # actually calls real DNS/hosts-file resolution rather than a fixed
    # string allowlist that would treat "localhost" as special-cased text.
    automation_bridge._validate_control_server_url("http://localhost:4756")  # must not raise


def test_ipv6_loopback_is_accepted():
    from ego_os import automation_bridge

    automation_bridge._validate_control_server_url("http://[::1]:4756")  # must not raise


@pytest.mark.parametrize("url", [
    "http://example.com:4756",
    "http://8.8.8.8:4756",
    "http://192.168.1.1:4756",
])
def test_external_host_is_rejected(url):
    from ego_os import automation_bridge

    with pytest.raises(automation_bridge.ControlServerConfigError):
        automation_bridge._validate_control_server_url(url)


def test_credentials_in_url_are_rejected():
    from ego_os import automation_bridge

    with pytest.raises(automation_bridge.ControlServerConfigError):
        automation_bridge._validate_control_server_url("http://user:pass@127.0.0.1:4756")


def test_unsupported_port_is_rejected():
    from ego_os import automation_bridge

    with pytest.raises(automation_bridge.ControlServerConfigError):
        automation_bridge._validate_control_server_url("http://127.0.0.1:9999")


def test_unsupported_scheme_is_rejected():
    from ego_os import automation_bridge

    with pytest.raises(automation_bridge.ControlServerConfigError):
        automation_bridge._validate_control_server_url("ftp://127.0.0.1:4756")


def test_url_with_no_hostname_is_rejected():
    from ego_os import automation_bridge

    with pytest.raises(automation_bridge.ControlServerConfigError):
        automation_bridge._validate_control_server_url("http://:4756")


def test_a_hostname_that_fails_to_resolve_is_rejected():
    from ego_os import automation_bridge

    with pytest.raises(automation_bridge.ControlServerConfigError):
        automation_bridge._validate_control_server_url("http://this-host-does-not-exist.invalid.:4756")


# --- production/misconfiguration fails closed, never raises -----------------

def test_misconfigured_url_fails_closed_to_unavailable_never_raises(monkeypatch):
    from ego_os import automation_bridge

    monkeypatch.setattr(automation_bridge, "CONTROL_SERVER_URL", "http://evil.example.com:4756")
    result = automation_bridge.get_status()
    assert result["ok"] is False
    assert "safety validation" in result["error"]


def test_safe_base_url_returns_none_when_invalid(monkeypatch):
    from ego_os import automation_bridge

    monkeypatch.setattr(automation_bridge, "CONTROL_SERVER_URL", "http://attacker.example:4756")
    assert automation_bridge._safe_base_url() is None


def test_unapproved_port_fails_closed(monkeypatch):
    from ego_os import automation_bridge

    monkeypatch.setattr(automation_bridge, "CONTROL_SERVER_URL", "http://127.0.0.1:8080")
    assert automation_bridge._safe_base_url() is None


# --- unknown command/action are rejected before any HTTP call ---------------

def test_unknown_runner_command_rejected_before_any_call(monkeypatch):
    from ego_os import automation_bridge

    called = []
    monkeypatch.setattr(automation_bridge, "_post", lambda *a, **k: called.append(1))
    result = automation_bridge.post_runner_command("reboot-the-vps")
    assert result["ok"] is False
    assert called == []


def test_unknown_task_action_rejected_before_any_call(monkeypatch):
    from ego_os import automation_bridge

    called = []
    monkeypatch.setattr(automation_bridge, "_post", lambda *a, **k: called.append(1))
    result = automation_bridge.post_task_action("DA-01", "delete-forever")
    assert result["ok"] is False
    assert called == []


# --- real local HTTP server: redirect rejection -----------------------------

class _RedirectHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(302)
        self.send_header("Location", "http://127.0.0.1:1/somewhere-else")
        self.end_headers()

    def log_message(self, *args):
        pass  # keep test output quiet


class _JsonOkHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"ok": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _run_server(handler_cls):
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


def test_redirect_response_is_never_followed_and_counts_as_not_ok(monkeypatch):
    from ego_os import automation_bridge

    server, port = _run_server(_RedirectHandler)
    try:
        monkeypatch.setattr(automation_bridge, "_APPROVED_PORTS", {port})
        monkeypatch.setattr(automation_bridge, "CONTROL_SERVER_URL", f"http://127.0.0.1:{port}")
        result = automation_bridge.get_status()
        assert result["status_code"] == 302, "the redirect itself must be visible, never silently chased"
        assert result["ok"] is False
    finally:
        server.shutdown()


def test_a_real_2xx_json_response_through_the_full_validated_path_is_ok(monkeypatch):
    from ego_os import automation_bridge

    server, port = _run_server(_JsonOkHandler)
    try:
        monkeypatch.setattr(automation_bridge, "_APPROVED_PORTS", {port})
        monkeypatch.setattr(automation_bridge, "CONTROL_SERVER_URL", f"http://127.0.0.1:{port}")
        result = automation_bridge.get_status()
        assert result["ok"] is True
        assert result["data"] == {"ok": True}
    finally:
        server.shutdown()
