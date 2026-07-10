"""Employee Skill references (SR-02): backward-compatible optional
`skills` field, fail-closed resolution before any model call, no
permission widening, and traceability that survives a later registry
change. Everything here uses the real `writer` employee row (temporarily
given a `skills` reference) rather than a fabricated one, so it exercises
the exact same code path a real task takes.
"""

import hashlib
import json

import pytest


def _digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _write_skill(root, skill_id, version, *, trust_state="approved", lifecycle_state="active", content=b"# Test skill.\n"):
    import yaml

    package_dir = root / skill_id / version
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "SKILL.md").write_bytes(content)
    manifest = {
        "schema_version": "1.0",
        "id": skill_id,
        "version": version,
        "name": "Test Skill",
        "description": "A skill used only for employee-skill-reference tests.",
        "origin": {"type": "internal", "source": "ego-os", "revision": None, "digest": "sha256:" + "0" * 64, "author": "test", "license": "proprietary"},
        "trust": {"state": trust_state, "approved_by": "owner", "approved_at": "2026-07-10T00:00:00Z"},
        "compatibility": {"ego_os": ">=0.4,<1.0", "manifest_schema": "1.x"},
        "entrypoint": {"type": "instructions", "path": "SKILL.md", "digest": _digest(content)},
        "dependencies": {"skills": []},
        "requirements": {"model_capabilities": [], "knowledge_classes": [], "tools": [], "permissions": ["write_repository"], "network": "none", "filesystem": "none"},
        "lifecycle": {"state": lifecycle_state, "replaces": None, "rollback_to": None},
    }
    (package_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    return package_dir


def _attach_skill_to_employee(employee_id, skill_refs, version=None):
    from ego_os import store

    existing = store.get_employee(employee_id)
    store.upsert_employee(
        id=employee_id, name=existing["name"], title=existing["title"], department=existing["department"],
        mission=existing["mission"], required_capabilities=json.loads(existing["required_capabilities"]),
        permissions=json.loads(existing["permissions"]), version=version or existing["version"],
        skills=skill_refs,
    )


def _submit(app_client, owner_credentials, csrf_headers, request_text, project_id=1):
    response = app_client.post(
        "/tasks",
        data={"request_text": request_text, "project_id": project_id},
        auth=owner_credentials,
        headers=csrf_headers,
        follow_redirects=False,
    )
    return int(response.headers["location"].rsplit("/", 1)[-1])


# --- backward compatibility -------------------------------------------------

def test_employee_without_skills_behaves_exactly_as_before(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task):
    from ego_os import store

    fake_model_complete.responses["delegation"] = ("writer", 5, 1, 0.00001)
    fake_model_complete.responses["business_communication"] = ("Done.", 10, 5, 0.00005)
    fake_model_complete.responses["critique"] = ("PASS", 5, 1, 0.00001)

    task_id = _submit(app_client, owner_credentials, csrf_headers, "Write a short note")
    process_task(task_id)

    task = store.get_task(task_id)
    assert task["run_state"] == "completed"
    report = store.get_report(task_id)
    assert report["skills_used"] == []


def test_employee_yaml_skills_field_is_loaded_by_sync(tmp_path, temp_env, monkeypatch):
    """The actual YAML -> DB loading path (ego_os/employees.py), not just
    direct store manipulation."""
    from ego_os import employees, store

    registry_dir = tmp_path / "yaml_registry"
    registry_dir.mkdir()
    (registry_dir / "test_employee.yaml").write_text(
        "id: test_employee\n"
        "name: Test Employee\n"
        "title: Test Employee\n"
        "department: Test\n"
        "version: '1.0'\n"
        "mission: exists only for this test\n"
        "required_capabilities: []\n"
        "permissions: []\n"
        "skills:\n"
        "  - id: some_skill\n"
        "    version: 1.0.0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(employees, "REGISTRY_DIR", registry_dir)
    store.init_db()
    employees.sync_from_registry()

    row = store.get_employee("test_employee")
    assert json.loads(row["skills"]) == [{"id": "some_skill", "version": "1.0.0"}]


# --- valid skill, real task through the lifecycle ---------------------------

def test_employee_with_valid_skill_resolves_and_is_traced(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task, temp_env, monkeypatch):
    from ego_os import skills, store

    registry_root = temp_env["db_path"].parent / "skill_fixtures"
    _write_skill(registry_root, "structured_reporting", "1.0.0")
    monkeypatch.setattr(skills, "REGISTRY_ROOT", registry_root)
    _attach_skill_to_employee("writer", [{"id": "structured_reporting", "version": "1.0.0"}])

    fake_model_complete.responses["delegation"] = ("writer", 5, 1, 0.00001)
    fake_model_complete.responses["business_communication"] = ("Done.", 10, 5, 0.00005)
    fake_model_complete.responses["critique"] = ("PASS", 5, 1, 0.00001)

    task_id = _submit(app_client, owner_credentials, csrf_headers, "Write a short note")
    process_task(task_id)

    task = store.get_task(task_id)
    assert task["run_state"] == "completed"

    report = store.get_report(task_id)
    assert report["skills_used"] == [{"id": "structured_reporting", "version": "1.0.0", "digest": _digest(b"# Test skill.\n")}]

    execution_event = next(e for e in store.get_execution_events(task_id) if e["step"] == "execution")
    assert execution_event["skill_id"] == "structured_reporting"
    assert execution_event["skill_version"] == "1.0.0"
    assert execution_event["skill_digest"] == _digest(b"# Test skill.\n")


def test_two_employees_share_one_skill(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task, temp_env, monkeypatch):
    from ego_os import skills, store

    registry_root = temp_env["db_path"].parent / "skill_fixtures"
    _write_skill(registry_root, "structured_reporting", "1.0.0")
    monkeypatch.setattr(skills, "REGISTRY_ROOT", registry_root)
    _attach_skill_to_employee("writer", [{"id": "structured_reporting", "version": "1.0.0"}])
    _attach_skill_to_employee("cfo", [{"id": "structured_reporting", "version": "1.0.0"}])

    fake_model_complete.responses["delegation"] = ("writer", 5, 1, 0.00001)
    fake_model_complete.responses["business_communication"] = ("Done (writer).", 10, 5, 0.00005)
    fake_model_complete.responses["critique"] = ("PASS", 5, 1, 0.00001)
    task_1 = _submit(app_client, owner_credentials, csrf_headers, "As Writer, write a note")
    process_task(task_1)

    fake_model_complete.responses["delegation"] = ("cfo", 5, 1, 0.00001)
    fake_model_complete.responses["cost_accounting"] = ("Done (cfo).", 10, 5, 0.00005)
    task_2 = _submit(app_client, owner_credentials, csrf_headers, "As CFO, note the cost")
    process_task(task_2)

    report_1 = store.get_report(task_1)
    report_2 = store.get_report(task_2)
    assert report_1["skills_used"][0]["id"] == "structured_reporting"
    assert report_2["skills_used"][0]["id"] == "structured_reporting"


# --- fail-closed cases -------------------------------------------------------

def test_missing_skill_blocks_before_model_invocation(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task, temp_env, monkeypatch):
    from ego_os import skills, store

    registry_root = temp_env["db_path"].parent / "empty_skill_fixtures"
    registry_root.mkdir()
    monkeypatch.setattr(skills, "REGISTRY_ROOT", registry_root)
    _attach_skill_to_employee("writer", [{"id": "does_not_exist", "version": "1.0.0"}])

    fake_model_complete.responses["delegation"] = ("writer", 5, 1, 0.00001)
    # Deliberately no "business_communication" response scripted -- if the
    # specialist step is ever actually invoked, fake_model_complete raises
    # its own AssertionError, which would itself prove the fail-closed
    # check did NOT block it in time.
    task_id = _submit(app_client, owner_credentials, csrf_headers, "Write a short note")
    process_task(task_id)

    task = store.get_task(task_id)
    assert task["run_state"] == "failed"
    assert "does_not_exist" in task["error_message"]
    capabilities_called = {call[0] for call in fake_model_complete.calls}
    assert "business_communication" not in capabilities_called


def test_revoked_skill_blocks_before_model_invocation(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task, temp_env, monkeypatch):
    from ego_os import skills, store

    registry_root = temp_env["db_path"].parent / "revoked_skill_fixtures"
    _write_skill(registry_root, "structured_reporting", "1.0.0", trust_state="revoked", lifecycle_state="revoked")
    monkeypatch.setattr(skills, "REGISTRY_ROOT", registry_root)
    _attach_skill_to_employee("writer", [{"id": "structured_reporting", "version": "1.0.0"}])

    fake_model_complete.responses["delegation"] = ("writer", 5, 1, 0.00001)
    task_id = _submit(app_client, owner_credentials, csrf_headers, "Write a short note")
    process_task(task_id)

    task = store.get_task(task_id)
    assert task["run_state"] == "failed"
    assert "revoked" in task["error_message"].lower()
    capabilities_called = {call[0] for call in fake_model_complete.calls}
    assert "business_communication" not in capabilities_called


def test_tampered_skill_digest_mismatch_blocks_before_model_invocation(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task, temp_env, monkeypatch):
    from ego_os import skills, store

    registry_root = temp_env["db_path"].parent / "tampered_skill_fixtures"
    package_dir = _write_skill(registry_root, "structured_reporting", "1.0.0")
    # Tamper with the entrypoint content after the manifest's digest was computed.
    (package_dir / "SKILL.md").write_bytes(b"# Tampered content, does not match the manifest digest.\n")
    monkeypatch.setattr(skills, "REGISTRY_ROOT", registry_root)
    _attach_skill_to_employee("writer", [{"id": "structured_reporting", "version": "1.0.0"}])

    fake_model_complete.responses["delegation"] = ("writer", 5, 1, 0.00001)
    task_id = _submit(app_client, owner_credentials, csrf_headers, "Write a short note")
    process_task(task_id)

    task = store.get_task(task_id)
    assert task["run_state"] == "failed"
    assert "digest mismatch" in task["error_message"].lower()
    capabilities_called = {call[0] for call in fake_model_complete.calls}
    assert "business_communication" not in capabilities_called


# --- skill requirements never widen permissions ------------------------------

def test_skill_requirements_do_not_widen_employee_permissions(temp_env, monkeypatch):
    """The skill's own manifest declares requirements.permissions =
    ["write_repository"] (see _write_skill) -- writer must not gain that
    permission just because it references the skill."""
    from ego_os import store

    registry_root = temp_env["db_path"].parent / "skill_fixtures"
    _write_skill(registry_root, "structured_reporting", "1.0.0")
    store.init_db()
    from ego_os import employees
    employees.sync_from_registry()

    before = json.loads(store.get_employee("writer")["permissions"])
    _attach_skill_to_employee("writer", [{"id": "structured_reporting", "version": "1.0.0"}])
    after = json.loads(store.get_employee("writer")["permissions"])

    assert before == after
    assert "write_repository" not in after


# --- historical traceability -------------------------------------------------

def test_historical_report_keeps_old_skill_version_after_a_newer_one_is_registered(
    app_client, owner_credentials, csrf_headers, fake_model_complete, process_task, temp_env, monkeypatch,
):
    from ego_os import skills, store

    registry_root = temp_env["db_path"].parent / "skill_fixtures"
    _write_skill(registry_root, "structured_reporting", "1.0.0")
    monkeypatch.setattr(skills, "REGISTRY_ROOT", registry_root)
    _attach_skill_to_employee("writer", [{"id": "structured_reporting", "version": "1.0.0"}])

    fake_model_complete.responses["delegation"] = ("writer", 5, 1, 0.00001)
    fake_model_complete.responses["business_communication"] = ("Done.", 10, 5, 0.00005)
    fake_model_complete.responses["critique"] = ("PASS", 5, 1, 0.00001)
    task_id = _submit(app_client, owner_credentials, csrf_headers, "Write a short note")
    process_task(task_id)

    original_skills_used = store.get_report(task_id)["skills_used"]
    assert original_skills_used == [{"id": "structured_reporting", "version": "1.0.0", "digest": _digest(b"# Test skill.\n")}]

    # A newer version is registered and the employee is re-pointed at it.
    _write_skill(registry_root, "structured_reporting", "1.1.0")
    _attach_skill_to_employee("writer", [{"id": "structured_reporting", "version": "1.1.0"}])

    unchanged = store.get_report(task_id)["skills_used"]
    assert unchanged == original_skills_used


# --- old-schema DB migrates safely -------------------------------------------

def test_old_schema_db_migrates_safely_for_skill_columns(tmp_path, monkeypatch):
    import sqlite3

    from ego_os import store

    db_copy = tmp_path / "pre_sr02_copy.db"
    conn = sqlite3.connect(db_copy)
    conn.execute(
        "CREATE TABLE employees (id TEXT PRIMARY KEY, name TEXT NOT NULL, title TEXT NOT NULL, "
        "department TEXT NOT NULL, mission TEXT NOT NULL, required_capabilities TEXT NOT NULL DEFAULT '[]', "
        "permissions TEXT NOT NULL DEFAULT '[]', version TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'idle')"
    )
    conn.execute(
        "INSERT INTO employees (id, name, title, department, mission, version) "
        "VALUES ('legacy_employee', 'Legacy', 'Legacy', 'Legacy', 'predates Skills', '1.0')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(store, "DB_PATH", db_copy)
    store.init_db()  # must not raise, must backfill skills='[]' for the pre-existing row

    row = store.get_employee("legacy_employee")
    assert json.loads(row["skills"]) == []
