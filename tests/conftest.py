"""Shared test fixtures.

Every test runs against a fresh temp SQLite DB and temp upload/generated/
presentations directories -- never the real local ego_os.db or real
uploads/generated content. Every test that would otherwise call a real
model provider mocks ego_os.model_provider.complete instead; no test may
reach OpenRouter, Tavily, or any other external API.
"""

import pytest


@pytest.fixture
def temp_env(tmp_path, monkeypatch):
    """Redirect all on-disk state (DB, uploads, generated artifacts,
    published presentation sites) to an isolated temp directory."""
    from ego_os import store, tools

    db_path = tmp_path / "test.db"
    uploads_dir = tmp_path / "uploads"
    generated_dir = tmp_path / "generated"
    presentations_dir = tmp_path / "presentations"

    monkeypatch.setattr(store, "DB_PATH", db_path)
    monkeypatch.setattr(tools, "UPLOADS_DIR", uploads_dir)
    monkeypatch.setattr(tools, "GENERATED_DIR", generated_dir)
    monkeypatch.setattr(tools, "PRESENTATIONS_DIR", presentations_dir)

    return {
        "db_path": db_path,
        "uploads_dir": uploads_dir,
        "generated_dir": generated_dir,
        "presentations_dir": presentations_dir,
    }


@pytest.fixture
def owner_credentials(monkeypatch):
    """A fixed Owner Basic Auth username/password for tests, set via env
    vars the same way production reads them -- never a real credential."""
    monkeypatch.setenv("OWNER_USERNAME", "test-owner")
    monkeypatch.setenv("OWNER_PASSWORD", "test-password")
    return ("test-owner", "test-password")


@pytest.fixture
def csrf_headers():
    """An Origin header matching FastAPI TestClient's default base_url
    (http://testserver), for tests exercising a state-changing route
    through the real CSRF-equivalent check rather than around it."""
    return {"origin": "http://testserver"}


@pytest.fixture
def app_client(temp_env, owner_credentials, monkeypatch):
    """A FastAPI TestClient against a fully isolated app instance. Does not
    set Basic Auth credentials on the client itself -- tests that need an
    authenticated request pass `auth=owner_credentials` explicitly, so
    unauthenticated-access tests stay honest about what they're checking.

    The real background worker thread is disabled here (worker.start() is
    a no-op) -- a real thread racing a test's assertions would make tests
    flaky. Tests that need a submitted task actually processed call the
    process_task fixture, which runs it synchronously and deterministically."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")

    from ego_os import worker
    monkeypatch.setattr(worker, "start", lambda: None)

    from fastapi.testclient import TestClient
    from ego_os import main as main_module

    with TestClient(main_module.app) as client:
        yield client


@pytest.fixture
def process_task():
    """Run one queued task's Task Lifecycle synchronously, in the test's
    own thread -- the deterministic alternative to waiting on the (here,
    disabled) background worker thread."""
    from ego_os import worker

    return worker.process_one


@pytest.fixture
def fake_model_complete(monkeypatch):
    """Install a scripted fake in place of ego_os.model_provider.complete.
    Tests configure behavior by assigning fake_model_complete.responses, a
    dict of capability -> (text, in_tok, out_tok, cost) or a callable
    capability -> that tuple, for scenarios needing different replies
    across repeated calls to the same capability (e.g. REVISE then PASS)."""
    from ego_os import model_provider

    state = {"responses": {}, "calls": []}

    def fake_complete(capability, prompt, max_tokens=1024, task_id=None, task_budget_cents=None):
        # task_id/task_budget_cents (ADR-0016) are accepted here but never
        # enforced -- these tests are about lifecycle/QA behavior, not
        # budget enforcement, which has its own dedicated test file
        # (tests/test_budget_ledger.py) against the real store.reserve_budget.
        state["calls"].append((capability, prompt))
        behavior = state["responses"].get(capability)
        if behavior is None:
            raise AssertionError(f"fake_model_complete has no scripted response for capability '{capability}'")
        if callable(behavior):
            return behavior(prompt)
        return behavior

    monkeypatch.setattr(model_provider, "complete", fake_complete)
    fake_complete.responses = state["responses"]
    fake_complete.calls = state["calls"]
    return fake_complete
