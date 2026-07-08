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
    version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'idle'
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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


def init_db():
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def upsert_employee(id, name, title, department, mission, version):
    conn = get_connection()
    try:
        existing = conn.execute("SELECT id FROM employees WHERE id = ?", (id,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE employees SET name=?, title=?, department=?, mission=?, version=? WHERE id=?",
                (name, title, department, mission, version, id),
            )
        else:
            conn.execute(
                "INSERT INTO employees (id, name, title, department, mission, version, status) "
                "VALUES (?, ?, ?, ?, ?, ?, 'idle')",
                (id, name, title, department, mission, version),
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


def set_employee_status(id, status):
    conn = get_connection()
    try:
        conn.execute("UPDATE employees SET status = ? WHERE id = ?", (status, id))
        conn.commit()
    finally:
        conn.close()


def create_task(request_text):
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO tasks (request_text, status) VALUES (?, 'intake')",
            (request_text,),
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
