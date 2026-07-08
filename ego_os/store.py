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
    artifacts TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS mandate (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version INTEGER NOT NULL,
    mission TEXT NOT NULL,
    starting_capital REAL NOT NULL,
    risk_policy TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS employee_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    trigger_text TEXT NOT NULL,
    title TEXT NOT NULL,
    department TEXT NOT NULL,
    mission TEXT NOT NULL,
    responsibilities TEXT NOT NULL DEFAULT '[]',
    required_capabilities TEXT NOT NULL DEFAULT '[]',
    tools TEXT NOT NULL DEFAULT '[]',
    permissions TEXT NOT NULL DEFAULT '[]',
    reporting_rules TEXT NOT NULL DEFAULT '[]',
    temporary_or_permanent TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost REAL NOT NULL DEFAULT 0,
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
        # Migration for databases created before Document Generation (v0.2).
        _ensure_column(conn, "reports", "artifacts", "TEXT NOT NULL DEFAULT '[]'")
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


def create_project(name, vision=None):
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO projects (name, vision) VALUES (?, ?)",
            (name, vision),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_projects():
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM projects ORDER BY id").fetchall()
    finally:
        conn.close()


def get_project(project_id):
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
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
        return conn.execute(
            "SELECT t.*, p.name AS project_name FROM tasks t "
            "LEFT JOIN projects p ON t.project_id = p.id ORDER BY t.id DESC"
        ).fetchall()
    finally:
        conn.close()


def get_task(task_id):
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT t.*, p.name AS project_name FROM tasks t "
            "LEFT JOIN projects p ON t.project_id = p.id WHERE t.id = ?",
            (task_id,),
        ).fetchone()
    finally:
        conn.close()


def create_report(task_id, employees_involved, timeline, input_tokens, output_tokens, cost, result_text, qa_note, artifacts=None):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO reports (task_id, employees_involved, timeline, input_tokens, output_tokens, cost, "
            "result_text, qa_note, artifacts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_id,
                json.dumps(employees_involved),
                json.dumps(timeline),
                input_tokens,
                output_tokens,
                cost,
                result_text,
                qa_note,
                json.dumps(artifacts or []),
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
        report["artifacts"] = json.loads(report["artifacts"])
        return report
    finally:
        conn.close()


def get_total_cost():
    """Sum of all recorded cost, whether the task fully completed (reports)
    or stopped at a capability gap (employee_proposals) -- cost accounting
    is first-class for every LLM call, not only completed tasks."""
    conn = get_connection()
    try:
        reports_total = conn.execute("SELECT COALESCE(SUM(cost), 0) AS total FROM reports").fetchone()["total"]
        proposals_total = conn.execute("SELECT COALESCE(SUM(cost), 0) AS total FROM employee_proposals").fetchone()["total"]
        return reports_total + proposals_total
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


def get_memory_entries(project_id):
    """Full memory history for a project, for direct browsing on the
    Dashboard (Operations Visibility) rather than only being injected
    silently into a specialist's prompt."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT m.id, m.summary, m.created_at, m.task_id, t.request_text FROM memory m "
            "JOIN tasks t ON m.task_id = t.id WHERE t.project_id = ? ORDER BY m.id DESC",
            (project_id,),
        ).fetchall()
    finally:
        conn.close()


def create_mandate(mission, starting_capital, risk_policy):
    """Insert a new mandate version. Never overwrites a prior version --
    per architecture/006 Stage 1, the mission/capital/risk policy are a
    real, versioned, Owner-approved artifact."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM mandate").fetchone()
        version = row["v"] + 1
        conn.execute(
            "INSERT INTO mandate (version, mission, starting_capital, risk_policy) VALUES (?, ?, ?, ?)",
            (version, mission, starting_capital, risk_policy),
        )
        conn.commit()
        return version
    finally:
        conn.close()


def get_current_mandate():
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM mandate ORDER BY version DESC LIMIT 1").fetchone()
    finally:
        conn.close()


def get_mandate_history():
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM mandate ORDER BY version DESC").fetchall()
    finally:
        conn.close()


def create_employee_proposal(
    task_id, trigger_text, title, department, mission, responsibilities,
    required_capabilities, tools_, permissions, reporting_rules,
    temporary_or_permanent, reason, input_tokens, output_tokens, cost,
):
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO employee_proposals (task_id, trigger_text, title, department, mission, "
            "responsibilities, required_capabilities, tools, permissions, reporting_rules, "
            "temporary_or_permanent, reason, input_tokens, output_tokens, cost) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_id, trigger_text, title, department, mission,
                json.dumps(responsibilities), json.dumps(required_capabilities),
                json.dumps(tools_), json.dumps(permissions), json.dumps(reporting_rules),
                temporary_or_permanent, reason, input_tokens, output_tokens, cost,
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _parse_proposal(row):
    proposal = dict(row)
    for field in ("responsibilities", "required_capabilities", "tools", "permissions", "reporting_rules"):
        proposal[field] = json.loads(proposal[field])
    return proposal


def get_proposals():
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM employee_proposals ORDER BY id DESC").fetchall()
        return [_parse_proposal(r) for r in rows]
    finally:
        conn.close()


def get_pending_proposals():
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM employee_proposals WHERE status = 'pending' ORDER BY id DESC"
        ).fetchall()
        return [_parse_proposal(r) for r in rows]
    finally:
        conn.close()


def get_proposal(proposal_id):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM employee_proposals WHERE id = ?", (proposal_id,)).fetchone()
        return _parse_proposal(row) if row else None
    finally:
        conn.close()


def get_proposal_by_task(task_id):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM employee_proposals WHERE task_id = ?", (task_id,)).fetchone()
        return _parse_proposal(row) if row else None
    finally:
        conn.close()


def update_proposal_status(proposal_id, status):
    conn = get_connection()
    try:
        conn.execute("UPDATE employee_proposals SET status = ? WHERE id = ?", (status, proposal_id))
        conn.commit()
    finally:
        conn.close()


def get_employee_task_history(employee_id):
    """Per-employee task history (Operations Visibility) -- which tasks an
    employee was actually involved in, derived from each report's
    employees_involved list."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT r.task_id, r.employees_involved, t.request_text, t.status FROM reports r "
            "JOIN tasks t ON r.task_id = t.id ORDER BY r.task_id DESC"
        ).fetchall()
        history = []
        for r in rows:
            if employee_id in json.loads(r["employees_involved"]):
                history.append({"task_id": r["task_id"], "request_text": r["request_text"], "status": r["status"]})
        return history
    finally:
        conn.close()
