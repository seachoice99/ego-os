"""Owner Asset Inbox (DA-02, architecture/013 / ADR-0007): GET /assets,
GET /assets/{id}, POST /assets/{id}/accept, POST /assets/{id}/reject.

Every test runs against an isolated temp DB (see conftest.py's temp_env)
and drives the real HTTP routes -- persistence itself (store.py) is
already covered by tests/test_digital_assets.py (DA-01).
"""

from ego_os import store, tools


def _make_task(project_id=None):
    store.init_db()
    if project_id is None:
        project_id = store.ensure_default_project()
    task_id = store.create_task("Write something reusable", project_id)
    return project_id, task_id


def _provenance(task_id, artifacts=None):
    return {
        "report_task_id": task_id,
        "artifacts": artifacts or [],
        "employee_versions": {"writer": "1.0"},
        "skills_used": [{"id": "structured_reporting", "version": "1.0.0"}],
        "model": "test-model",
        "created_at": "2026-07-11T00:00:00Z",
    }


def _create_candidate(project_id=None, task_id=None, artifacts=None, **overrides):
    if task_id is None:
        project_id, task_id = _make_task(project_id)
    kwargs = dict(
        project_id=project_id,
        source_task_id=task_id,
        title="A reusable asset",
        summary="Something the company built that keeps its value.",
        asset_type="document",
        target_audience="future tasks needing this reference",
        reusable_value="saves re-deriving this analysis",
        evidence=["cited in the delivered report"],
        value_thesis="specific, checkable value for a specific audience",
        provenance=_provenance(task_id, artifacts),
    )
    kwargs.update(overrides)
    asset_id = store.create_asset_candidate(**kwargs)
    return asset_id, project_id, task_id


# --- auth required -----------------------------------------------------------

def test_assets_routes_require_owner_auth(app_client, temp_env):
    asset_id, _, _ = _create_candidate()
    assert app_client.get("/assets").status_code == 401
    assert app_client.get(f"/assets/{asset_id}").status_code == 401


# --- CSRF required for accept/reject -----------------------------------------

def test_accept_and_reject_require_csrf(app_client, owner_credentials, temp_env):
    asset_id, _, _ = _create_candidate()
    response = app_client.post(f"/assets/{asset_id}/accept", auth=owner_credentials)
    assert response.status_code == 403
    response = app_client.post(f"/assets/{asset_id}/reject", auth=owner_credentials)
    assert response.status_code == 403
    # Neither request without CSRF actually changed anything.
    assert store.get_asset(asset_id)["status"] == "candidate"


# --- list page -----------------------------------------------------------------

def test_list_page_shows_real_candidate(app_client, owner_credentials, temp_env):
    asset_id, project_id, task_id = _create_candidate(title="Reusable Onboarding Guide")
    response = app_client.get("/assets", auth=owner_credentials)
    assert response.status_code == 200
    assert "Reusable Onboarding Guide" in response.text
    assert f"/assets/{asset_id}" in response.text
    assert f"/tasks/{task_id}" in response.text
    assert "General" in response.text  # default project name


def test_list_page_groups_by_status(app_client, owner_credentials, temp_env):
    candidate_id, _, _ = _create_candidate(title="Still A Candidate")
    accepted_id, _, _ = _create_candidate(title="Now Accepted")
    store.transition_asset(accepted_id, "accepted", "owner_accepted", "owner")
    rejected_id, _, _ = _create_candidate(title="Now Rejected")
    store.transition_asset(rejected_id, "rejected", "owner_rejected", "owner")

    response = app_client.get("/assets", auth=owner_credentials)
    assert response.status_code == 200
    text = response.text
    # Each title appears exactly once (it must land in exactly one group).
    for title in ("Still A Candidate", "Now Accepted", "Now Rejected"):
        assert text.count(title) == 1


# --- detail page -----------------------------------------------------------------

def test_detail_page_renders_provenance_evidence_and_event_history(app_client, owner_credentials, temp_env):
    _, task_id = _make_task()
    task_dir = tools.GENERATED_DIR / str(task_id)
    task_dir.mkdir(parents=True)
    (task_dir / "report.pdf").write_bytes(b"%PDF-1.4 fake content")

    asset_id, project_id, task_id = _create_candidate(
        task_id=task_id,
        artifacts=[{"filename": "report.pdf", "type": "pdf", "task_id": task_id}],
    )
    store.transition_asset(asset_id, "accepted", "owner_accepted", "owner", detail="looks solid")

    response = app_client.get(f"/assets/{asset_id}", auth=owner_credentials)
    assert response.status_code == 200
    text = response.text
    # Evidence and provenance fields.
    assert "cited in the delivered report" in text
    assert "specific, checkable value for a specific audience" in text
    assert f"/tasks/{task_id}" in text
    assert f"/tasks/{task_id}/artifacts/report.pdf" in text
    assert "test-model" in text
    assert "writer" in text
    assert "structured_reporting" in text
    # Monetization thesis has not been set yet (only DA-04 adds that).
    assert "not yet validated" in text
    # Event history: candidate_created then owner_accepted.
    assert "candidate_created" in text
    assert "owner_accepted" in text
    assert "looks solid" in text


def test_unknown_asset_id_returns_404(app_client, owner_credentials, temp_env):
    store.init_db()
    response = app_client.get("/assets/999999", auth=owner_credentials)
    assert response.status_code == 404


# --- accept / reject -----------------------------------------------------------

def test_accept_transitions_candidate_to_accepted_and_logs_owner_event(app_client, owner_credentials, csrf_headers, temp_env):
    asset_id, _, _ = _create_candidate()
    response = app_client.post(f"/assets/{asset_id}/accept", auth=owner_credentials, headers=csrf_headers)
    assert response.status_code == 200  # TestClient follows the 303 redirect

    asset = store.get_asset(asset_id)
    assert asset["status"] == "accepted"
    events = store.get_asset_events(asset_id)
    assert [e["event_type"] for e in events] == ["candidate_created", "owner_accepted"]
    assert events[-1]["actor"] == "owner"


def test_reject_transitions_candidate_to_rejected_and_logs_owner_event(app_client, owner_credentials, csrf_headers, temp_env):
    asset_id, _, _ = _create_candidate()
    response = app_client.post(f"/assets/{asset_id}/reject", auth=owner_credentials, headers=csrf_headers)
    assert response.status_code == 200

    asset = store.get_asset(asset_id)
    assert asset["status"] == "rejected"
    events = store.get_asset_events(asset_id)
    assert [e["event_type"] for e in events] == ["candidate_created", "owner_rejected"]
    assert events[-1]["actor"] == "owner"


def test_accept_or_reject_unknown_asset_returns_404(app_client, owner_credentials, csrf_headers, temp_env):
    store.init_db()
    assert app_client.post("/assets/999999/accept", auth=owner_credentials, headers=csrf_headers).status_code == 404
    assert app_client.post("/assets/999999/reject", auth=owner_credentials, headers=csrf_headers).status_code == 404


# --- repeat / invalid transitions: clear error, never a crash or duplicate -----

def test_accepting_an_already_accepted_asset_returns_clear_error_not_crash(app_client, owner_credentials, csrf_headers, temp_env):
    asset_id, _, _ = _create_candidate()
    store.transition_asset(asset_id, "accepted", "owner_accepted", "owner")

    response = app_client.post(f"/assets/{asset_id}/accept", auth=owner_credentials, headers=csrf_headers)
    assert response.status_code == 400  # clear 4xx, not a 500 and not a silent no-op

    # No duplicate owner_accepted event, and status is unchanged.
    events = store.get_asset_events(asset_id)
    assert [e["event_type"] for e in events] == ["candidate_created", "owner_accepted"]
    assert store.get_asset(asset_id)["status"] == "accepted"


def test_accepting_an_already_internally_validated_asset_returns_clear_error(app_client, owner_credentials, csrf_headers, temp_env):
    asset_id, _, _ = _create_candidate()
    store.transition_asset(asset_id, "accepted", "owner_accepted", "owner")
    thesis = {"who": "internal teams", "value": "reusable analysis", "cheapest_test": "share it internally",
              "assumptions": ["audience wants it"], "prohibited": "any external action"}
    store.transition_asset(
        asset_id, "internally_validated", "validation_passed", "system",
        validation_status="passed", monetization_thesis=thesis,
    )

    response = app_client.post(f"/assets/{asset_id}/accept", auth=owner_credentials, headers=csrf_headers)
    assert response.status_code == 400

    assert store.get_asset(asset_id)["status"] == "internally_validated"
    # There is no route in this task that could have set validation_status
    # or monetization_thesis itself -- confirm they're unchanged from DA-01's own write.
    assert store.get_asset(asset_id)["monetization_thesis"] == thesis


def test_double_submit_accept_does_not_produce_two_owner_accepted_events(app_client, owner_credentials, csrf_headers, temp_env):
    asset_id, _, _ = _create_candidate()
    first = app_client.post(f"/assets/{asset_id}/accept", auth=owner_credentials, headers=csrf_headers)
    second = app_client.post(f"/assets/{asset_id}/accept", auth=owner_credentials, headers=csrf_headers)

    assert first.status_code == 200
    assert second.status_code == 400  # error-on-repeat, chosen and proven consistently

    events = store.get_asset_events(asset_id)
    owner_accepted_events = [e for e in events if e["event_type"] == "owner_accepted"]
    assert len(owner_accepted_events) == 1


def test_accepting_a_rejected_candidate_succeeds_as_a_fresh_distinct_decision(app_client, owner_credentials, csrf_headers, temp_env):
    asset_id, _, _ = _create_candidate()
    app_client.post(f"/assets/{asset_id}/reject", auth=owner_credentials, headers=csrf_headers)
    assert store.get_asset(asset_id)["status"] == "rejected"

    response = app_client.post(f"/assets/{asset_id}/accept", auth=owner_credentials, headers=csrf_headers)
    assert response.status_code == 200

    asset = store.get_asset(asset_id)
    assert asset["status"] == "accepted"
    events = store.get_asset_events(asset_id)
    assert [e["event_type"] for e in events] == ["candidate_created", "owner_rejected", "owner_accepted"]
    # The original rejection event is still there, untouched -- not deleted.
    assert events[1]["event_type"] == "owner_rejected"


# --- provenance is never edited by accept/reject --------------------------------

def test_accept_never_edits_provenance(app_client, owner_credentials, csrf_headers, temp_env):
    asset_id, _, task_id = _create_candidate()
    before = store.get_asset(asset_id)["provenance"]

    app_client.post(f"/assets/{asset_id}/accept", auth=owner_credentials, headers=csrf_headers)

    after = store.get_asset(asset_id)["provenance"]
    assert after == before


# --- HTML escaping -----------------------------------------------------------------

def test_html_in_title_and_summary_is_escaped_not_executed(app_client, owner_credentials, temp_env):
    asset_id, _, _ = _create_candidate(
        title="<script>alert(1)</script>",
        summary="<img src=x onerror=alert(2)>",
        evidence=["<b>bold evidence</b>"],
    )

    list_response = app_client.get("/assets", auth=owner_credentials)
    detail_response = app_client.get(f"/assets/{asset_id}", auth=owner_credentials)

    for response in (list_response, detail_response):
        assert "<script>alert(1)</script>" not in response.text
        assert "<img src=x onerror=alert(2)>" not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in detail_response.text
    assert "&lt;img src=x onerror=alert(2)&gt;" in detail_response.text
    assert "&lt;b&gt;bold evidence&lt;/b&gt;" in detail_response.text


# --- provenance artifact links reuse the existing download route ----------------

def test_provenance_renders_correct_task_and_artifact_links(app_client, owner_credentials, temp_env):
    _, task_id = _make_task()
    task_dir = tools.GENERATED_DIR / str(task_id)
    task_dir.mkdir(parents=True)
    (task_dir / "summary.pdf").write_bytes(b"%PDF-1.4 fake content")

    asset_id, _, task_id = _create_candidate(
        task_id=task_id,
        artifacts=[{"filename": "summary.pdf", "type": "pdf", "task_id": task_id}],
    )
    response = app_client.get(f"/assets/{asset_id}", auth=owner_credentials)
    assert response.status_code == 200
    # Exactly the existing download route -- no new download path invented.
    assert f"/tasks/{task_id}/artifacts/summary.pdf" in response.text
    assert "/assets/" + str(asset_id) + "/artifacts" not in response.text


# --- pre-existing routes unaffected -----------------------------------------------

def test_existing_routes_still_work(app_client, owner_credentials):
    assert app_client.get("/", auth=owner_credentials).status_code == 200
    assert app_client.get("/dashboard", auth=owner_credentials).status_code == 200
    assert app_client.get("/skills", auth=owner_credentials).status_code == 200
    assert app_client.get("/employees/writer", auth=owner_credentials).status_code == 200
