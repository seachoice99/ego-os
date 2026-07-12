"use strict";

const { resolveGroup } = require("./project_groups.js");

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

// --- Task-level action rules (control-API queue management) --------------

// Which task actions make sense given the task's CURRENT status -- checked
// by control_server.js before ever touching a task file, so an accidental
// or malicious request (e.g. "retry" on a task that's still running)
// cannot corrupt an in-flight task.
function taskActionAllowed(action, taskStatus) {
  switch (action) {
    case "hold":
      return taskStatus === "ready";
    case "unhold":
      return taskStatus === "held";
    case "skip":
      return ["ready", "held", "blocked", "waiting_for_limit", "waiting_for_auth"].includes(taskStatus);
    case "retry":
      return ["failed", "waiting_for_auth", "interrupted"].includes(taskStatus);
    default:
      return false;
  }
}

// A reorder request may only touch "ready" tasks (an already-claimed,
// running, or finished task's position is never up for grabs), and must
// never place a task ahead of a `depends_on` task that has not reached
// "done" -- whether or not that dependency is itself part of the reorder.
function validateReorder(order, tasksById) {
  if (!Array.isArray(order) || !order.length) {
    return { ok: false, reason: "order must be a non-empty array of task ids" };
  }
  const seen = new Set();
  for (const id of order) {
    if (seen.has(id)) return { ok: false, reason: `duplicate id in reorder request: ${id}` };
    seen.add(id);
    const task = tasksById[id];
    if (!task) return { ok: false, reason: `unknown task id: ${id}` };
    if (task.status !== "ready") {
      return { ok: false, reason: `${id} is not 'ready' (currently '${task.status}') -- cannot reorder a task that is already claimed, running, or finished` };
    }
  }
  const position = new Map(order.map((id, i) => [id, i]));
  for (const id of order) {
    for (const depId of tasksById[id].depends_on || []) {
      const depTask = tasksById[depId];
      if (!depTask || depTask.status === "done") continue;
      if (!position.has(depId)) {
        return { ok: false, reason: `${id} depends on ${depId}, which is not done and not included in this reorder` };
      }
      if (position.get(depId) > position.get(id)) {
        return { ok: false, reason: `${id} cannot be placed ahead of its dependency ${depId}, which is not done` };
      }
    }
  }
  return { ok: true };
}

// A stable, minimal shape for the queue table (GET /api/tasks) -- deliberately
// never includes the full prompt/result blob by default, just enough for
// the UI's queue table and status bar. No secrets ever live in a task file
// in this codebase, but keeping the response shape explicit and narrow is
// still the safer default for anything served over the control API.
function summarizeTask(task) {
  const group = resolveGroup(task.id);
  return {
    id: task.id,
    title: task.title,
    display_summary: task.display_summary || task.title,
    group_key: group.key,
    group_name: group.name,
    group_casual_summary: group.casual_summary,
    priority: task.priority,
    status: task.status,
    release: task.release,
    owner_approved: Boolean(task.owner_approved),
    max_duration_minutes: task.max_duration_minutes ?? null,
    queue_order: task.queue_order ?? null,
    blocked_reason: task.status === "blocked" ? (task.result && (task.result.error || task.result.reason)) || null : null,
    retry_after: (task.result && task.result.retry_after) || null,
    summary: (task.result && task.result.summary) || null,
    sessions_count: (task.result && Array.isArray(task.result.sessions)) ? task.result.sessions.length : 0,
  };
}

// --- Secret masking for the logs panel ------------------------------------

// Defense in depth for GET /api/logs: a stage's raw stream-json log is not
// expected to contain credentials (the runner never prints .env contents),
// but a copy-paste of an error message or an environment dump inside a
// child process's own output is not impossible. These patterns are masked
// unconditionally before any log line ever leaves the control server.
const SECRET_PATTERNS = [
  /sk-ant-[A-Za-z0-9_-]{10,}/g,
  /sk-[A-Za-z0-9_-]{20,}/g,
  /Bearer\s+[A-Za-z0-9._-]{10,}/gi,
  /(OWNER_PASSWORD|OPENROUTER_API_KEY|API_KEY|ANTHROPIC_API_KEY)\s*=\s*\S+/gi,
];

function maskSecrets(text) {
  let masked = String(text ?? "");
  for (const pattern of SECRET_PATTERNS) {
    masked = masked.replace(pattern, "[REDACTED]");
  }
  return masked;
}

// --- Windows Runner Agent coordination ------------------------------------
// Claude Code cannot run on the production VPS (confirmed live, external
// blocker -- the CLI hangs identically whether launched via npm, the
// native installer's own setup step, or interactively). Execution moves to
// a Windows agent on the Owner's own machine; the VPS becomes a
// coordinator only: it stores the queue, hands out one task at a time,
// tracks liveness, and never runs `claude` itself again.

// How long an agent may hold a claimed task before the lease is treated as
// abandoned and the task becomes claimable again -- checked lazily by
// nextTask()'s own filter (no separate background timer needed), matching
// the existing waiting_for_limit / isRetryDue pattern exactly.
const AGENT_LEASE_MINUTES_DEFAULT = 30;

function isLeaseExpired(lease, now = Date.now()) {
  if (!lease || !lease.expires_at) return true;
  const t = Date.parse(lease.expires_at);
  return !Number.isFinite(t) || now >= t;
}

function buildLease(agentId, minutes, now = Date.now()) {
  return {
    agent_id: agentId,
    claimed_at: new Date(now).toISOString(),
    expires_at: new Date(now + (minutes || AGENT_LEASE_MINUTES_DEFAULT) * 60000).toISOString(),
  };
}

// Replay/reused-request defense that doesn't depend on synchronized
// clocks: each agent keeps its own strictly-increasing local counter and
// sends it as `seq` on every request. The server remembers the highest
// `seq` it has ever accepted per agent_id and rejects anything at or
// below that -- a genuine new request from a well-behaved agent always
// uses a higher seq than any request before it; a captured-and-replayed
// request reuses an old (now too-low) seq and is rejected.
function isReplayedRequest(seq, lastSeqSeen) {
  if (!Number.isFinite(seq) || seq <= 0) return true; // malformed is never trusted
  if (lastSeqSeen == null) return false;
  return seq <= lastSeqSeen;
}

// An agent counts as online if it has heartbeated within the last
// staleAfterMs -- a simple, honest liveness signal for /automation to
// display, never inferred from anything else (no "probably still running"
// guessing).
function isAgentOnline(lastHeartbeatAt, now = Date.now(), staleAfterMs = 90000) {
  if (!lastHeartbeatAt) return false;
  const t = Date.parse(lastHeartbeatAt);
  return Number.isFinite(t) && (now - t) < staleAfterMs;
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
  taskActionAllowed,
  validateReorder,
  summarizeTask,
  SECRET_PATTERNS,
  maskSecrets,
  AGENT_LEASE_MINUTES_DEFAULT,
  isLeaseExpired,
  buildLease,
  isReplayedRequest,
  isAgentOnline,
};
