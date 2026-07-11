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
