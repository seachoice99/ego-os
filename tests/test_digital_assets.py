"""Digital Asset domain model (DA-01, ADR-0007 / architecture/013).

Every test runs against an isolated temp DB via the `temp_env` fixture --
never the real local ego_os.db. Persistence only: no HTTP route, no
lifecycle/worker involvement (those are DA-02/DA-03's scope).
"""

import json
import sqlite3

import pytest

from ego_os import store, tools


def _make_task(temp_env):
    store.init_db()
    project_id = store.ensure_default_project()
    task_id = store.create_task("Write something reusable", project_id)
    return project_id, task_id


def _provenance(task_id):
    return {
        "report_task_id": task_id,
        "artifacts": [],
        "employee_versions": {},
        "skills_used": [],
        "model": "test-model",
        "created_at": "2026-07-11T00:00:00Z",
    }


def _create_candidate(temp_env, project_id=None, task_id=None, **overrides):
    if task_id is None:
        project_id, task_id = _make_task(temp_env)
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
        provenance=_provenance(task_id),
    )
    kwargs.update(overrides)
    asset_id = store.create_asset_candidate(**kwargs)
    return asset_id, task_id


# --- additive migration -------------------------------------------------

def test_additive_migration_on_old_db_copy(tmp_path, monkeypatch):
    db_copy = tmp_path / "pre_da01_copy.db"
    conn = sqlite3.connect(db_copy)
    conn.execute(
        "CREATE TABLE employees (id TEXT PRIMARY KEY, name TEXT NOT NULL, title TEXT NOT NULL, "
        "department TEXT NOT NULL, mission TEXT NOT NULL, required_capabilities TEXT NOT NULL DEFAULT '[]', "
        "permissions TEXT NOT NULL DEFAULT '[]', version TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'idle')"
    )
    conn.execute(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, vision TEXT, "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute(
        "CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER REFERENCES projects(id), "
        "request_text TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'intake', "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute(
        "CREATE TABLE reports (task_id INTEGER PRIMARY KEY REFERENCES tasks(id), "
        "employees_involved TEXT NOT NULL, timeline TEXT NOT NULL, input_tokens INTEGER NOT NULL DEFAULT 0, "
        "output_tokens INTEGER NOT NULL DEFAULT 0, cost REAL NOT NULL DEFAULT 0, result_text TEXT, qa_note TEXT, "
        "artifacts TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute("INSERT INTO projects (id, name) VALUES (1, 'General')")
    conn.execute("INSERT INTO tasks (id, project_id, request_text, status) VALUES (1, 1, 'old task', 'delivered')")
    conn.execute(
        "INSERT INTO reports (task_id, employees_involved, timeline, result_text) "
        "VALUES (1, '[]', '[]', 'an old-shaped report with no digital_asset reference at all')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(store, "DB_PATH", db_copy)
    store.init_db()  # must not raise; must add digital_assets/digital_asset_events cleanly

    conn = sqlite3.connect(db_copy)
    conn.row_factory = sqlite3.Row
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "digital_assets" in tables
    assert "digital_asset_events" in tables

    # The pre-existing Report row still opens/reads fine -- Reports were not touched.
    report = conn.execute("SELECT * FROM reports WHERE task_id = 1").fetchone()
    assert report["result_text"] == "an old-shaped report with no digital_asset reference at all"
    conn.close()


def test_init_db_twice_is_idempotent(temp_env):
    store.init_db()
    store.init_db()  # must not raise or duplicate anything
    asset_id, _ = _create_candidate(temp_env)
    assert store.get_asset(asset_id) is not None


# --- candidate creation ---------------------------------------------------

def test_creating_candidate_succeeds_and_logs_one_event(temp_env):
    asset_id, task_id = _create_candidate(temp_env)

    asset = store.get_asset(asset_id)
    assert asset["status"] == "candidate"
    assert asset["origin"] == "automatic"
    assert asset["source_task_id"] == task_id

    events = store.get_asset_events(asset_id)
    assert len(events) == 1
    assert events[0]["event_type"] == "candidate_created"
    assert events[0]["actor"] == "system"


def test_create_candidate_against_missing_task_is_rejected(temp_env):
    store.init_db()
    project_id = store.ensure_default_project()
    with pytest.raises(store.DigitalAssetError):
        store.create_asset_candidate(
            project_id=project_id,
            source_task_id=999999,
            title="orphan",
            summary="no such task",
            asset_type="document",
            target_audience="nobody",
            reusable_value="none",
            evidence=[],
            value_thesis="none",
            provenance=_provenance(999999),
        )
    assert store.get_assets() == []


# --- get_asset_by_source_task --------------------------------------------

def test_get_asset_by_source_task_finds_existing_and_none_otherwise(temp_env):
    asset_id, task_id = _create_candidate(temp_env)
    found = store.get_asset_by_source_task(task_id)
    assert found is not None
    assert found["id"] == asset_id

    _, other_task_id = _make_task(temp_env)
    assert store.get_asset_by_source_task(other_task_id) is None


# --- invalid status / event values ---------------------------------------

def test_invalid_status_value_is_rejected(temp_env):
    asset_id, _ = _create_candidate(temp_env)
    with pytest.raises(store.DigitalAssetError):
        store.transition_asset(asset_id, "bogus_status", "owner_accepted", "owner")


def test_invalid_event_type_is_rejected_by_log_asset_event(temp_env):
    asset_id, _ = _create_candidate(temp_env)
    with pytest.raises(store.DigitalAssetError):
        store.log_asset_event(asset_id, "not_a_real_event", "system")


# --- disallowed transitions ------------------------------------------------

def test_candidate_to_internally_validated_directly_is_rejected(temp_env):
    asset_id, _ = _create_candidate(temp_env)
    with pytest.raises(store.DigitalAssetTransitionError):
        store.transition_asset(
            asset_id, "internally_validated", "validation_passed", "system",
            validation_status="passed", monetization_thesis={"who": "x", "value": "y"},
        )
    assert store.get_asset(asset_id)["status"] == "candidate"


def test_accepted_to_internally_validated_missing_validation_status_is_rejected(temp_env):
    asset_id, _ = _create_candidate(temp_env)
    store.transition_asset(asset_id, "accepted", "owner_accepted", "owner")
    with pytest.raises(store.DigitalAssetTransitionError):
        store.transition_asset(
            asset_id, "internally_validated", "validation_passed", "system",
            monetization_thesis={"who": "x", "value": "y"},
        )
    assert store.get_asset(asset_id)["status"] == "accepted"


def test_accepted_to_internally_validated_missing_monetization_thesis_is_rejected(temp_env):
    asset_id, _ = _create_candidate(temp_env)
    store.transition_asset(asset_id, "accepted", "owner_accepted", "owner")
    with pytest.raises(store.DigitalAssetTransitionError):
        store.transition_asset(
            asset_id, "internally_validated", "validation_passed", "system",
            validation_status="passed",
        )
    assert store.get_asset(asset_id)["status"] == "accepted"


def test_accepted_to_internally_validated_succeeds_with_both(temp_env):
    asset_id, _ = _create_candidate(temp_env)
    store.transition_asset(asset_id, "accepted", "owner_accepted", "owner")
    thesis = {
        "who": "internal teams",
        "value": "reusable analysis",
        "cheapest_test": "share it once internally",
        "assumptions": ["audience actually wants it"],
        "prohibited": "any external action without separate Owner approval",
    }
    store.transition_asset(
        asset_id, "internally_validated", "validation_passed", "system",
        validation_status="passed", monetization_thesis=thesis,
    )
    asset = store.get_asset(asset_id)
    assert asset["status"] == "internally_validated"
    assert asset["validation_status"] == "passed"
    assert asset["monetization_thesis"] == thesis


def test_rejected_to_accepted_requires_new_distinct_event(temp_env):
    asset_id, _ = _create_candidate(temp_env)
    store.transition_asset(asset_id, "rejected", "owner_rejected", "owner", detail="not reusable enough")
    assert store.get_asset(asset_id)["status"] == "rejected"

    # A silent flip is never allowed -- only a brand-new, explicit event.
    store.transition_asset(asset_id, "accepted", "owner_accepted", "owner", detail="reconsidered")

    asset = store.get_asset(asset_id)
    assert asset["status"] == "accepted"

    events = store.get_asset_events(asset_id)
    event_types = [e["event_type"] for e in events]
    assert event_types == ["candidate_created", "owner_rejected", "owner_accepted"]
    # The original rejection event is still there, untouched.
    rejected_event = events[1]
    assert rejected_event["event_type"] == "owner_rejected"
    assert rejected_event["detail"] == "not reusable enough"


def test_actor_must_be_owner_for_owner_decision_events(temp_env):
    asset_id, _ = _create_candidate(temp_env)
    with pytest.raises(store.DigitalAssetTransitionError):
        store.transition_asset(asset_id, "accepted", "owner_accepted", "system")
    assert store.get_asset(asset_id)["status"] == "candidate"


def test_unmapped_transition_is_rejected(temp_env):
    asset_id, _ = _create_candidate(temp_env)
    store.transition_asset(asset_id, "rejected", "owner_rejected", "owner")
    with pytest.raises(store.DigitalAssetTransitionError):
        store.transition_asset(asset_id, "internally_validated", "validation_passed", "system",
                                validation_status="passed", monetization_thesis={"a": "b"})


def test_archive_requires_system_or_owner_actor(temp_env):
    asset_id, _ = _create_candidate(temp_env)
    with pytest.raises(store.DigitalAssetTransitionError):
        store.transition_asset(asset_id, "archived", "archived", "anonymous-worker-bug")
    assert store.get_asset(asset_id)["status"] == "candidate"

    # A legitimate actor can still archive from any status.
    store.transition_asset(asset_id, "archived", "archived", "owner")
    assert store.get_asset(asset_id)["status"] == "archived"


def test_event_type_and_validation_status_must_be_consistent(temp_env):
    asset_id, _ = _create_candidate(temp_env)
    store.transition_asset(asset_id, "accepted", "owner_accepted", "owner")
    with pytest.raises(store.DigitalAssetTransitionError):
        store.transition_asset(
            asset_id, "accepted", "validation_started", "system", validation_status="passed",
        )
    assert store.get_asset(asset_id)["validation_status"] is None


def test_log_asset_event_rejects_nonexistent_asset(temp_env):
    store.init_db()
    with pytest.raises(store.DigitalAssetError):
        store.log_asset_event(999999, "thesis_updated", "system")


def test_create_candidate_against_missing_project_is_rejected(temp_env):
    store.init_db()
    _, task_id = _make_task(temp_env)
    with pytest.raises(store.DigitalAssetError):
        store.create_asset_candidate(
            project_id=999999,
            source_task_id=task_id,
            title="orphan project",
            summary="no such project",
            asset_type="document",
            target_audience="nobody",
            reusable_value="none",
            evidence=[],
            value_thesis="none",
            provenance=_provenance(task_id),
        )


# --- provenance immutability -----------------------------------------------

def test_provenance_is_recorded_and_immutable(temp_env):
    _, task_id = _make_task(temp_env)
    provenance = _provenance(task_id)
    asset_id, _ = _create_candidate(temp_env, task_id=task_id, provenance=provenance)

    asset = store.get_asset(asset_id)
    assert asset["provenance"] == provenance

    # An unrelated store call (a status transition) must not mutate provenance.
    store.transition_asset(asset_id, "accepted", "owner_accepted", "owner")
    asset_after = store.get_asset(asset_id)
    assert asset_after["provenance"] == provenance


# --- append-only event history ----------------------------------------------

def test_events_only_ever_grow_across_a_real_sequence(temp_env):
    asset_id, _ = _create_candidate(temp_env)
    counts = [len(store.get_asset_events(asset_id))]

    store.transition_asset(asset_id, "accepted", "owner_accepted", "owner")
    counts.append(len(store.get_asset_events(asset_id)))

    store.transition_asset(
        asset_id, "accepted", "validation_started", "system", validation_status="started",
    )
    counts.append(len(store.get_asset_events(asset_id)))

    store.transition_asset(
        asset_id, "internally_validated", "validation_passed", "system",
        validation_status="passed", monetization_thesis={"who": "x", "value": "y"},
    )
    counts.append(len(store.get_asset_events(asset_id)))

    assert counts == sorted(counts)
    assert all(b > a for a, b in zip(counts, counts[1:]))


def test_no_hard_delete_code_path_exists(temp_env):
    assert not hasattr(store, "delete_asset")
    assert not hasattr(store, "delete_asset_event")
    source = open(store.__file__, encoding="utf-8").read()
    assert "DELETE FROM digital_assets" not in source
    assert "DELETE FROM digital_asset_events" not in source


def test_row_counts_never_decrease_across_full_history(temp_env):
    asset_id, _ = _create_candidate(temp_env)
    conn = sqlite3.connect(temp_env["db_path"])
    counts = []

    def snapshot():
        assets = conn.execute("SELECT COUNT(*) FROM digital_assets").fetchone()[0]
        events = conn.execute("SELECT COUNT(*) FROM digital_asset_events").fetchone()[0]
        counts.append((assets, events))

    snapshot()
    store.transition_asset(asset_id, "accepted", "owner_accepted", "owner")
    snapshot()
    store.transition_asset(
        asset_id, "internally_validated", "validation_passed", "system",
        validation_status="passed", monetization_thesis={"who": "x", "value": "y"},
    )
    snapshot()
    conn.close()

    for (prev_assets, prev_events), (assets, events) in zip(counts, counts[1:]):
        assert assets >= prev_assets
        assert events >= prev_events


# --- artifact-provenance path safety -----------------------------------------

def test_artifact_reference_traversal_is_rejected(temp_env):
    _, task_id = _make_task(temp_env)
    with pytest.raises(tools.ToolError):
        tools.verify_artifact_reference(task_id, "../../evil")


def test_artifact_reference_missing_file_is_rejected(temp_env):
    _, task_id = _make_task(temp_env)
    with pytest.raises(tools.ToolError):
        tools.verify_artifact_reference(task_id, "does_not_exist.pdf")


def test_artifact_reference_valid_file_is_accepted_and_not_copied(temp_env):
    _, task_id = _make_task(temp_env)
    task_dir = tools.GENERATED_DIR / str(task_id)
    task_dir.mkdir(parents=True)
    real_file = task_dir / "report.pdf"
    real_file.write_bytes(b"%PDF-1.4 fake content")

    result = tools.verify_artifact_reference(task_id, "report.pdf")
    assert result == real_file.resolve()
    # Only one copy of the file exists anywhere under GENERATED_DIR.
    all_files = list(tools.GENERATED_DIR.rglob("report.pdf"))
    assert len(all_files) == 1
