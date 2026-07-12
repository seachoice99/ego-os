"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("path");

const {
  isValidCommand,
  commandAllowedInState,
  nextRunnerState,
  buildEvent,
  isSafeTaskId,
  resolveTaskFile,
  taskActionAllowed,
  validateReorder,
  summarizeTask,
  maskSecrets,
} = require("./runner_control.js");

// --- command validity -------------------------------------------------

test("isValidCommand accepts only the four known commands", () => {
  assert.equal(isValidCommand("pause"), true);
  assert.equal(isValidCommand("resume"), true);
  assert.equal(isValidCommand("stop_after_stage"), true);
  assert.equal(isValidCommand("emergency_stop"), true);
  assert.equal(isValidCommand("delete_everything"), false);
  assert.equal(isValidCommand(""), false);
  assert.equal(isValidCommand(undefined), false);
});

test("commandAllowedInState: resume only makes sense while paused/pause_requested", () => {
  assert.equal(commandAllowedInState("resume", "paused"), true);
  assert.equal(commandAllowedInState("resume", "pause_requested"), true);
  assert.equal(commandAllowedInState("resume", "running"), false);
  assert.equal(commandAllowedInState("resume", "stopped"), false);
});

test("commandAllowedInState: pause makes sense while running/idle/starting, not while already paused", () => {
  assert.equal(commandAllowedInState("pause", "running"), true);
  assert.equal(commandAllowedInState("pause", "idle"), true);
  assert.equal(commandAllowedInState("pause", "paused"), false);
});

test("commandAllowedInState: emergency_stop is allowed in almost any non-stopped state", () => {
  assert.equal(commandAllowedInState("emergency_stop", "running"), true);
  assert.equal(commandAllowedInState("emergency_stop", "paused"), true);
  assert.equal(commandAllowedInState("emergency_stop", "waiting_for_limit"), true);
  assert.equal(commandAllowedInState("emergency_stop", "stopped"), false);
});

// --- runner-level state transitions ------------------------------------

test("nextRunnerState: pause never jumps straight to 'paused' from 'running' -- it must wait for a safe point", () => {
  const result = nextRunnerState("running", "pause_command");
  assert.equal(result.ok, true);
  assert.equal(result.state, "pause_requested");
  assert.notEqual(result.state, "paused", "pause must not immediately claim to be paused while a stage may still be mid-flight");
});

test("nextRunnerState: pause_requested only becomes paused once a safe point is actually reached", () => {
  const result = nextRunnerState("pause_requested", "safe_point_reached");
  assert.equal(result.ok, true);
  assert.equal(result.state, "paused");
});

test("nextRunnerState: resume always starts a fresh 'starting' cycle, never resumes in place", () => {
  const result = nextRunnerState("paused", "resume_command");
  assert.equal(result.ok, true);
  assert.equal(result.state, "starting");
});

test("nextRunnerState: emergency_stop_command reaches 'stopped' even from mid-stage states", () => {
  for (const state of ["running", "pause_requested", "paused", "stop_requested", "waiting_for_limit"]) {
    const result = nextRunnerState(state, "emergency_stop_command");
    assert.equal(result.ok, true, `expected a transition for emergency_stop_command from ${state}`);
    assert.equal(result.state, "stopped");
  }
});

test("nextRunnerState: rate limit and auth failure route to their own distinct waiting states, never 'failed'", () => {
  assert.equal(nextRunnerState("running", "rate_limited").state, "waiting_for_limit");
  assert.equal(nextRunnerState("running", "auth_required").state, "authentication_required");
  assert.equal(nextRunnerState("running", "owner_gate_blocked").state, "waiting_for_owner");
});

test("nextRunnerState: an undefined event for the current state is rejected, not silently ignored", () => {
  const result = nextRunnerState("stopped", "resume_command");
  assert.equal(result.ok, false);
  assert.match(result.reason, /no transition/);
});

// --- event log entries --------------------------------------------------

test("buildEvent produces every required field, append-only shaped", () => {
  const now = Date.parse("2026-01-01T00:00:00Z");
  const event = buildEvent({
    event: "pause_command", previousState: "running", newState: "pause_requested",
    reason: "owner requested pause", taskId: "DA-03", sessionId: "sess-1", now,
  });
  assert.equal(event.ts, new Date(now).toISOString());
  assert.equal(event.event, "pause_command");
  assert.equal(event.previous_state, "running");
  assert.equal(event.new_state, "pause_requested");
  assert.equal(event.reason, "owner requested pause");
  assert.equal(event.task_id, "DA-03");
  assert.equal(event.session_id, "sess-1");
});

test("buildEvent defaults reason/task_id/session_id to null rather than undefined (JSON-safe)", () => {
  const event = buildEvent({ event: "start", previousState: "stopped", newState: "starting", now: 0 });
  assert.equal(event.reason, null);
  assert.equal(event.task_id, null);
  assert.equal(event.session_id, null);
  assert.doesNotThrow(() => JSON.stringify(event));
});

// --- task id / path validation (API layer defense) -----------------------

test("isSafeTaskId accepts real task ids used in this repo", () => {
  for (const id of ["TOKEN-EFFICIENCY-VERIFY", "DA-03", "RUNNER-002", "SR-01"]) {
    assert.equal(isSafeTaskId(id), true, id);
  }
});

test("isSafeTaskId rejects path traversal and shell-metacharacter attempts", () => {
  for (const id of ["../../etc/passwd", "..\\..\\windows", "DA-03; rm -rf /", "DA 03", "", "a".repeat(200), "/abs/path"]) {
    assert.equal(isSafeTaskId(id), false, id);
  }
});

test("resolveTaskFile stays inside queueDir for a safe id and rejects traversal ids outright", () => {
  const queueDir = path.join("C:", "repo", "tasks", "queue");
  const resolved = resolveTaskFile(queueDir, "DA-03", path);
  assert.equal(resolved, path.join(queueDir, "DA-03.yaml"));
  assert.equal(resolveTaskFile(queueDir, "../../../etc/passwd", path), null);
  assert.equal(resolveTaskFile(queueDir, "..", path), null);
});

// --- task action rules --------------------------------------------------

test("taskActionAllowed: hold only from ready, unhold only from held", () => {
  assert.equal(taskActionAllowed("hold", "ready"), true);
  assert.equal(taskActionAllowed("hold", "running"), false);
  assert.equal(taskActionAllowed("unhold", "held"), true);
  assert.equal(taskActionAllowed("unhold", "ready"), false);
});

test("taskActionAllowed: retry only from failed/waiting_for_auth/interrupted, never from done", () => {
  assert.equal(taskActionAllowed("retry", "failed"), true);
  assert.equal(taskActionAllowed("retry", "waiting_for_auth"), true);
  assert.equal(taskActionAllowed("retry", "interrupted"), true);
  assert.equal(taskActionAllowed("retry", "done"), false);
  assert.equal(taskActionAllowed("retry", "ready"), false);
});

test("taskActionAllowed: skip never allowed on an already-running or already-done task", () => {
  assert.equal(taskActionAllowed("skip", "ready"), true);
  assert.equal(taskActionAllowed("skip", "waiting_for_limit"), true);
  assert.equal(taskActionAllowed("skip", "running"), false);
  assert.equal(taskActionAllowed("skip", "done"), false);
});

// --- reorder validation --------------------------------------------------

test("validateReorder accepts a simple reorder of independent ready tasks", () => {
  const tasksById = {
    A: { status: "ready" }, B: { status: "ready" }, C: { status: "ready" },
  };
  const result = validateReorder(["C", "A", "B"], tasksById);
  assert.equal(result.ok, true);
});

test("validateReorder rejects an unknown id and a duplicate id", () => {
  const tasksById = { A: { status: "ready" } };
  assert.equal(validateReorder(["A", "GHOST"], tasksById).ok, false);
  assert.equal(validateReorder(["A", "A"], tasksById).ok, false);
});

test("validateReorder rejects reordering a task that is not 'ready' (e.g. already running)", () => {
  const tasksById = { A: { status: "running" }, B: { status: "ready" } };
  const result = validateReorder(["A", "B"], tasksById);
  assert.equal(result.ok, false);
  assert.match(result.reason, /not 'ready'/);
});

test("validateReorder rejects placing a task ahead of an unmet dependency", () => {
  const tasksById = {
    A: { status: "ready", depends_on: ["B"] },
    B: { status: "ready" },
  };
  const result = validateReorder(["A", "B"], tasksById);
  assert.equal(result.ok, false);
  assert.match(result.reason, /dependency/);
  // The correct order (dependency first) is accepted.
  assert.equal(validateReorder(["B", "A"], tasksById).ok, true);
});

test("validateReorder allows a dependency ahead once it is already done, even if not included in the reorder", () => {
  const tasksById = {
    A: { status: "ready", depends_on: ["B"] },
    B: { status: "done" },
  };
  assert.equal(validateReorder(["A"], tasksById).ok, true);
});

// --- task summary (queue table shape) ------------------------------------

test("summarizeTask produces a stable, minimal shape for the queue table", () => {
  const task = {
    id: "DA-03", title: "Digital Asset candidate nomination", priority: "P1", status: "blocked",
    release: "no_deploy", owner_approved: false,
    result: { error: "Owner-only risk lacks owner_approved: true", sessions: [{ stage: 1 }] },
  };
  const summary = summarizeTask(task);
  assert.equal(summary.id, "DA-03");
  assert.equal(summary.blocked_reason, "Owner-only risk lacks owner_approved: true");
  assert.equal(summary.sessions_count, 1);
});

test("summarizeTask never throws on a task with no result yet", () => {
  const summary = summarizeTask({ id: "X", title: "t", priority: "P2", status: "ready", release: "no_deploy" });
  assert.equal(summary.sessions_count, 0);
  assert.equal(summary.blocked_reason, null);
});

test("summarizeTask attaches a casual project group and falls back display_summary to title", () => {
  const summary = summarizeTask({ id: "MED-01", title: "Codex CLI recon", priority: "P1", status: "ready", release: "no_deploy" });
  assert.equal(summary.group_key, "multi-executor");
  assert.equal(summary.group_name, "Клод + Кодекс работают вместе");
  assert.equal(summary.display_summary, "Codex CLI recon");
});

test("summarizeTask prefers an explicit display_summary over title", () => {
  const summary = summarizeTask({
    id: "MED-01", title: "Codex CLI recon", display_summary: "Проверяем, что вообще умеет Codex",
    priority: "P1", status: "ready", release: "no_deploy",
  });
  assert.equal(summary.display_summary, "Проверяем, что вообще умеет Codex");
});

// --- secret masking (logs panel) ------------------------------------------

test("maskSecrets redacts an Anthropic-shaped API key and a Bearer token", () => {
  const text = "Using key sk-ant-api03-abcdefghijklmnop and header Bearer xyz123abcdefghij done";
  const masked = maskSecrets(text);
  assert.doesNotMatch(masked, /sk-ant-api03-abcdefghijklmnop/);
  assert.doesNotMatch(masked, /xyz123abcdefghij/);
  assert.match(masked, /\[REDACTED\]/);
});

test("maskSecrets redacts an OWNER_PASSWORD=... style assignment", () => {
  const masked = maskSecrets("OWNER_PASSWORD=hunter2verysecret and more text");
  assert.doesNotMatch(masked, /hunter2verysecret/);
});

test("maskSecrets leaves ordinary log text untouched", () => {
  const text = "STAGE DA-02 #1/4 -- prompt 2793 chars (~699 tokens)\nDONE DA-02 (1 session(s))";
  assert.equal(maskSecrets(text), text);
});
