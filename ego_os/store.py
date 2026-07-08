import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "ego_os.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    title TEXT NOT NULL,
    department TEXT NOT NULL,
    mission TEXT NOT NULL,
    required_capabilities TEXT NOT NULL DEFAULT '[]',
    permissions TEXT NOT NULL DEFAULT '[]',
    version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'idle'
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    vision TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id),
    request_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'intake',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reports (
    task_id INTEGER PRIMARY KEY REFERENCES tasks(id),
    employees_involved TEXT NOT NULL,
    timeline TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost REAL NOT NULL DEFAULT 0,
    result_text TEXT,
    qa_note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_column(conn, table, column, coldef):
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coldef}")


def init_db():
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        # Migrations for databases created before Phase 1.
        _ensure_column(conn, "employees", "required_capabilities", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "tasks", "project_id", "INTEGER REFERENCES projects(id)")
        # Migration for databases created before the Tool Framework (v0.2).
        _ensure_column(conn, "employees", "permissions", "TEXT NOT NULL DEFAULT '[]'")
        conn.commit()
    finally:
        conn.close()


def ensure_default_project():
    conn = get_connection()
    try:
        row = conn.execute("SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()
        if row:
            return row["id"]
        cur = conn.execute(
            "INSERT INTO projects (name, vision) VALUES (?, ?)",
            ("General", "The Owner's default working context."),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def upsert_employee(id, name, title, department, mission, required_capabilities, permissions, version):
    conn = get_connection()
    try:
        capabilities_json = json.dumps(required_capabilities)
        permissions_json = json.dumps(permissions)
        existing = conn.execute("SELECT id FROM employees WHERE id = ?", (id,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE employees SET name=?, title=?, department=?, mission=?, required_capabilities=?, "
                "permissions=?, version=? WHERE id=?",
                (name, title, department, mission, capabilities_json, permissions_json, version, id),
            )
        else:
            conn.execute(
                "INSERT INTO employees (id, name, title, department, mission, required_capabilities, "
                "permissions, version, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'idle')",
                (id, name, title, department, mission, capabilities_json, permissions_json, version),
            )
        conn.commit()
    finally:
        conn.close()


def get_employees():
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM employees ORDER BY id").fetchall()
    finally:
        conn.close()


def get_employee(id):
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM employees WHERE id = ?", (id,)).fetchone()
    finally:
        conn.close()


def get_roster_summary(ids):
    """Return id/title/mission/required_capabilities/permissions for the
    given employee ids, with the JSON columns parsed back into lists -- the
    shape Orchestrator needs to reason about who to staff, and the shape the
    Tool Framework needs to know what a chosen specialist may access."""
    conn = get_connection()
    try:
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT id, title, mission, required_capabilities, permissions FROM employees WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "mission": r["mission"],
                "required_capabilities": json.loads(r["required_capabilities"]),
                "permissions": json.loads(r["permissions"]),
            }
            for r in rows
        ]
    finally:
        conn.close()


def set_employee_status(id, status):
    conn = get_connection()
    try:
        conn.execute("UPDATE employees SET status = ? WHERE id = ?", (status, id))
        conn.commit()
    finally:
        conn.close()


def create_task(request_text, project_id):
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO tasks (project_id, request_text, status) VALUES (?, ?, 'intake')",
            (project_id, request_text),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_task_status(task_id, status):
    conn = get_connection()
    try:
        conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
        conn.commit()
    finally:
        conn.close()


def get_tasks():
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM tasks ORDER BY id DESC").fetchall()
    finally:
        conn.close()


def get_task(task_id):
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    finally:
        conn.close()


def create_report(task_id, employees_involved, timeline, input_tokens, output_tokens, cost, result_text, qa_note):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO reports (task_id, employees_involved, timeline, input_tokens, output_tokens, cost, "
            "result_text, qa_note) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_id,
                json.dumps(employees_involved),
                json.dumps(timeline),
                input_tokens,
                output_tokens,
                cost,
                result_text,
                qa_note,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_report(task_id):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM reports WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        report = dict(row)
        report["employees_involved"] = json.loads(report["employees_involved"])
        report["timeline"] = json.loads(report["timeline"])
        return report
    finally:
        conn.close()


def get_total_cost():
    conn = get_connection()
    try:
        row = conn.execute("SELECT COALESCE(SUM(cost), 0) AS total FROM reports").fetchone()
        return row["total"]
    finally:
        conn.close()


def create_memory_entry(task_id, summary):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO memory (task_id, summary) VALUES (?, ?)",
            (task_id, summary),
        )
        conn.commit()
    finally:
        conn.close()


def get_recent_memory(project_id, limit=5):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT m.summary FROM memory m JOIN tasks t ON m.task_id = t.id "
            "WHERE t.project_id = ? ORDER BY m.id DESC LIMIT ?",
            (project_id, limit),
        ).fetchall()
        return [r["summary"] for r in rows]
    finally:
        conn.close()
