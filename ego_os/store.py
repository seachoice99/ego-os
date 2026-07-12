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

CREATE TABLE IF NOT EXISTS execution_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    step TEXT NOT NULL,
    employee_id TEXT,
    employee_version TEXT,
    capability TEXT,
    model TEXT,
    tool_name TEXT,
    tool_args_summary TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost REAL NOT NULL DEFAULT 0,
    status TEXT,
    detail TEXT,
    duration_ms INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS skill_audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id TEXT NOT NULL,
    skill_version TEXT,
    event_type TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS digital_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id),
    source_task_id INTEGER NOT NULL REFERENCES tasks(id),
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'candidate',
    origin TEXT NOT NULL DEFAULT 'automatic',
    target_audience TEXT,
    reusable_value TEXT,
    evidence TEXT NOT NULL DEFAULT '[]',
    value_thesis TEXT,
    monetization_thesis TEXT,
    validation_status TEXT,
    owner_decision TEXT,
    provenance TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS digital_asset_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL REFERENCES digital_assets(id),
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ADR-0014: persisted ProductTaskPlan -- architecture/001_CORE_ENTITIES.md
-- defines Task.plan; before this table, nothing was actually persisted.
CREATE TABLE IF NOT EXISTS product_task_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    objective TEXT,
    deliverables TEXT NOT NULL DEFAULT '[]',
    selected_employees TEXT NOT NULL DEFAULT '[]',
    required_capabilities TEXT NOT NULL DEFAULT '[]',
    allowed_tools TEXT NOT NULL DEFAULT '[]',
    estimated_cost REAL,
    task_budget REAL,
    risks TEXT NOT NULL DEFAULT '[]',
    assumptions TEXT NOT NULL DEFAULT '[]',
    qa_acceptance_criteria TEXT NOT NULL DEFAULT '[]',
    required_approvals TEXT NOT NULL DEFAULT '[]',
    subtasks TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ADR-0014: persisted Clarification contract. Runtime ask/pause/resume
-- wiring inside lifecycle.py is tracked separately (see this pass's final
-- report) -- this table exists so the contract is real even where the
-- full runtime is not yet.
CREATE TABLE IF NOT EXISTS clarifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    question TEXT NOT NULL,
    answer TEXT,
    status TEXT NOT NULL DEFAULT 'asked',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    answered_at TEXT
);

-- ADR-0016: append-only budget ledger. amount_cents is always an integer
-- (minor units) -- money is never stored as a float in this table.
CREATE TABLE IF NOT EXISTS budget_ledger_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER REFERENCES tasks(id),
    event_type TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    detail TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ADR-0015 (Decision 7): Approve creates this, not an Employee directly.
-- This is an AutomationTask-shaped unit of work (it edits repository
-- files) -- automation_task_ref is the explicit reference-field linkage
-- ADR-0015 requires, populated once a real tasks/queue/*.yaml is filed
-- for it (not automated by this pass -- see architecture/001).
CREATE TABLE IF NOT EXISTS employee_provisioning_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id INTEGER NOT NULL REFERENCES employee_proposals(id),
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    status TEXT NOT NULL DEFAULT 'pending',
    requires_extra_approval INTEGER NOT NULL DEFAULT 0,
    extra_approval_granted INTEGER NOT NULL DEFAULT 0,
    automation_task_ref TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);
"""


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_column(conn, table, column, coldef):
    """Returns True only when the column was actually just added, so a
    caller can run one-time backfill logic exactly once, not on every
    startup."""
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coldef}")
        return True
    return False


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

        # Migration for databases created before the background worker
        # (v0.4.1): run_state is the coarse worker-scheduling state
        # (queued/running/completed/failed/cancelled), deliberately kept
        # separate from the existing fine-grained `status` column
        # (intake/planning/.../delivered/awaiting_approval/...) rather than
        # repurposing it -- that vocabulary is already established and
        # rendered throughout the templates.
        run_state_added = _ensure_column(conn, "tasks", "run_state", "TEXT NOT NULL DEFAULT 'queued'")
        _ensure_column(conn, "tasks", "error_message", "TEXT")
        if run_state_added:
            # Every pre-v0.4.1 task ran synchronously inside its own HTTP
            # request and only ever left the DB once that request
            # returned, so every existing row is already at a real
            # terminal `status` -- never actually 'queued' or 'running'
            # from the new worker's point of view. Without this, the
            # ALTER TABLE ... DEFAULT 'queued' backfill would make the
            # worker try to (re-)run the company's entire task history on
            # first boot after upgrading.
            conn.execute("UPDATE tasks SET run_state = 'completed' WHERE run_state = 'queued'")

        # Migration for databases created before Employee version
        # traceability (v0.4.1): which version of each employee actually
        # performed the work, captured at execution time -- distinct from
        # employees.version, which is mutated in place by every registry
        # sync and so cannot answer "which version ran this" once an
        # employee is later updated (ADR-0002: history must stay stable
        # across upgrades).
        _ensure_column(conn, "reports", "employee_versions", "TEXT NOT NULL DEFAULT '{}'")

        # Migration for databases created before Employee Skill references
        # (SR-02): an Employee's optional list of {"id", "version"} Skill
        # references, absent (=> '[]') for every Employee defined before
        # ADR-0004. Additive and backward compatible -- an Employee with
        # no skills behaves exactly as before.
        _ensure_column(conn, "employees", "skills", "TEXT NOT NULL DEFAULT '[]'")
        # Which exact Skill (id/version/digest) a step actually used, and
        # which Skills a delivered report's work drew on -- both additive,
        # both default to "nothing" for history that predates Skills.
        _ensure_column(conn, "execution_events", "skill_id", "TEXT")
        _ensure_column(conn, "execution_events", "skill_version", "TEXT")
        _ensure_column(conn, "execution_events", "skill_digest", "TEXT")
        _ensure_column(conn, "reports", "skills_used", "TEXT NOT NULL DEFAULT '[]'")

        # Migration for the 2026-07-13 architecture-correction pass (ADR-0014):
        # a structured, additive terminal-outcome marker -- never replaces
        # `status`, which keeps its existing string vocabulary unchanged.
        _ensure_column(conn, "tasks", "terminal_reason", "TEXT")
        _ensure_column(conn, "reports", "schema_version", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "reports", "terminal_status", "TEXT")
        _ensure_column(conn, "reports", "terminal_reason", "TEXT")

        # ADR-0016: the current global operating budget (USD 15.00) is a
        # real, append-only ledger entry -- never a number hardcoded into
        # enforcement code -- seeded exactly once (gated on "no ledger
        # events exist yet at all", not on a version-added column, since
        # this table is new rather than migrated).
        existing_ledger_events = conn.execute("SELECT COUNT(*) AS n FROM budget_ledger_events").fetchone()["n"]
        if existing_ledger_events == 0:
            conn.execute(
                "INSERT INTO budget_ledger_events (task_id, event_type, amount_cents, currency, detail) "
                "VALUES (NULL, 'budget_approved', 1500, 'USD', ?)",
                ("Initial global operating budget per ADR-0016, accepted by Owner 2026-07-13.",),
            )

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


def upsert_employee(id, name, title, department, mission, required_capabilities, permissions, version, skills=None):
    conn = get_connection()
    try:
        capabilities_json = json.dumps(required_capabilities)
        permissions_json = json.dumps(permissions)
        skills_json = json.dumps(skills or [])
        existing = conn.execute("SELECT id FROM employees WHERE id = ?", (id,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE employees SET name=?, title=?, department=?, mission=?, required_capabilities=?, "
                "permissions=?, version=?, skills=? WHERE id=?",
                (name, title, department, mission, capabilities_json, permissions_json, version, skills_json, id),
            )
        else:
            conn.execute(
                "INSERT INTO employees (id, name, title, department, mission, required_capabilities, "
                "permissions, version, skills, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'idle')",
                (id, name, title, department, mission, capabilities_json, permissions_json, version, skills_json),
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
    """Return id/title/mission/required_capabilities/permissions/version/
    skills for the given employee ids, with the JSON columns parsed back
    into lists -- the shape Orchestrator needs to reason about who to
    staff, the shape the Tool Framework needs to know what a chosen
    specialist may access, the version (v0.4.1) so the lifecycle can
    record which Employee Definition version actually performed the
    work, and (SR-02) the Skill references so the lifecycle can resolve
    and fail closed on them before any model call."""
    conn = get_connection()
    try:
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT id, title, mission, required_capabilities, permissions, version, skills FROM employees WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "mission": r["mission"],
                "required_capabilities": json.loads(r["required_capabilities"]),
                "permissions": json.loads(r["permissions"]),
                "version": r["version"],
                "skills": json.loads(r["skills"]) if r["skills"] is not None else [],
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


class TaskTransitionError(Exception):
    """Raised by update_task_status for a (current, new) status pair not in
    _TASK_TRANSITIONS -- the tasks.status analogue of digital_assets'
    existing transition_asset/_ASSET_TRANSITIONS enforcement (ADR-0014).
    An invalid transition must be structurally impossible, not just
    discouraged by caller convention."""


# architecture/002_TASK_LIFECYCLE.md's full transition table. A pair not
# listed here (and not a same-status no-op) is rejected outright.
_TASK_TRANSITIONS = {
    ("intake", "waiting_for_clarification"),
    ("intake", "planning"),
    ("waiting_for_clarification", "planning"),
    ("planning", "staffing"),
    ("staffing", "execution"),
    ("staffing", "awaiting_approval"),
    ("awaiting_approval", "gap_approved"),
    ("awaiting_approval", "gap_rejected"),
    ("gap_approved", "planning"),  # replanned once the EmployeeProvisioningTask completes
    ("execution", "qa"),
    ("qa", "delivered"),
    ("qa", "revision"),
    ("qa", "needs_owner_review"),
    ("revision", "qa"),
    ("needs_owner_review", "delivered"),
    ("needs_owner_review", "revision"),
    ("needs_owner_review", "cancelled"),
    ("revision", "planning"),  # Owner-authorized restart after needs_owner_review -> revision (see main.py's retry route)
    # A terminal failure can occur from any non-terminal, in-flight status.
    ("intake", "failed"),
    ("waiting_for_clarification", "failed"),
    ("planning", "failed"),
    ("staffing", "failed"),
    ("execution", "failed"),
    ("qa", "failed"),
    ("revision", "failed"),
}
TASK_TERMINAL_STATUSES = {"delivered", "failed", "cancelled", "needs_owner_review", "gap_rejected"}


def update_task_status(task_id, status, terminal_reason=None):
    """terminal_reason, when given, is a small dict ({"category": ...,
    "detail": ...}) persisted as JSON alongside the status -- ADR-0014's
    structured-reason approach, so a new terminal outcome never needs a
    brand-new tasks.status string. A (current, new) pair not in
    _TASK_TRANSITIONS (and not a same-status no-op) raises
    TaskTransitionError before anything is written."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise TaskTransitionError(f"task {task_id} does not exist")
        current = row["status"]
        if current != status and (current, status) not in _TASK_TRANSITIONS:
            raise TaskTransitionError(f"invalid ProductTask transition: '{current}' -> '{status}'")
        conn.execute(
            "UPDATE tasks SET status = ?, terminal_reason = ? WHERE id = ?",
            (status, json.dumps(terminal_reason) if terminal_reason else None, task_id),
        )
        conn.commit()
    finally:
        conn.close()


def set_task_run_state(task_id, run_state, error_message=None):
    """run_state is the coarse worker-scheduling state (queued/running/
    completed/failed/cancelled) -- separate from the fine-grained
    lifecycle-phase `status` column the worker also continues to update
    via update_task_status."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tasks SET run_state = ?, error_message = ? WHERE id = ?",
            (run_state, error_message, task_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_tasks_by_run_state(run_state):
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM tasks WHERE run_state = ?", (run_state,)).fetchall()
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


def create_report(
    task_id, employees_involved, timeline, input_tokens, output_tokens, cost, result_text, qa_note,
    artifacts=None, employee_versions=None, skills_used=None, terminal_status=None, terminal_reason=None,
    schema_version=1,
):
    """ADR-0014: Report is the immutable terminal projection for a
    ProductTask -- schema_version/terminal_status/terminal_reason are
    additive fields (default NULL/1 for pre-this-pass callers). One report
    row per task_id is enforced at the DB level (reports.task_id PRIMARY
    KEY) deliberately -- see tests/test_worker.py's
    test_create_report_twice_for_same_task_is_rejected_at_db_level -- a
    ProductTask that later moves from needs_owner_review to delivered
    updates this same row's terminal_status via update_report_terminal_outcome,
    it never calls create_report a second time."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO reports (task_id, employees_involved, timeline, input_tokens, output_tokens, cost, "
            "result_text, qa_note, artifacts, employee_versions, skills_used, schema_version, terminal_status, "
            "terminal_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                json.dumps(employee_versions or {}),
                json.dumps(skills_used or []),
                schema_version,
                terminal_status,
                json.dumps(terminal_reason) if terminal_reason else None,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def update_report_terminal_outcome(task_id, terminal_status, terminal_reason=None):
    """Updates ONLY the terminal disposition of an existing report row (e.g.
    needs_owner_review -> delivered once the Owner accepts a draft) --
    never re-inserts, never touches the immutable operational content
    (result_text/timeline/cost/qa_note). Raises if no report exists yet
    for this task_id (the Owner cannot accept a draft that was never
    reported)."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE reports SET terminal_status = ?, terminal_reason = ? WHERE task_id = ?",
            (terminal_status, json.dumps(terminal_reason) if terminal_reason else None, task_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"no report exists yet for task {task_id}")
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
        report["employee_versions"] = json.loads(report["employee_versions"])
        report["skills_used"] = json.loads(report["skills_used"])
        report["terminal_reason"] = json.loads(report["terminal_reason"]) if report.get("terminal_reason") else None
        return report
    finally:
        conn.close()


def log_execution_event(
    task_id, step, employee_id=None, employee_version=None, capability=None, model=None,
    tool_name=None, tool_args_summary=None, input_tokens=0, output_tokens=0, cost=0.0,
    status=None, detail=None, duration_ms=None, skill_id=None, skill_version=None, skill_digest=None,
):
    """Written incrementally as the lifecycle proceeds (not just once at
    the end, unlike reports.timeline) -- so a crash mid-task still leaves
    a real, queryable operational record of what happened before it died.
    Only operational facts (who, what step, what model/tool, cost,
    outcome) -- never hidden chain-of-thought, per architecture/003.
    skill_id/skill_version/skill_digest (SR-02) record which exact,
    locked Skill version a step actually used -- a single skill per event
    is enough for this MVP (the first real Skill, structured_reporting,
    is attached one-per-employee); a multi-skill-per-step model would
    need a join table if that ever becomes a real requirement."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO execution_events (task_id, step, employee_id, employee_version, capability, "
            "model, tool_name, tool_args_summary, input_tokens, output_tokens, cost, status, detail, "
            "duration_ms, skill_id, skill_version, skill_digest) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_id, step, employee_id, employee_version, capability, model, tool_name,
                tool_args_summary, input_tokens, output_tokens, cost, status, detail, duration_ms,
                skill_id, skill_version, skill_digest,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_execution_events(task_id):
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM execution_events WHERE task_id = ? ORDER BY id", (task_id,)
        ).fetchall()
    finally:
        conn.close()


_SKILL_AUDIT_EVENT_TYPES = {
    "discovered", "created", "validated", "attached", "detached",
    "deprecated", "revoked", "resolution_failure",
}


def log_skill_audit_event(skill_id, event_type, skill_version=None, detail=None):
    """Append-only Skill audit trail (SR-04), kept as its own table --
    never mixed into the immutable Skill package on disk. Only
    operational facts: which skill, what happened, when -- never a raw
    prompt, a credential, or hidden chain-of-thought."""
    if event_type not in _SKILL_AUDIT_EVENT_TYPES:
        raise ValueError(f"invalid skill audit event_type: {event_type!r}")
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO skill_audit_events (skill_id, skill_version, event_type, detail) VALUES (?, ?, ?, ?)",
            (skill_id, skill_version, event_type, detail),
        )
        conn.commit()
    finally:
        conn.close()


def get_skill_audit_events(skill_id=None):
    conn = get_connection()
    try:
        if skill_id is None:
            return conn.execute("SELECT * FROM skill_audit_events ORDER BY id DESC").fetchall()
        return conn.execute(
            "SELECT * FROM skill_audit_events WHERE skill_id = ? ORDER BY id DESC", (skill_id,)
        ).fetchall()
    finally:
        conn.close()


def get_last_skill_check(skill_id):
    """The last genuine operational validation of this Skill -- a real
    Registry validation or resolution, never a page view and not an
    attach/detach/resolution_failure bookkeeping event, so 'last check'
    means what it says."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM skill_audit_events WHERE skill_id = ? AND event_type = 'validated' "
            "ORDER BY id DESC LIMIT 1", (skill_id,)
        ).fetchone()
    finally:
        conn.close()


def get_employees_using_skill(skill_id, version=None):
    """Which Employees reference this Skill (optionally pinned to one
    exact version) -- scans the small `employees` table's own `skills`
    JSON column rather than needing a join table."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT id, title, skills FROM employees ORDER BY id").fetchall()
        matches = []
        for r in rows:
            for ref in json.loads(r["skills"]):
                if ref.get("id") == skill_id and (version is None or ref.get("version") == version):
                    matches.append({"id": r["id"], "title": r["title"], "version": ref.get("version")})
        return matches
    finally:
        conn.close()


_DANGEROUS_PERMISSION_KEYWORDS = ("external", "publish", "payment", "send_", "delete", "deploy", "outreach")


def create_employee_provisioning_task(proposal_id, task_id, permissions=None):
    """ADR-0015 (Decision 7): Approve creates this, never an Employee
    directly. requires_extra_approval is a simple, disclosed keyword
    check against the proposed permissions -- not a judgment call hidden
    from the Owner; the extra confirmation itself is a separate, explicit
    step (grant_provisioning_extra_approval)."""
    requires_extra_approval = any(
        keyword in str(p).lower() for p in (permissions or []) for keyword in _DANGEROUS_PERMISSION_KEYWORDS
    )
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO employee_provisioning_tasks (proposal_id, task_id, status, requires_extra_approval) "
            "VALUES (?, ?, 'pending', ?)",
            (proposal_id, task_id, int(requires_extra_approval)),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_employee_provisioning_task(provisioning_id):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM employee_provisioning_tasks WHERE id = ?", (provisioning_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def grant_provisioning_extra_approval(provisioning_id):
    """A dangerous/external-permission provisioning task cannot proceed
    until this is called explicitly -- separate from the original
    proposal approval, per Decision 7."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE employee_provisioning_tasks SET extra_approval_granted = 1 WHERE id = ?",
            (provisioning_id,),
        )
        conn.commit()
    finally:
        conn.close()


# --- ADR-0016: append-only budget ledger -----------------------------------
#
# Money here is always integer cents (USD minor units) -- never float --
# per ADR-0016's explicit "never binary FLOAT/REAL as the authoritative
# representation" rule. Existing reports.cost/employee_proposals.cost stay
# REAL (unchanged, out of this pass's scope); this ledger is a separate,
# new, exact accounting of RESERVATIONS and ENFORCEMENT, distinct from
# those historical cost-reporting columns.
#
# Balance model (deliberately simple, auditable from the append-only log
# alone, never a mutable counter):
#   available = sum(budget_approved + adjustment_approved + reservation_released)
#             - sum(task_reserved)
# spend_recorded is informational/audit only -- the reservation already
# accounted for the conservative maximum; reservation_released trues the
# balance up to what was actually spent.

class BudgetError(Exception):
    """Raised when a reservation would exceed the task's own sub-limit or
    the remaining global balance -- callers must treat this as a real,
    expected 'not enough budget' condition (ADR-0016: automatic overspend
    is never permitted), not a bug."""


_BUDGET_EVENT_TYPES = {
    "budget_approved", "task_reserved", "spend_recorded",
    "reservation_released", "adjustment_approved", "budget_exhausted",
}


def record_budget_event(event_type, amount_cents, task_id=None, currency="USD", detail=None):
    if event_type not in _BUDGET_EVENT_TYPES:
        raise ValueError(f"unknown budget ledger event_type: {event_type}")
    if not isinstance(amount_cents, int):
        raise TypeError("amount_cents must be an exact integer (minor units), never a float")
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO budget_ledger_events (task_id, event_type, amount_cents, currency, detail) VALUES (?, ?, ?, ?, ?)",
            (task_id, event_type, amount_cents, currency, detail),
        )
        conn.commit()
    finally:
        conn.close()


def get_global_available_cents():
    conn = get_connection()
    try:
        total = 0
        for row in conn.execute("SELECT event_type, amount_cents FROM budget_ledger_events"):
            if row["event_type"] in ("budget_approved", "adjustment_approved", "reservation_released"):
                total += row["amount_cents"]
            elif row["event_type"] == "task_reserved":
                total -= row["amount_cents"]
        return total
    finally:
        conn.close()


def get_task_net_reserved_cents(task_id):
    """Outstanding (not-yet-released) reservation for one task."""
    conn = get_connection()
    try:
        total = 0
        for row in conn.execute(
            "SELECT event_type, amount_cents FROM budget_ledger_events WHERE task_id = ?", (task_id,),
        ):
            if row["event_type"] == "task_reserved":
                total += row["amount_cents"]
            elif row["event_type"] == "reservation_released":
                total -= row["amount_cents"]
        return total
    finally:
        conn.close()


def reserve_budget(task_id, amount_cents, task_budget_cents=None, detail=None):
    """Step 1-4 of ADR-0016's enforcement sequence: check the task's own
    sub-limit (if one is set) and the global balance, then record a
    task_reserved event -- all inside one connection/transaction so a
    concurrent reservation for the same or another task can never
    observe a half-updated balance (SQLite's own single-writer-at-a-time
    locking on this file-based DB serializes these transactions).
    Raises BudgetError (never allows an overspend) if either limit would
    be exceeded, and records a budget_exhausted event in that case."""
    if not isinstance(amount_cents, int):
        raise TypeError("amount_cents must be an exact integer (minor units), never a float")
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if task_budget_cents is not None:
            reserved_so_far = 0
            for row in conn.execute(
                "SELECT event_type, amount_cents FROM budget_ledger_events WHERE task_id = ?", (task_id,),
            ):
                if row["event_type"] == "task_reserved":
                    reserved_so_far += row["amount_cents"]
                elif row["event_type"] == "reservation_released":
                    reserved_so_far -= row["amount_cents"]
            if reserved_so_far + amount_cents > task_budget_cents:
                conn.execute(
                    "INSERT INTO budget_ledger_events (task_id, event_type, amount_cents, detail) VALUES (?, 'budget_exhausted', 0, ?)",
                    (task_id, f"task sub-limit exceeded: {reserved_so_far + amount_cents} > {task_budget_cents} cents"),
                )
                conn.commit()
                raise BudgetError(f"task {task_id}: reservation of {amount_cents} cents would exceed its own task budget")

        available = 0
        for row in conn.execute("SELECT event_type, amount_cents FROM budget_ledger_events"):
            if row["event_type"] in ("budget_approved", "adjustment_approved", "reservation_released"):
                available += row["amount_cents"]
            elif row["event_type"] == "task_reserved":
                available -= row["amount_cents"]
        if amount_cents > available:
            conn.execute(
                "INSERT INTO budget_ledger_events (task_id, event_type, amount_cents, detail) VALUES (?, 'budget_exhausted', 0, ?)",
                (task_id, f"global balance exceeded: requested {amount_cents}, available {available} cents"),
            )
            conn.commit()
            raise BudgetError(f"task {task_id}: reservation of {amount_cents} cents would exceed the remaining global balance ({available} cents)")

        conn.execute(
            "INSERT INTO budget_ledger_events (task_id, event_type, amount_cents, detail) VALUES (?, 'task_reserved', ?, ?)",
            (task_id, amount_cents, detail),
        )
        conn.commit()
    finally:
        conn.close()


def record_spend(task_id, amount_cents, detail=None):
    record_budget_event("spend_recorded", amount_cents, task_id=task_id, detail=detail)


def release_reservation(task_id, amount_cents, detail=None):
    if amount_cents < 0:
        raise ValueError("release amount cannot be negative")
    if amount_cents == 0:
        return  # nothing to release; a real zero-amount ledger row would be noise, not evidence
    record_budget_event("reservation_released", amount_cents, task_id=task_id, detail=detail)


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


# --- Digital Assets (v0.5, ADR-0007 / architecture/013) ---------------------
#
# A Digital Asset Candidate and an Accepted Digital Asset are the same
# underlying `digital_assets` row at different points in one lifecycle
# (ADR-0007 decision 1) -- `status` is a derived, queryable convenience
# field, never the only record of what happened. The real source of truth
# is the append-only `digital_asset_events` history (ADR-0007 decision 6),
# so `transition_asset` below is the single enforcement point for every
# status change: it validates against the allowed-transition map before
# writing anything, then writes the new status and the event in the same
# connection/transaction. No function in this module ever deletes a
# `digital_assets` or `digital_asset_events` row (ADR-0007 decision 7).


class DigitalAssetError(Exception):
    """Base class for every Digital Asset failure: an invalid status/event
    value, a reference to a source Task that does not exist, or (see
    DigitalAssetTransitionError) a disallowed lifecycle transition. Always
    a clean, human-readable message."""


class DigitalAssetTransitionError(DigitalAssetError):
    """A requested `digital_assets.status` transition is not allowed by
    architecture/013 Section 6's lifecycle map (e.g. candidate ->
    internally_validated directly, or accepted -> internally_validated
    without a passed validation result and a monetization thesis recorded
    in the same call)."""


_ASSET_STATUSES = {"candidate", "accepted", "rejected", "internally_validated", "archived"}

_ASSET_EVENT_TYPES = {
    "candidate_created", "owner_accepted", "owner_rejected", "validation_started",
    "validation_passed", "validation_failed", "thesis_updated", "archived",
}

_ASSET_VALIDATION_STATUSES = {"started", "passed", "failed", "needs_revision"}

# Which validation_status value(s) are semantically consistent with each
# event_type -- e.g. a validation_started event can never be paired with
# validation_status='passed' in the same call, even though both are
# individually valid values.
_EVENT_VALIDATION_STATUS = {
    "validation_started": {"started"},
    "validation_failed": {"failed", "needs_revision"},
    "validation_passed": {"passed"},
    "thesis_updated": set(),
}

# Actors allowed to archive an Asset (architecture/013 Section 6: "any
# status -> archived", implemented for model completeness) -- deliberately
# the same system/owner restriction every other non-Owner-only transition
# uses, so archiving is never reachable by an unrestricted caller.
_ASSET_ARCHIVE_ACTORS = {"system", "owner"}

# (current_status, new_status) -> {event_type: {allowed actors}}. Every
# transition not present here is disallowed. The ("accepted", "accepted")
# self-loop covers validation_started/validation_failed/thesis_updated,
# which record progress without moving the Asset out of `accepted`
# (architecture/013 Section 6: "validation_started/validation_failed/
# needs_revision update ONLY validation_status").
_ASSET_TRANSITIONS = {
    ("candidate", "accepted"): {"owner_accepted": {"owner"}},
    ("candidate", "rejected"): {"owner_rejected": {"owner"}},
    ("rejected", "accepted"): {"owner_accepted": {"owner"}},
    ("accepted", "internally_validated"): {"validation_passed": {"system", "owner"}},
    ("accepted", "accepted"): {
        "validation_started": {"system", "owner"},
        "validation_failed": {"system", "owner"},
        "thesis_updated": {"system", "owner"},
    },
}


def _parse_asset(row):
    if row is None:
        return None
    asset = dict(row)
    asset["evidence"] = json.loads(asset["evidence"])
    asset["provenance"] = json.loads(asset["provenance"])
    if asset["monetization_thesis"] is not None:
        asset["monetization_thesis"] = json.loads(asset["monetization_thesis"])
    return asset


def create_asset_candidate(
    project_id, source_task_id, title, summary, asset_type,
    target_audience, reusable_value, evidence, value_thesis, provenance,
):
    """Nominate a Candidate (ADR-0007 decision 2: this is nomination, never
    acceptance -- the automatic system may never move a row past
    `candidate`). Raises DigitalAssetError, rather than silently inserting,
    if source_task_id does not reference a real Task."""
    conn = get_connection()
    try:
        task_row = conn.execute("SELECT id FROM tasks WHERE id = ?", (source_task_id,)).fetchone()
        if task_row is None:
            raise DigitalAssetError(f"source_task_id {source_task_id!r} does not reference an existing task")
        if project_id is not None:
            project_row = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
            if project_row is None:
                raise DigitalAssetError(f"project_id {project_id!r} does not reference an existing project")
        cur = conn.execute(
            "INSERT INTO digital_assets (project_id, source_task_id, title, summary, asset_type, "
            "status, origin, target_audience, reusable_value, evidence, value_thesis, provenance) "
            "VALUES (?, ?, ?, ?, ?, 'candidate', 'automatic', ?, ?, ?, ?, ?)",
            (
                project_id, source_task_id, title, summary, asset_type,
                target_audience, reusable_value, json.dumps(evidence or []), value_thesis,
                json.dumps(provenance),
            ),
        )
        asset_id = cur.lastrowid
        _insert_asset_event(
            conn, asset_id, "candidate_created", "system",
            detail=f"Candidate nominated from task {source_task_id}",
        )
        conn.commit()
        return asset_id
    finally:
        conn.close()


def get_asset(asset_id):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM digital_assets WHERE id = ?", (asset_id,)).fetchone()
        return _parse_asset(row)
    finally:
        conn.close()


def get_assets(status=None):
    conn = get_connection()
    try:
        if status is None:
            rows = conn.execute("SELECT * FROM digital_assets ORDER BY id").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM digital_assets WHERE status = ? ORDER BY id", (status,)
            ).fetchall()
        return [_parse_asset(r) for r in rows]
    finally:
        conn.close()


def get_asset_by_source_task(source_task_id):
    """Whether ANY Digital Asset (in any status) already exists for this
    Task -- the duplicate-prevention guard DA-03's automatic nomination
    step will call before ever creating a second Candidate for the same
    Task (architecture/013 Section 4: at most one automatic Candidate per
    Task). Returns None, not raises, when there is no existing Asset."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM digital_assets WHERE source_task_id = ? ORDER BY id LIMIT 1",
            (source_task_id,),
        ).fetchone()
        return _parse_asset(row)
    finally:
        conn.close()


def get_asset_events(asset_id):
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM digital_asset_events WHERE asset_id = ? ORDER BY id", (asset_id,)
        ).fetchall()
    finally:
        conn.close()


def _insert_asset_event(conn, asset_id, event_type, actor, detail=None):
    if event_type not in _ASSET_EVENT_TYPES:
        raise DigitalAssetError(f"invalid digital asset event_type: {event_type!r}")
    conn.execute(
        "INSERT INTO digital_asset_events (asset_id, event_type, actor, detail) VALUES (?, ?, ?, ?)",
        (asset_id, event_type, actor, detail),
    )


def log_asset_event(asset_id, event_type, actor, detail=None):
    """Append-only insert of one Digital Asset event, own connection/
    transaction -- for callers that only need to record a fact (e.g. a
    thesis_updated note) without also driving a status transition. Every
    status-changing event should go through transition_asset instead, so
    the status column and the event history can never disagree."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT id FROM digital_assets WHERE id = ?", (asset_id,)).fetchone()
        if row is None:
            raise DigitalAssetError(f"asset_id {asset_id!r} does not exist")
        _insert_asset_event(conn, asset_id, event_type, actor, detail)
        conn.commit()
    finally:
        conn.close()


def transition_asset(
    asset_id, new_status, event_type, actor, detail=None,
    validation_status=None, monetization_thesis=None,
):
    """The single enforcement point for every `digital_assets.status`
    change (architecture/013 Section 6). Validates the requested
    transition against `_ASSET_TRANSITIONS` before writing anything, then
    updates `status` (and any of `validation_status`/`monetization_thesis`/
    `owner_decision` supplied in this same call) and appends exactly one
    new event, in the same transaction. Never edits or removes an existing
    event row."""
    if new_status not in _ASSET_STATUSES:
        raise DigitalAssetError(f"invalid digital asset status: {new_status!r}")
    if event_type not in _ASSET_EVENT_TYPES:
        raise DigitalAssetError(f"invalid digital asset event_type: {event_type!r}")
    if validation_status is not None and validation_status not in _ASSET_VALIDATION_STATUSES:
        raise DigitalAssetError(f"invalid validation_status: {validation_status!r}")
    if (
        validation_status is not None
        and event_type in _EVENT_VALIDATION_STATUS
        and validation_status not in _EVENT_VALIDATION_STATUS[event_type]
    ):
        raise DigitalAssetTransitionError(
            f"validation_status {validation_status!r} is not consistent with event_type {event_type!r}"
        )

    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM digital_assets WHERE id = ?", (asset_id,)).fetchone()
        if row is None:
            raise DigitalAssetError(f"asset_id {asset_id!r} does not exist")
        current_status = row["status"]

        if new_status == "archived":
            if event_type != "archived":
                raise DigitalAssetTransitionError(
                    f"transition to 'archived' requires event_type='archived', got {event_type!r}"
                )
            if actor not in _ASSET_ARCHIVE_ACTORS:
                raise DigitalAssetTransitionError(
                    f"actor {actor!r} may not archive an asset"
                )
        else:
            allowed_events = _ASSET_TRANSITIONS.get((current_status, new_status))
            if allowed_events is None:
                raise DigitalAssetTransitionError(
                    f"transition {current_status!r} -> {new_status!r} is not allowed"
                )
            allowed_actors = allowed_events.get(event_type)
            if allowed_actors is None:
                raise DigitalAssetTransitionError(
                    f"event_type {event_type!r} cannot drive transition {current_status!r} -> {new_status!r}"
                )
            if actor not in allowed_actors:
                raise DigitalAssetTransitionError(
                    f"actor {actor!r} may not perform {event_type!r} for {current_status!r} -> {new_status!r}"
                )

        if new_status == "internally_validated":
            if validation_status != "passed":
                raise DigitalAssetTransitionError(
                    "reaching internally_validated requires validation_status='passed' in this same call"
                )
            if not monetization_thesis:
                raise DigitalAssetTransitionError(
                    "reaching internally_validated requires a non-empty monetization_thesis in this same call"
                )

        updates = ["status = ?", "updated_at = datetime('now')"]
        params = [new_status]
        if validation_status is not None:
            updates.append("validation_status = ?")
            params.append(validation_status)
        if monetization_thesis is not None:
            updates.append("monetization_thesis = ?")
            params.append(json.dumps(monetization_thesis))
        if event_type == "owner_accepted":
            updates.append("owner_decision = ?")
            params.append("accepted")
        elif event_type == "owner_rejected":
            updates.append("owner_decision = ?")
            params.append("rejected")
        params.append(asset_id)

        conn.execute(f"UPDATE digital_assets SET {', '.join(updates)} WHERE id = ?", params)
        _insert_asset_event(conn, asset_id, event_type, actor, detail)
        conn.commit()
    finally:
        conn.close()
