"""Skills UI and audit trail (SR-04): a read-only `/skills` list and
`/skills/{id}/{version}` detail page, an append-only Skill audit trail
in its own table, and proof that none of this lets the UI mutate the
Registry, execute Skill content, or leak a secret.
"""

import hashlib
import json


def _digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _write_skill(root, skill_id, version, *, trust_state="approved", lifecycle_state="active",
                  name="Test Skill", description="A skill used only for UI tests.",
                  content=b"# Test skill.\n"):
    import yaml

    package_dir = root / skill_id / version
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "SKILL.md").write_bytes(content)
    manifest = {
        "schema_version": "1.0",
        "id": skill_id,
        "version": version,
        "name": name,
        "description": description,
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


# --- list page ---------------------------------------------------------------

def test_skills_list_page_returns_200_and_shows_skill(app_client, owner_credentials, temp_env, monkeypatch):
    from ego_os import skills

    registry_root = temp_env["db_path"].parent / "skill_fixtures"
    _write_skill(registry_root, "structured_reporting", "1.0.0")
    monkeypatch.setattr(skills, "REGISTRY_ROOT", registry_root)

    response = app_client.get("/skills", auth=owner_credentials)
    assert response.status_code == 200
    assert "structured_reporting" in response.text
    assert "1.0.0" in response.text
    assert "approved" in response.text


# --- detail page ---------------------------------------------------------------

def test_skill_detail_page_returns_200_with_manifest_fields(app_client, owner_credentials, temp_env, monkeypatch):
    from ego_os import skills

    registry_root = temp_env["db_path"].parent / "skill_fixtures"
    _write_skill(registry_root, "structured_reporting", "1.0.0")
    monkeypatch.setattr(skills, "REGISTRY_ROOT", registry_root)

    response = app_client.get("/skills/structured_reporting/1.0.0", auth=owner_credentials)
    assert response.status_code == 200
    assert "structured_reporting" in response.text
    assert "SKILL.md" in response.text
    assert _digest(b"# Test skill.\n") in response.text


# --- auth required -------------------------------------------------------------

def test_skills_routes_require_owner_auth(app_client, temp_env, monkeypatch):
    from ego_os import skills

    registry_root = temp_env["db_path"].parent / "skill_fixtures"
    _write_skill(registry_root, "structured_reporting", "1.0.0")
    monkeypatch.setattr(skills, "REGISTRY_ROOT", registry_root)

    assert app_client.get("/skills").status_code == 401
    assert app_client.get("/skills/structured_reporting/1.0.0").status_code == 401


# --- HTML escaping ---------------------------------------------------------------

def test_manifest_content_is_html_escaped_not_executed(app_client, owner_credentials, temp_env, monkeypatch):
    from ego_os import skills

    registry_root = temp_env["db_path"].parent / "skill_fixtures"
    _write_skill(
        registry_root, "structured_reporting", "1.0.0",
        name="<script>alert(1)</script>",
        description="<img src=x onerror=alert(2)>",
    )
    monkeypatch.setattr(skills, "REGISTRY_ROOT", registry_root)

    list_response = app_client.get("/skills", auth=owner_credentials)
    detail_response = app_client.get("/skills/structured_reporting/1.0.0", auth=owner_credentials)

    for response in (list_response, detail_response):
        assert "<script>alert(1)</script>" not in response.text
        assert "<img src=x onerror=alert(2)>" not in response.text
    assert "&lt;script&gt;" in detail_response.text
    assert "&lt;img src=x onerror=alert(2)&gt;" in detail_response.text


# --- unknown skill 404 ---------------------------------------------------------

def test_unknown_skill_detail_returns_404(app_client, owner_credentials, temp_env, monkeypatch):
    from ego_os import skills

    registry_root = temp_env["db_path"].parent / "empty_skill_fixtures"
    registry_root.mkdir()
    monkeypatch.setattr(skills, "REGISTRY_ROOT", registry_root)

    response = app_client.get("/skills/does_not_exist/1.0.0", auth=owner_credentials)
    assert response.status_code == 404


# --- revoked skill visible but not executable -----------------------------------

def test_revoked_skill_is_visible_but_not_executable(app_client, owner_credentials, temp_env, monkeypatch):
    from ego_os import skills

    registry_root = temp_env["db_path"].parent / "revoked_skill_fixtures"
    _write_skill(registry_root, "structured_reporting", "1.0.0", trust_state="revoked", lifecycle_state="revoked")
    monkeypatch.setattr(skills, "REGISTRY_ROOT", registry_root)

    list_response = app_client.get("/skills", auth=owner_credentials)
    detail_response = app_client.get("/skills/structured_reporting/1.0.0", auth=owner_credentials)
    assert list_response.status_code == 200
    assert detail_response.status_code == 200
    assert "revoked" in list_response.text
    assert "revoked" in detail_response.text

    import pytest
    with pytest.raises(skills.SkillRevokedError):
        skills.get_exact_version("structured_reporting", "1.0.0", registry_root=registry_root)
    with pytest.raises(skills.SkillNotFoundError):
        skills.resolve_compatible_version("structured_reporting", registry_root=registry_root)


# --- viewing a read-only page must never mutate the audit trail -----------------

def test_viewing_list_page_twice_appends_no_audit_events(app_client, owner_credentials, temp_env, monkeypatch):
    """The bug this quality follow-up fixes: GET /skills used to log a
    'validated' event on every page view, so a read-only UI was silently
    mutating state just by being looked at. Viewing it any number of
    times must not change the audit trail at all."""
    from ego_os import skills, store

    registry_root = temp_env["db_path"].parent / "skill_fixtures"
    _write_skill(registry_root, "structured_reporting", "1.0.0")
    monkeypatch.setattr(skills, "REGISTRY_ROOT", registry_root)

    before = len(store.get_skill_audit_events("structured_reporting"))
    response_1 = app_client.get("/skills", auth=owner_credentials)
    after_one = len(store.get_skill_audit_events("structured_reporting"))
    response_2 = app_client.get("/skills", auth=owner_credentials)
    after_two = len(store.get_skill_audit_events("structured_reporting"))

    assert response_1.status_code == 200
    assert response_2.status_code == 200
    assert after_one == before
    assert after_two == before


def test_viewing_detail_page_twice_appends_no_audit_events(app_client, owner_credentials, temp_env, monkeypatch):
    from ego_os import skills, store

    registry_root = temp_env["db_path"].parent / "skill_fixtures"
    _write_skill(registry_root, "structured_reporting", "1.0.0")
    monkeypatch.setattr(skills, "REGISTRY_ROOT", registry_root)

    before = len(store.get_skill_audit_events("structured_reporting"))
    app_client.get("/skills/structured_reporting/1.0.0", auth=owner_credentials)
    app_client.get("/skills/structured_reporting/1.0.0", auth=owner_credentials)
    after = len(store.get_skill_audit_events("structured_reporting"))

    assert after == before


def test_real_skill_resolution_logs_exactly_one_validated_event(
    app_client, owner_credentials, csrf_headers, fake_model_complete, process_task, temp_env, monkeypatch,
):
    """A real operational validation -- a Skill actually resolved (loaded,
    digest-checked) for a real task -- is exactly what 'validated' should
    mean, and it fires exactly once per skill per task, not once per QA
    revision reusing the same already-resolved manifest."""
    from ego_os import skills, store

    registry_root = temp_env["db_path"].parent / "skill_fixtures"
    _write_skill(registry_root, "structured_reporting", "1.0.0")
    monkeypatch.setattr(skills, "REGISTRY_ROOT", registry_root)
    _attach_skill_to_employee("writer", [{"id": "structured_reporting", "version": "1.0.0"}])

    fake_model_complete.responses["delegation"] = ("writer", 5, 1, 0.00001)
    fake_model_complete.responses["business_communication"] = ("Done.", 10, 5, 0.00005)
    fake_model_complete.responses["critique"] = ("PASS", 5, 1, 0.00001)

    before = store.get_skill_audit_events("structured_reporting")
    response = app_client.post(
        "/tasks", data={"request_text": "Write a short note", "project_id": 1},
        auth=owner_credentials, headers=csrf_headers, follow_redirects=False,
    )
    task_id = int(response.headers["location"].rsplit("/", 1)[-1])
    process_task(task_id)

    assert store.get_task(task_id)["run_state"] == "completed"
    after = store.get_skill_audit_events("structured_reporting")
    new_events = [e for e in after if e["id"] not in {row["id"] for row in before}]
    assert len(new_events) == 1
    assert new_events[0]["event_type"] == "validated"
    assert new_events[0]["skill_version"] == "1.0.0"

    last_check = store.get_last_skill_check("structured_reporting")
    assert last_check["id"] == new_events[0]["id"]


def test_attach_and_detach_are_logged_via_sync_from_registry(tmp_path, temp_env, monkeypatch):
    from ego_os import employees, skills, store

    registry_root = temp_env["db_path"].parent / "skill_fixtures"
    _write_skill(registry_root, "structured_reporting", "1.0.0")
    monkeypatch.setattr(skills, "REGISTRY_ROOT", registry_root)
    store.init_db()

    yaml_registry = tmp_path / "yaml_registry"
    yaml_registry.mkdir()
    employee_yaml = yaml_registry / "test_employee.yaml"
    employee_yaml.write_text(
        "id: test_employee\nname: Test Employee\ntitle: Test Employee\ndepartment: Test\n"
        "version: '1.0'\nmission: exists only for this test\nrequired_capabilities: []\npermissions: []\n"
        "skills:\n  - id: structured_reporting\n    version: 1.0.0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(employees, "REGISTRY_DIR", yaml_registry)
    employees.sync_from_registry()

    attached_events = [e for e in store.get_skill_audit_events("structured_reporting") if e["event_type"] == "attached"]
    assert len(attached_events) == 1

    employee_yaml.write_text(
        "id: test_employee\nname: Test Employee\ntitle: Test Employee\ndepartment: Test\n"
        "version: '1.1'\nmission: exists only for this test\nrequired_capabilities: []\npermissions: []\n"
        "skills: []\n",
        encoding="utf-8",
    )
    employees.sync_from_registry()

    detached_events = [e for e in store.get_skill_audit_events("structured_reporting") if e["event_type"] == "detached"]
    assert len(detached_events) == 1


# --- audit contains no secrets ---------------------------------------------------

def test_audit_trail_never_contains_owner_credentials(
    app_client, owner_credentials, csrf_headers, fake_model_complete, process_task, temp_env, monkeypatch,
):
    """Audit events now only come from real operational activity (a real
    Skill resolution, or a real attach/detach), not from viewing a page --
    so this test has to generate real events the same way, then check
    none of them leak the Owner password."""
    from ego_os import skills, store

    registry_root = temp_env["db_path"].parent / "skill_fixtures"
    _write_skill(registry_root, "structured_reporting", "1.0.0")
    monkeypatch.setattr(skills, "REGISTRY_ROOT", registry_root)
    _attach_skill_to_employee("writer", [{"id": "structured_reporting", "version": "1.0.0"}])

    fake_model_complete.responses["delegation"] = ("writer", 5, 1, 0.00001)
    fake_model_complete.responses["business_communication"] = ("Done.", 10, 5, 0.00005)
    fake_model_complete.responses["critique"] = ("PASS", 5, 1, 0.00001)
    response = app_client.post(
        "/tasks", data={"request_text": "Write a short note", "project_id": 1},
        auth=owner_credentials, headers=csrf_headers, follow_redirects=False,
    )
    process_task(int(response.headers["location"].rsplit("/", 1)[-1]))

    app_client.get("/skills", auth=owner_credentials)
    app_client.get("/skills/structured_reporting/1.0.0", auth=owner_credentials)

    events = store.get_skill_audit_events("structured_reporting")
    assert events
    _, password = owner_credentials
    for event in events:
        assert password not in (event["detail"] or "")
        assert "OWNER_PASSWORD" not in (event["detail"] or "")


# --- Employee usage mapping -------------------------------------------------------

def test_employee_usage_mapping_shown_on_list_and_detail(app_client, owner_credentials, temp_env, monkeypatch):
    from ego_os import skills

    registry_root = temp_env["db_path"].parent / "skill_fixtures"
    _write_skill(registry_root, "structured_reporting", "1.0.0")
    monkeypatch.setattr(skills, "REGISTRY_ROOT", registry_root)
    _attach_skill_to_employee("writer", [{"id": "structured_reporting", "version": "1.0.0"}])
    _attach_skill_to_employee("cfo", [{"id": "structured_reporting", "version": "1.0.0"}])

    list_response = app_client.get("/skills", auth=owner_credentials)
    detail_response = app_client.get("/skills/structured_reporting/1.0.0", auth=owner_credentials)

    for response in (list_response, detail_response):
        assert "/employees/writer" in response.text
        assert "/employees/cfo" in response.text


# --- old routes not broken -----------------------------------------------------

def test_existing_routes_still_work(app_client, owner_credentials):
    assert app_client.get("/dashboard", auth=owner_credentials).status_code == 200
    assert app_client.get("/employees/writer", auth=owner_credentials).status_code == 200
    assert app_client.get("/", auth=owner_credentials).status_code == 200
