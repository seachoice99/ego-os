"""First internal Skill (SR-03): structured_reporting, attached to Coder
and Researcher. Uses the *real* on-disk skill package under
skills/registry/ (not a synthetic fixture) so these tests exercise
exactly what ships to production.
"""

import json


_REQUIRED_SECTIONS = (
    "Goal", "Actions taken", "Evidence", "Changed files or artifacts",
    "Tests / checks performed", "Risks", "Cost", "Open questions", "Final status",
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


def test_real_skill_package_resolves_and_is_readable():
    """The actual, real, committed package -- not a fixture."""
    from ego_os import skills

    manifest = skills.get_exact_version("structured_reporting", "1.0.0")
    assert manifest["trust"]["state"] == "approved"
    assert manifest["lifecycle"]["state"] == "active"
    instructions_path = manifest["_package_dir"] / manifest["entrypoint"]["path"]
    instructions = instructions_path.read_text(encoding="utf-8")
    for section in _REQUIRED_SECTIONS:
        assert section in instructions


def test_coder_and_researcher_yaml_both_reference_the_real_skill():
    import yaml

    coder = yaml.safe_load(open("company/employees/core/coder.yaml", encoding="utf-8"))
    researcher = yaml.safe_load(open("company/employees/core/researcher.yaml", encoding="utf-8"))
    assert {"id": "structured_reporting", "version": "1.0.0"} in coder["skills"]
    assert {"id": "structured_reporting", "version": "1.0.0"} in researcher["skills"]
    # Persona/responsibilities/permissions were not removed by attaching the skill.
    assert coder["responsibilities"] == ["inspect codebase", "create files", "write code", "run tests", "document changes"]
    assert coder["permissions"] == ["read_repository", "write_repository", "run_local_commands"]
    assert researcher["permissions"] == ["use_web", "read_project_memory", "create_research_notes"]


def _shared_report_structure_and_role_rules_preserved(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task, specialist_id, capability, request_text, role_specific_marker):
    from ego_os import store

    draft_text = "\n".join(f"## {s}\nsample content for {s}" for s in _REQUIRED_SECTIONS) + f"\n\n{role_specific_marker}"

    fake_model_complete.responses["delegation"] = (specialist_id, 5, 1, 0.00001)
    fake_model_complete.responses[capability] = (draft_text, 20, 10, 0.0001)
    fake_model_complete.responses["critique"] = ("PASS", 5, 1, 0.00001)

    task_id = _submit(app_client, owner_credentials, csrf_headers, request_text)
    process_task(task_id)

    task = store.get_task(task_id)
    assert task["run_state"] == "completed"
    report = store.get_report(task_id)
    for section in _REQUIRED_SECTIONS:
        assert section in report["result_text"]
    assert role_specific_marker in report["result_text"]
    assert report["skills_used"] == [
        {"id": "structured_reporting", "version": "1.0.0", "digest": _real_digest()}
    ]
    return report


def _real_digest():
    from ego_os import skills

    manifest = skills.get_exact_version("structured_reporting", "1.0.0")
    return manifest["entrypoint"]["digest"]


def test_coder_keeps_shared_structure_and_its_own_role_specific_rules(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task):
    _shared_report_structure_and_role_rules_preserved(
        app_client, owner_credentials, csrf_headers, fake_model_complete, process_task,
        specialist_id="coder", capability="coding",
        request_text="As Coder, note that no files needed changing for this check.",
        role_specific_marker="Changed files: none. Tests run: not applicable for this check.",
    )


def test_researcher_keeps_shared_structure_and_its_own_role_specific_rules(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task):
    _shared_report_structure_and_role_rules_preserved(
        app_client, owner_credentials, csrf_headers, fake_model_complete, process_task,
        specialist_id="researcher", capability="synthesis",
        request_text="As Researcher, summarize a known, uncontroversial fact.",
        role_specific_marker="Source: internal knowledge, no live search performed. Uncertainty: low.",
    )


def test_skill_instructions_appear_after_persona_framing_in_the_actual_prompt(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task):
    """Skill does not erase Persona: the 'You are the {title}... Mission:'
    framing must still appear, and appear *before* the Skill's own
    instructions, in the literal prompt sent to the model."""
    fake_model_complete.responses["delegation"] = ("coder", 5, 1, 0.00001)
    fake_model_complete.responses["coding"] = ("## Goal\nok\n## Actions taken\nok\n## Evidence\nok\n## Changed files or artifacts\nnone\n## Tests / checks performed\nnone\n## Risks\nnone\n## Cost\nnone\n## Open questions\nnone\n## Final status\ndelivered", 20, 10, 0.0001)
    fake_model_complete.responses["critique"] = ("PASS", 5, 1, 0.00001)

    task_id = _submit(app_client, owner_credentials, csrf_headers, "As Coder, note this check.")
    process_task(task_id)

    coding_prompts = [call[1] for call in fake_model_complete.calls if call[0] == "coding"]
    assert coding_prompts, "coder's capability was never invoked"
    prompt = coding_prompts[0]
    persona_index = prompt.find("You are the Coder at a digital company. Mission:")
    skill_index = prompt.find("Follow this Skill (structured_reporting@1.0.0)")
    assert persona_index != -1
    assert skill_index != -1
    assert persona_index < skill_index


def test_missing_skill_blocks_coder_before_model_invocation(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task, temp_env, monkeypatch):
    """If the real package were ever missing/revoked, Coder must fail
    closed before its model is invoked -- proven here by pointing the
    registry at an empty directory."""
    from ego_os import skills, store

    empty_root = temp_env["db_path"].parent / "no_skills_here"
    empty_root.mkdir()
    monkeypatch.setattr(skills, "REGISTRY_ROOT", empty_root)

    fake_model_complete.responses["delegation"] = ("coder", 5, 1, 0.00001)
    task_id = _submit(app_client, owner_credentials, csrf_headers, "As Coder, note this check.")
    process_task(task_id)

    task = store.get_task(task_id)
    assert task["run_state"] == "failed"
    capabilities_called = {call[0] for call in fake_model_complete.calls}
    assert "coding" not in capabilities_called


def test_old_task_history_unaffected_by_attaching_the_skill(app_client, owner_credentials, csrf_headers, fake_model_complete, process_task):
    """A task delivered by Coder *before* structured_reporting existed
    (simulated here by an employee_versions snapshot with no skill data)
    must keep rendering exactly as it always did -- old reports have no
    skills_used at all, and that must not break anything."""
    from ego_os import store

    project_id = store.ensure_default_project()
    task_id = store.create_task("a task delivered before Skills existed", project_id)
    store.create_report(
        task_id=task_id, employees_involved=["orchestrator", "coder", "qa"], timeline=[],
        input_tokens=1, output_tokens=1, cost=0.0, result_text="old-style delivered content",
        qa_note="PASS", employee_versions={"coder": "1.0"},
        # skills_used intentionally omitted -- defaults to [] via create_report
    )
    report = store.get_report(task_id)
    assert report["skills_used"] == []
    assert report["result_text"] == "old-style delivered content"
