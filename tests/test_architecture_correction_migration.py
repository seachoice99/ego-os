"""Additive migration safety for the 2026-07-13 architecture-correction pass
(ADR-0014/0016/architecture/018) -- new tables (product_task_plans,
clarifications, budget_ledger_events, employee_provisioning_tasks) and new
columns (tasks.terminal_reason, reports.schema_version/terminal_status/
terminal_reason) must attach cleanly to a pre-existing DB copy that predates
this pass, without disturbing any row already in it.

Mirrors the existing pattern in tests/test_digital_assets.py
(test_additive_migration_on_old_db_copy) for the same guarantee: init_db()
must never require a fresh DB, and must never touch data it doesn't own.
"""

import sqlite3

from ego_os import store


def test_additive_migration_on_pre_correction_db_copy(tmp_path, monkeypatch):
    db_copy = tmp_path / "pre_2026_07_13_copy.db"
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
    conn.execute(
        "CREATE TABLE employee_proposals (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "task_id INTEGER NOT NULL REFERENCES tasks(id), trigger_text TEXT NOT NULL, title TEXT NOT NULL, "
        "department TEXT NOT NULL, mission TEXT NOT NULL, temporary_or_permanent TEXT NOT NULL, "
        "reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute("INSERT INTO projects (id, name) VALUES (1, 'General')")
    conn.execute(
        "INSERT INTO tasks (id, project_id, request_text, status) VALUES (1, 1, 'old task', 'delivered')"
    )
    conn.execute(
        "INSERT INTO reports (task_id, employees_involved, timeline, result_text) "
        "VALUES (1, '[]', '[]', 'an old-shaped report predating terminal_status/schema_version')"
    )
    conn.execute(
        "INSERT INTO employee_proposals (id, task_id, trigger_text, title, department, mission, "
        "temporary_or_permanent, reason, status) VALUES "
        "(1, 1, 'need a specialist', 'Old Specialist', 'ops', 'do the thing', 'permanent', 'gap', 'approved')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(store, "DB_PATH", db_copy)
    store.init_db()  # must not raise; must add new tables/columns additively

    conn = sqlite3.connect(db_copy)
    conn.row_factory = sqlite3.Row
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for expected in (
        "product_task_plans",
        "clarifications",
        "budget_ledger_events",
        "employee_provisioning_tasks",
    ):
        assert expected in tables

    report_cols = {r["name"] for r in conn.execute("PRAGMA table_info(reports)")}
    for expected in ("schema_version", "terminal_status", "terminal_reason"):
        assert expected in report_cols
    task_cols = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}
    assert "terminal_reason" in task_cols

    # Pre-existing rows are untouched by the migration.
    report = conn.execute("SELECT * FROM reports WHERE task_id = 1").fetchone()
    assert report["result_text"] == "an old-shaped report predating terminal_status/schema_version"
    assert report["schema_version"] == 1
    assert report["terminal_status"] is None
    task = conn.execute("SELECT * FROM tasks WHERE id = 1").fetchone()
    assert task["status"] == "delivered"
    assert task["terminal_reason"] is None
    proposal = conn.execute("SELECT * FROM employee_proposals WHERE id = 1").fetchone()
    assert proposal["status"] == "approved"

    # The global operating budget (ADR-0016, USD 15.00) is seeded exactly once
    # as an append-only ledger event, even on a DB that never had the table.
    ledger_rows = conn.execute(
        "SELECT event_type, amount_cents FROM budget_ledger_events"
    ).fetchall()
    assert len(ledger_rows) == 1
    assert ledger_rows[0]["event_type"] == "budget_approved"
    assert ledger_rows[0]["amount_cents"] == 1500
    conn.close()


def test_additive_migration_is_idempotent_and_never_reseeds_budget(tmp_path, monkeypatch):
    db_copy = tmp_path / "reseed_check.db"
    monkeypatch.setattr(store, "DB_PATH", db_copy)
    store.init_db()
    store.init_db()  # second call must not raise or duplicate the budget seed

    conn = sqlite3.connect(db_copy)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT event_type FROM budget_ledger_events WHERE event_type = 'budget_approved'"
    ).fetchall()
    assert len(rows) == 1
    conn.close()
