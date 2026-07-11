"use strict";

/**
 * Pure decision logic for RUNNER-CONTROL-UI -- no I/O, no child_process, no
 * network, so every rule here is directly unit-testable against synthetic
 * data. `claude_task_runner.js` (the runner engine) and `control_server.js`
 * (the local control API) both call into this module rather than each
 * re-implementing state/command rules -- this is the one place "is this
 * command legal right now" and "what does the next state look like" live.
 *
 * Runner-level (process) states -- what the whole runner is doing, distinct
 * from any single task's own status:
 */
const RUNNER_STATES = [
  "stopped", "starting", "idle", "running", "pause_requested", "paused",
  "stop_requested", "waiting_for_limit", "waiting_for_owner",
  "authentication_required", "failed", "completed",
];

/**
 * Task-level states. `ready`/`in_progress`(~running)/`done`/`failed`/
 * `blocked`/`waiting_for_limit` already exist and are written by
 * claude_task_runner.js today. `claimed`/`checkpointing`/`skipped`/
 * `waiting_for_auth`/`interrupted` are the ones this feature adds or makes
 * externally visible.
 */
const TASK_STATES = [
  "ready", "claimed", "in_progress", "checkpointing", "done", "failed",
  "blocked", "skipped", "waiting_for_limit", "waiting_for_auth", "interrupted",
];

// --- Commands --------------------------------------------------------------

const COMMANDS = ["pause", "resume", "stop_after_stage", "emergency_stop"];

function isValidCommand(command) {
  return COMMANDS.includes(command);
}

// Which commands make sense to ISSUE given the runner's current state --
// this is what the control server checks before even writing a command,
// so a client can't queue a nonsensical instruction (e.g. "resume" while
// already running).
function commandAllowedInState(command, runnerState) {
  switch (command) {
    case "pause":
      return runnerState === "running" || runnerState === "idle" || runnerState === "starting";
    case "resume":
      return runnerState === "paused" || runnerState === "pause_requested";
    case "stop_after_stage":
      return runnerState === "running" || runnerState === "idle" || runnerState === "starting" || runnerState === "pause_requested";
    case "emergency_stop":
      // Always allowed except when there is nothing left to stop -- this is
      // the one command that may need to act even mid-session, so it is
      // deliberately permissive; the runner engine, not this check, is what
      // decides whether there is actually a process to kill.
      return runnerState !== "stopped";
    default:
      return false;
  }
}

// --- Runner-level state transitions -----------------------------------

// Pure transition table: given the current runner state and an event the
// engine observed, what is the new state? Kept as data (not scattered
// if/else in the engine) so the whole machine can be reasoned about and
// tested in one place. `event` is one of: "start", "task_claimed",
// "no_ready_tasks", "pause_command", "safe_point_reached", "resume_command",
// "stop_after_stage_command", "emergency_stop_command", "rate_limited",
// "owner_gate_blocked", "auth_required", "task_failed", "queue_exhausted".
const TRANSITIONS = {
  stopped: { start: "starting" },
  starting: {
    task_claimed: "running",
    no_ready_tasks: "idle",
    auth_required: "authentication_required",
    // Nothing is running yet -- exactly like "idle", these act immediately.
    pause_command: "paused",
    stop_after_stage_command: "stopped",
    emergency_stop_command: "stopped",
  },
  idle: {
    task_claimed: "running",
    pause_command: "paused", // nothing in flight -- pauses immediately, no safe point to wait for
    stop_after_stage_command: "stopped",
    emergency_stop_command: "stopped",
  },
  running: {
    pause_command: "pause_requested",
    stop_after_stage_command: "stop_requested",
    emergency_stop_command: "stopped",
    safe_point_reached_idle: "idle",
    rate_limited: "waiting_for_limit",
    owner_gate_blocked: "waiting_for_owner",
    auth_required: "authentication_required",
    task_failed: "failed",
    queue_exhausted: "completed",
  },
  pause_requested: {
    safe_point_reached: "paused",
    emergency_stop_command: "stopped",
  },
  paused: {
    resume_command: "starting",
    emergency_stop_command: "stopped",
  },
  stop_requested: {
    safe_point_reached: "stopped",
    emergency_stop_command: "stopped",
  },
  waiting_for_limit: {
    start: "starting", // resumed once retry_after passes, via a fresh starting cycle
    emergency_stop_command: "stopped",
  },
  waiting_for_owner: {
    start: "starting", // resumed once a human sets owner_approved / unblocks the task
    emergency_stop_command: "stopped",
  },
  authentication_required: {
    start: "starting", // resumed only after a human confirms auth is fixed
    emergency_stop_command: "stopped",
  },
  failed: { start: "starting" },
  completed: { start: "starting" },
};

function nextRunnerState(current, event) {
  const row = TRANSITIONS[current];
  if (!row || !(event in row)) {
    return { ok: false, reason: `no transition for event '${event}' from state '${current}'` };
  }
  return { ok: true, state: row[event] };
}

// --- Append-only event log entries -----------------------------------

// Every transition the spec requires: timestamp, command/event, previous
// state, new state, reason, task id, process/session id. `now` is injected
// (never Date.now() called implicitly deep in a pure function) so this
// stays trivially testable.
function buildEvent({ event, previousState, newState, reason, taskId, sessionId, now }) {
  return {
    ts: new Date(now ?? Date.now()).toISOString(),
    event,
    previous_state: previousState,
    new_state: newState,
    reason: reason ?? null,
    task_id: taskId ?? null,
    session_id: sessionId ?? null,
  };
}

// --- Validation helpers for the local control API -----------------------

// Task ids in this codebase are always upper-kebab identifiers
// (TOKEN-EFFICIENCY-VERIFY, DA-03, RUNNER-002, ...). Rejecting anything
// else closes off path traversal (`../../etc/passwd`) and shell/argument
// injection through an API parameter before it ever reaches a filesystem
// path or a spawned command.
const SAFE_TASK_ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]*$/;

function isSafeTaskId(id) {
  return typeof id === "string" && id.length > 0 && id.length <= 128 && SAFE_TASK_ID_RE.test(id);
}

// Resolves a task id to its expected file path and confirms the result is
// still actually inside queueDir -- defense in depth against a task id that
// passes isSafeTaskId's regex but still resolves oddly on a platform with
// unusual path semantics.
function resolveTaskFile(queueDir, id, path) {
  if (!isSafeTaskId(id)) return null;
  const resolved = path.resolve(queueDir, `${id}.yaml`);
  const normalizedQueueDir = path.resolve(queueDir) + path.sep;
  if (!resolved.startsWith(normalizedQueueDir)) return null;
  return resolved;
}

module.exports = {
  RUNNER_STATES,
  TASK_STATES,
  COMMANDS,
  isValidCommand,
  commandAllowedInState,
  TRANSITIONS,
  nextRunnerState,
  buildEvent,
  SAFE_TASK_ID_RE,
  isSafeTaskId,
  resolveTaskFile,
};
