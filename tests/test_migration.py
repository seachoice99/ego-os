"""Schema migration safety (v0.4.1): adding tasks.run_state/error_message
to a database that predates the background worker must not make the
worker try to re-run the company's entire task history. Always run
against a throwaway temp-copy DB -- never the real local ego_os.db or
production.
"""

import sqlite3


def _build_pre_v041_db(db_path):
    """A minimal stand-in for a real pre-v0.4.1 database: tasks existed,
    ran synchronously, and reached a real terminal `status` -- but had no
    run_state/error_message columns at all yet."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            request_text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'intake',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        "INSERT INTO tasks (project_id, request_text, status) VALUES (1, 'a real historical task', 'delivered')"
    )
    conn.execute(
        "INSERT INTO tasks (project_id, request_text, status) VALUES (1, 'a paused historical task', 'awaiting_approval')"
    )
    conn.commit()
    conn.close()


def test_run_state_migration_backfills_completed_not_queued(tmp_path, monkeypatch):
    """The critical assertion: without the backfill, ALTER TABLE ... ADD
    COLUMN run_state TEXT DEFAULT 'queued' would leave every pre-existing
    row at 'queued', and the new worker would try to (re-)process the
    company's entire history on first boot after upgrading."""
    from ego_os import store

    db_copy = tmp_path / "pre_v041_copy.db"  # a throwaway copy, never the real DB
    _build_pre_v041_db(db_copy)

    monkeypatch.setattr(store, "DB_PATH", db_copy)
    store.init_db()

    tasks = store.get_tasks()
    assert len(tasks) == 2
    for task in tasks:
        assert task["run_state"] == "completed"
        assert task["error_message"] is None


def test_run_state_migration_is_idempotent_across_repeated_startups(tmp_path, monkeypatch):
    """init_db() runs on every startup -- calling it again after the
    column already exists must not re-run the backfill and clobber a
    since-updated run_state (e.g. a task the worker later marked 'failed')."""
    from ego_os import store

    db_copy = tmp_path / "pre_v041_copy2.db"
    _build_pre_v041_db(db_copy)
    monkeypatch.setattr(store, "DB_PATH", db_copy)

    store.init_db()
    task_id = store.get_tasks()[0]["id"]
    store.set_task_run_state(task_id, "failed", error_message="a later real failure")

    store.init_db()  # simulates a second app startup

    task = store.get_task(task_id)
    assert task["run_state"] == "failed"
    assert task["error_message"] == "a later real failure"
