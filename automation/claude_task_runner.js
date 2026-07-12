#!/usr/bin/env node
"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const cp = require("child_process");

const { verifyFinalSyncEvidence } = require("./release_sync.js");
const {
  DEFAULT_MAX_AUTO_STAGES,
  validateHandoff,
  handoffWordCount,
  isRetryDue,
  planStages,
  buildGitStateBlock,
  buildHandoffBlock,
  estimatePromptSize,
  classifySessionOutcome,
  decideNextAction,
  claudeInvocationArgs,
} = require("./session_manager.js");
const {
  commandAllowedInState,
  nextRunnerState,
  buildEvent,
  isLeaseExpired,
} = require("./runner_control.js");
const { extractSessionUsage, emptyTracker, recordSession } = require("./usage_tracker.js");
const { listProcessParents, killProcessTree } = require("./process_tree.js");
const { fetchCodexUsageSnapshot, formatConsoleReport, unknownSnapshot: unknownCodexSnapshot } = require("./codex_usage.js");

// Overridable so tests can run preflight()'s real (but read-only) git
// checks against an isolated throwaway repo instead of depending on this
// checkout's own working tree being clean at test time.
const ROOT = process.env.EGO_OS_RUNNER_ROOT_DIR || path.resolve(__dirname, "..");
const QUEUE = process.env.EGO_OS_RUNNER_QUEUE_DIR || path.join(ROOT, "tasks", "queue");
// Overridable so tests can isolate the lock/log/handoff directories from
// this machine's real runner state without touching %LOCALAPPDATA%.
const LOCAL = process.env.EGO_OS_RUNNER_LOCAL_DIR || process.env.LOCALAPPDATA || os.homedir();
const LOCK = path.join(LOCAL, "ego-os-claude-runner.lock");
const LOG_DIR = path.join(LOCAL, "EgoOS", "claude-runner", "logs");
const HANDOFF_DIR = path.join(LOCAL, "EgoOS", "claude-runner", "handoffs");
// RUNNER-CONTROL-UI: the shared, file-based protocol between this engine
// and control_server.js -- deliberately not a socket/IPC channel so a
// control server that starts after the runner (or is restarted) can still
// read/write the same state without any live connection.
const CONTROL_DIR = path.join(LOCAL, "EgoOS", "claude-runner", "control");
const COMMANDS_FILE = path.join(CONTROL_DIR, "commands.json");
const RUNNER_STATE_FILE = path.join(CONTROL_DIR, "runner_state.json");
const EVENTS_FILE = path.join(CONTROL_DIR, "events.ndjson");
// Casual dashboard's limits tracker (see automation/usage_tracker.js for
// why this is parsed from the session's own free, already-emitted final
// stream-json "result" line rather than any separate command/API call).
const USAGE_FILE = path.join(CONTROL_DIR, "usage_tracker.json");
// Codex (ChatGPT) rate-limit snapshots -- one JSONL line per finished
// Codex session, deliberately OUTSIDE the git-tracked repo, exactly like
// LOG_DIR/HANDOFF_DIR (see automation/codex_usage.js). Never read/written
// by the final-sync protocol or any git command.
const CODEX_USAGE_LOG_FILE = path.join(LOCAL, "EgoOS", "claude-runner", "codex-usage.jsonl");
// Overridable so tests can point the runner at a fake/mock executable
// instead of ever spawning a real Claude Code process. The Windows default
// names an absolute path because npm's global bin location is predictable
// there; on Linux/macOS there's no equivalent single predictable path
// (nvm, system npm, NodeSource, etc. all differ), so the default is the
// bare command name and resolution is left to PATH via shell:true --
// preflight() below deliberately skips its own fs.existsSync check for a
// non-absolute CLAUDE for exactly this reason.
const CLAUDE = process.env.EGO_OS_RUNNER_CLAUDE_PATH
  || (process.platform === "win32" ? path.join(process.env.APPDATA || "", "npm", "claude.cmd") : "claude");
const OWNER_ONLY = new Set(["destructive_data", "irreversible_migration", "payments", "secrets", "external_infrastructure"]);

function run(file, args, timeout = 60000, opts = {}) {
  return cp.spawnSync(file, args, { cwd: ROOT, encoding: "utf8", timeout, windowsHide: true, ...opts });
}

// Windows cannot execute a .cmd file directly via spawnSync -- without
// shell:true it fails immediately with EINVAL (verified: `claude.cmd
// --version` errors out with no output at all). shell:true fixes that,
// but on Windows it routes the command through cmd.exe, which *does*
// interpret shell metacharacters (&, |, ^, ") in argv elements -- verified
// live: a prompt string containing "& echo INJECTED &" passed as an argv
// element was executed as a second command, not treated as literal text.
// The fix is to never put untrusted content (the task prompt) in argv at
// all: only fixed, code-controlled flags go in args, and the actual
// prompt -- which embeds task.yaml fields the runner doesn't otherwise
// sanitize -- is piped over stdin instead, exactly as `claude -p` already
// supports ("useful for pipes" per its own --help text). Verified live
// with the real CLI: the same dangerous string passed via stdin arrived
// byte-for-byte with no shell interpretation and no injected command.
//
// Deliberately async cp.spawn, NOT spawnSync -- found live while testing
// TOKEN-EFFICIENCY-001's own timeout/handoff staging: spawnSync's built-in
// `timeout` option kills the *direct* child (cmd.exe) itself the instant
// it fires. By the time our own code got control back to run its own
// tree-kill, that PID was already gone -- nothing left to walk the rest
// of the tree (cmd.exe -> claude.cmd -> claude.exe) from, so a genuine
// timeout could still orphan the underlying claude.exe exactly like the
// original DA-01 defect, just via a different race. Owning the kill
// ourselves, on a live process tree, before anything else touches it,
// closes that race: the timer below fires while the tree is still alive.
// opts.pollEmergencyStop, if given, is polled on an interval (never any
// other command -- pause/stop_after_stage NEVER interrupt an in-flight
// session, only emergency_stop may) so a genuinely dangerous command can
// still act while a session is running, not just between stages.
function runClaude(promptText, args, timeoutMs, opts = {}) {
  return new Promise((resolve) => {
    const child = cp.spawn(CLAUDE, args, { cwd: ROOT, shell: true, windowsHide: true });
    let stdout = "", stderr = "", timedOut = false, interrupted = false, settled = false;
    if (child.stdout) child.stdout.on("data", (d) => { stdout += d.toString(); });
    if (child.stderr) child.stderr.on("data", (d) => { stderr += d.toString(); });

    const timer = setTimeout(() => {
      timedOut = true;
      killProcessTree(child.pid);
    }, timeoutMs);

    const emergencyPoll = opts.pollEmergencyStop
      ? setInterval(() => {
          if (!settled && opts.pollEmergencyStop()) {
            interrupted = true;
            killProcessTree(child.pid);
          }
        }, opts.pollIntervalMs || 2000)
      : null;

    function finish(result) {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (emergencyPoll) clearInterval(emergencyPoll);
      resolve(result);
    }

    child.on("error", (error) => {
      finish({ status: null, signal: null, stdout, stderr, pid: child.pid, error });
    });
    child.on("close", (status, signal) => {
      // A final, unconditional tree-kill safety net even on an ordinary
      // close -- a no-op if nothing is left, a hard backstop if the
      // process reported closed while a descendant (e.g. a background
      // Agent-tool subagent) is still alive, exactly the shape of the
      // original DA-01 orphan.
      killProcessTree(child.pid);
      finish({ status, signal: (timedOut || interrupted) ? (signal || "SIGTERM") : signal, stdout, stderr, pid: child.pid, interrupted });
    });

    if (child.stdin) {
      child.stdin.write(promptText || "");
      child.stdin.end();
    }
  });
}

function load(file) {
  const task = JSON.parse(fs.readFileSync(file, "utf8"));
  for (const key of ["id", "status", "priority", "title", "prompt", "acceptance", "release"]) {
    if (!(key in task)) throw new Error(`${file}: missing ${key}`);
  }
  if (!Array.isArray(task.acceptance) || !task.acceptance.length) throw new Error(`${file}: acceptance must be a non-empty array`);
  return task;
}

function save(file, task) {
  fs.writeFileSync(file, JSON.stringify(task, null, 2) + "\n", "utf8");
}

// --- RUNNER-CONTROL-UI: file-based control protocol ------------------------
// A pending command is a single JSON object at COMMANDS_FILE -- the control
// server writes it, the engine reads and clears it at a genuinely safe
// point (never mid-runClaude(), except emergency_stop's own poll below).
// This is deliberately NOT a queue of commands: only the latest instruction
// matters, and there is exactly one runner per workspace by design (the
// existing lock file already enforces that).
function readPendingCommand() {
  try {
    const parsed = JSON.parse(fs.readFileSync(COMMANDS_FILE, "utf8"));
    return parsed && typeof parsed.command === "string" ? parsed : null;
  } catch {
    return null;
  }
}

function clearPendingCommand() {
  try { fs.unlinkSync(COMMANDS_FILE); } catch { /* already absent */ }
}

function appendEvent(event) {
  fs.mkdirSync(CONTROL_DIR, { recursive: true });
  fs.appendFileSync(EVENTS_FILE, JSON.stringify(event) + "\n", "utf8");
}

// Thin I/O shell around usage_tracker.js's pure functions -- same split as
// runner_control.js (pure) / this file (owns the actual file path and
// fs calls). Never throws on a missing/corrupt file: a fresh, empty
// tracker is a safe, honest starting point, not a fatal error.
function readUsageTracker() {
  try {
    return JSON.parse(fs.readFileSync(USAGE_FILE, "utf8"));
  } catch {
    return emptyTracker();
  }
}

function writeUsageTracker(state) {
  fs.mkdirSync(CONTROL_DIR, { recursive: true });
  fs.writeFileSync(USAGE_FILE, JSON.stringify(state, null, 2), "utf8");
}

// Most recent Codex rate-limit snapshot, for the dashboard's "Лимиты"
// panel -- reads the last line of codex-usage.jsonl (append-only, one
// entry per finished Codex session). Never throws: a missing/empty/
// corrupt log is a normal "no data yet" state, not an error.
function readLatestCodexUsageSnapshot() {
  try {
    const lines = fs.readFileSync(CODEX_USAGE_LOG_FILE, "utf8").trim().split("\n").filter(Boolean);
    if (!lines.length) return null;
    return JSON.parse(lines[lines.length - 1]);
  } catch {
    return null;
  }
}

// Called once per finished session (successful or not -- cost/turns were
// spent either way), never per dashboard poll and never via a separate
// "/usage"-style command. executor defaults to "claude" until MED-02 (real
// Codex path) lets a task carry a real, implemented `executor` value.
function recordSessionUsage(task, rawOutput) {
  const usage = extractSessionUsage(rawOutput);
  const next = recordSession(readUsageTracker(), task.executor || "claude", task.id, usage);
  writeUsageTracker(next);
}

// Codex (ChatGPT) rate-limit snapshot -- see automation/codex_usage.js for
// the protocol/rationale. Fires only for a session that actually ran
// through Codex; `executor` is never guessed here (see resolvedExecutor in
// execute(), below, for why it is unconditionally "claude" today -- MED-02
// has not shipped a real Codex dispatch path yet, so this is correctly
// inert until it does). A failed/unreadable snapshot is logged with
// status "unknown" and never rethrown -- it must never change the task's
// own outcome (already saved to disk before this is ever called) or stop
// the queue.
async function snapshotCodexUsageIfNeeded(task, executor) {
  if (executor !== "codex") return;
  let snapshot;
  try {
    snapshot = await fetchCodexUsageSnapshot({});
  } catch (error) {
    snapshot = unknownCodexSnapshot(`unexpected error calling codex app-server: ${error.message}`);
  }
  console.log(formatConsoleReport(task.id, snapshot));
  try {
    fs.mkdirSync(path.dirname(CODEX_USAGE_LOG_FILE), { recursive: true });
    fs.appendFileSync(CODEX_USAGE_LOG_FILE, JSON.stringify({ task_id: task.id, task_status: task.status, ...snapshot }) + "\n", "utf8");
  } catch (logError) {
    console.error(`WARNING: could not append to codex-usage.jsonl: ${logError.message}`);
  }
}

function writeRunnerState(state, extra = {}) {
  fs.mkdirSync(CONTROL_DIR, { recursive: true });
  const payload = { state, updated_at: new Date().toISOString(), pid: process.pid, ...extra };
  fs.writeFileSync(RUNNER_STATE_FILE, JSON.stringify(payload, null, 2), "utf8");
}

// The single in-process source of truth for "what is the runner doing" --
// every transition goes through here so the append-only event log and the
// live state snapshot can never drift apart. Returns false (a silent
// no-op) for an event that has no transition from the current state --
// e.g. a stray duplicate command -- rather than throwing, since this is
// read by an external, independently-timed control server.
let runnerState = "stopped";
function transition(event, { reason, taskId, sessionId } = {}) {
  const result = nextRunnerState(runnerState, event);
  if (!result.ok) return false;
  const previousState = runnerState;
  runnerState = result.state;
  appendEvent(buildEvent({ event, previousState, newState: runnerState, reason, taskId, sessionId }));
  writeRunnerState(runnerState, { current_task_id: taskId || null, reason: reason || null });
  return true;
}

// The runner's own post-session bookkeeping (sessions[], retry_after,
// rate_limit, runner_error) is written directly to the task file via
// save() -- Claude's own commits inside the stage never include these
// fields, since they don't exist until after its process has already
// exited. Left uncommitted, that write leaves the working tree dirty,
// which the NEXT invocation's preflight() (clean-tree required) then
// refuses to run past -- found live: TOKEN-EFFICIENCY-VERIFY's own
// waiting_for_limit write blocked the whole queue, not just itself.
// Scoped to exactly this one task file (never `git add -A`) so a stray
// uncommitted change Claude itself left behind is never silently swept
// in -- that should still fail the next preflight(), not be papered over.
function commitRunnerState(file, taskId, label) {
  const rel = path.relative(ROOT, file);
  // Task files live under ROOT in every real invocation (tasks/queue/*.yaml
  // inside the repo). Some tests deliberately place fake task files in an
  // unrelated temp directory outside ROOT to isolate fixtures from the
  // small throwaway git repo used for preflight() checks -- there is
  // nothing to commit in that case, and `git add` on an out-of-repo path
  // would just fail, so skip it rather than surface a spurious warning.
  if (rel.startsWith("..") || path.isAbsolute(rel)) return { ok: true, committed: false, skipped: "outside repository root" };
  const add = run("git", ["add", "--", rel]);
  if (add.status !== 0) return { ok: false, reason: add.stderr.trim() || "git add failed" };
  const staged = run("git", ["diff", "--cached", "--quiet"]);
  if (staged.status === 0) return { ok: true, committed: false };
  const commit = run("git", ["commit", "-m", `${taskId}: runner state (${label})`]);
  if (commit.status !== 0) return { ok: false, reason: commit.stderr.trim() || "git commit failed" };
  const push = run("git", ["push", "origin", "main"]);
  if (push.status !== 0) return { ok: false, reason: push.stderr.trim() || "git push failed" };
  return { ok: true, committed: true };
}

function handoffPathFor(taskId) {
  return path.join(HANDOFF_DIR, `${taskId}.json`);
}

function readHandoff(taskId) {
  const p = handoffPathFor(taskId);
  if (!fs.existsSync(p)) return null;
  try {
    return JSON.parse(fs.readFileSync(p, "utf8"));
  } catch {
    return null;
  }
}

async function preflight() {
  const status = run("git", ["status", "--porcelain"]);
  if (status.status !== 0 || status.stdout.trim()) return [false, "working tree is not clean"];
  const fetch = run("git", ["fetch", "origin", "main"]);
  if (fetch.status !== 0) return [false, fetch.stderr.trim() || "git fetch failed"];
  const head = run("git", ["rev-parse", "HEAD"]).stdout.trim();
  const origin = run("git", ["rev-parse", "origin/main"]).stdout.trim();
  const branch = run("git", ["branch", "--show-current"]).stdout.trim();
  if (branch !== "main" || head !== origin) return [false, "local main must exactly match origin/main"];
  // Only meaningful for an absolute CLAUDE path (Windows' default, or any
  // explicit EGO_OS_RUNNER_CLAUDE_PATH override) -- a bare command name
  // (the non-Windows default, resolved via PATH through shell:true) isn't
  // a real filesystem path relative to ROOT, so fs.existsSync against it
  // would just check for a wrongly-named file in the repo and always fail.
  // The real existence/executability check either way is the probe below.
  if (path.isAbsolute(CLAUDE) && !fs.existsSync(CLAUDE)) return [false, `Claude CLI not found at ${CLAUDE}`];
  // Confirms the CLI is actually invokable this way (shell:true, no
  // untrusted content in argv) before committing to a task run -- catches
  // an EINVAL/quoting regression, a missing PATH entry, or a hung/broken
  // CLI before burning a task attempt.
  const probe = await runClaude("", ["--version"], 15000);
  if (probe.status !== 0 || probe.error) return [false, `Claude CLI probe failed: ${(probe.error && probe.error.message) || probe.stderr || "non-zero exit"}`];
  return [true, head];
}

const PRIORITY_RANK = { P0: 0, P1: 1, P2: 2, P3: 3 };

// Shared by nextTask() and the control API (GET /api/tasks) so the API
// never re-implements queue scanning/loading itself. A task file that
// fails to load (bad JSON, missing required field) is skipped with a
// console warning rather than crashing the whole scan -- one malformed
// task must never take down visibility into every other task.
function listTasks() {
  return fs.readdirSync(QUEUE).filter(x => x.endsWith(".yaml") && !x.startsWith("_")).flatMap(name => {
    const file = path.join(QUEUE, name);
    try {
      return [{ file, task: load(file) }];
    } catch (error) {
      console.error(`WARNING: skipping unreadable task file ${file}: ${error.message}`);
      return [];
    }
  });
}

function nextTask() {
  const now = Date.now();
  const tasks = listTasks().filter(x => {
    if (x.task.status === "ready") return true;
    // A task parked waiting_for_limit becomes eligible again once its own
    // recorded retry_after has passed -- never sooner, so the runner never
    // spends an attempt (or paid usage credits) trying to beat a limit
    // that hasn't actually reset yet.
    if (x.task.status === "waiting_for_limit") {
      return isRetryDue(x.task.result && x.task.result.retry_after, now);
    }
    // A task left "checkpointing" by a pause/stop_after_stage command
    // between stages resumes exactly where it left off (its sessions[]
    // already reflects every completed stage) -- unlike waiting_for_auth,
    // which requires an explicit human "retry", this one is safe to just
    // pick back up: the human's own resume command already authorized it.
    if (x.task.status === "checkpointing") return true;
    // Windows Runner Agent coordination: a task "claimed" by an agent
    // (control_server.js's /api/agent/claim) reverts to its pre-claim
    // status once the lease expires -- the agent may have crashed, lost
    // network, or the Owner's machine may simply be off. Reverted lazily
    // here (no separate background timer needed), matching the existing
    // isRetryDue pattern exactly.
    if (x.task.status === "claimed") {
      const lease = x.task.result && x.task.result.agent_lease;
      if (isLeaseExpired(lease, now)) {
        const reverted = load(x.file);
        reverted.status = (reverted.result && reverted.result.pre_claim_status) || "ready";
        if (reverted.result) {
          reverted.result.agent_lease = null;
          reverted.result.lease_expired_at = new Date(now).toISOString();
        }
        save(x.file, reverted);
        commitRunnerState(x.file, reverted.id, "lease expired, reverted to " + reverted.status);
        x.task = reverted;
        return reverted.status === "ready" || (reverted.status === "waiting_for_limit" && isRetryDue(reverted.result && reverted.result.retry_after, now));
      }
      return false; // still validly leased to a live agent
    }
    return false;
  });
  // queue_order (set by POST /api/tasks/reorder) breaks ties within the
  // same priority tier before falling back to filename -- absent for every
  // task that was never explicitly reordered, so existing queues sort
  // exactly as before.
  tasks.sort((a, b) => (PRIORITY_RANK[a.task.priority] ?? 99) - (PRIORITY_RANK[b.task.priority] ?? 99)
    || (a.task.queue_order ?? Infinity) - (b.task.queue_order ?? Infinity)
    || a.file.localeCompare(b.file));
  return tasks[0] || null;
}

function gitStateBlockNow() {
  const headSha = run("git", ["rev-parse", "HEAD"]).stdout.trim();
  const statusPorcelain = run("git", ["status", "--porcelain"]).stdout;
  const recentCommits = run("git", ["log", "--oneline", "-5"]).stdout.trim().split("\n").filter(Boolean);
  return buildGitStateBlock({ headSha, statusPorcelain, recentCommits });
}

// Builds one stage's complete starting prompt. Deliberately pure given its
// inputs (gitState/handoff are pre-computed by the caller) so it can be
// unit-tested without any real git or file I/O.
function buildStagePrompt(task, relPath, gitState, stageIndex, maxStages, stageDef, handoff, handoffPath) {
  const criteria = task.acceptance.map(x => `- ${x}`).join("\n");
  const allowed = (task.allowed_paths || ["task-required repository paths"]).map(x => `- ${x}`).join("\n");
  const forbidden = (task.forbidden_paths || []).map(x => `- ${x}`).join("\n") || "- none beyond repository rules";
  const deploy = task.release === "automatic";
  const handoffBlock = buildHandoffBlock(handoff);
  const stageLabel = maxStages > 1 ? `STAGE ${stageIndex + 1} of up to ${maxStages}` : "SINGLE STAGE";
  const stageFocus = stageDef && stageDef.prompt ? `\nTHIS STAGE'S FOCUS:\n${stageDef.prompt}\n` : "";

  return `You are the autonomous implementation and release worker for Ego OS, running as ${stageLabel} of task ${task.id}.
Read CLAUDE.md and AI_ONBOARDING.md first. Work only on ${task.id} in ${relPath}.

${gitState}
${handoffBlock ? `\n${handoffBlock}\n` : ""}
TITLE: ${task.title}${stageDef ? ` -- ${stageDef.title}` : ""}

PROMPT:
${task.prompt}
${stageFocus}
ACCEPTANCE:
${criteria}

EXPECTED PATHS:
${allowed}

FORBIDDEN PATHS:
${forbidden}

Rules:
1. Stay in scope and never touch another in-progress task.
2. Never perform destructive data operations, irreversible migrations, payments, secret changes, external publication, or non-Ego-OS infrastructure changes without owner_approved: true for that recorded risk.
3. Implement the smallest complete solution and add relevant tests.
4. Move this task file through in_progress, testing, deploying, done; record changed files, tests, commit, deploy, health check, and concise result.
5. Do not commit secrets, settings, caches, logs, scratch files, generated artifacts, or another agent's work.
6. Tests must pass. Every commit you make for this task -- including the final metadata commit in rule 11 -- must start with '${task.id}:'; push main to origin/main after each one.
7. ${deploy ? "Deploy the implementation commit using DEPLOYMENT.md and require active service plus HTTP 200." : "Do not deploy."}
8. On any unsafe or incomplete step set status failed (or blocked) with the exact blocker and stop. Never claim success without evidence.
9. COMMIT EARLY AND OFTEN. Do not wait until everything is finished to make your first commit -- this session has a real time budget, this stage will be stopped (not gracefully) once it runs out, and uncommitted work at that point is lost. A small, real, working commit survives a stage boundary; a large uncommitted change does not.
10. Before ending this stage for ANY reason -- finished, or running low on time/turns -- write a handoff file to exactly this path: ${handoffPath}
    It must be a single JSON object with exactly these fields: {"summary": "what you did this stage, one or two sentences", "commit": "the short commit hash you made this stage, or null if none", "changed_files": ["..."], "checks": "what you ran and its result, briefly", "remaining": "what is NOT done yet, or 'nothing -- task complete'", "risks": "anything the next stage (or the Owner) should know", "next_step": "the single next concrete action"}.
    Keep it under 1500 words total -- it is the ONLY context the next stage (if there is one) will have, not a transcript or a diff. Never put secrets, credentials, or raw hidden reasoning in it.
${deploy ? `11. After the implementation commit is deployed and verified, record that evidence and status "done" in this task file, then make a SEPARATE final commit of just that task-file update and push it to origin/main. This final commit must touch only this task's own YAML file (or another explicitly permitted release-metadata file) -- never re-touch ego_os/, requirements*, templates, static, config, or migrations in it.
12. Before treating the task as truly finished, reconcile production with that final commit so production is never left behind origin/main (this exact defect happened once before -- see automation/release_sync.js and CHANGELOG.md):
    a. Confirm production's current checkout HEAD equals the implementation commit you just deployed. If it does not, STOP: do not sync anything, set status failed/blocked with the discrepancy -- production changed out of band.
    b. Confirm your local HEAD equals origin/main HEAD. If it does not, STOP: something else pushed to origin/main, or your own push did not land.
    c. List every commit between the implementation commit and origin/main HEAD. If any commit's message does not start with '${task.id}:', STOP: a foreign commit is interleaved; do not fast-forward over unrelated history automatically. Set status failed/blocked and report it.
    d. Diff the file paths changed between the implementation commit and origin/main HEAD. If that diff is EXCLUSIVELY this task's own YAML file (or another explicitly permitted release-metadata file), sync production with 'git pull --ff-only' and skip restarting the service -- safe, since no application code changed. If the diff touches ego_os/, requirements*, templates, static, config, or a migration, do NOT skip the restart: run the normal deploy procedure (pull, restart, health check) instead.
    e. Only ever use 'git pull --ff-only' for this reconciliation, on production or anywhere else. Never use 'git reset', force push, or rewrite history.
    f. Record the outcome in this task's result.final_sync object: {"local_head": ..., "origin_head": ..., "production_head": ..., "restart_performed": true|false}. All three head values must be identical. Only leave status "done" if they match; otherwise set status "failed" with the discrepancy recorded there -- never leave status "done" without this evidence.` : ""}

You are authorized for task-scoped edits, tests, commit, push main, and ${deploy ? "Ego OS deploy" : "no deployment"}. Owner-only exclusions remain hard stops.`;
}

async function execute(selected, cliMaxTurns, cliTimeoutMinutes) {
  const { file, task } = selected;
  const risks = new Set(task.risks || []);
  if ([...risks].some(x => OWNER_ONLY.has(x)) && task.owner_approved !== true) {
    task.status = "blocked"; task.result = { error: "Owner-only risk lacks owner_approved: true" }; save(file, task); return false;
  }
  if (!["automatic", "no_deploy"].includes(task.release)) throw new Error("release must be automatic or no_deploy");
  const [ok, detail] = await preflight();
  if (!ok) { console.error(`STOP: ${detail}`); return false; }

  // TOKEN-EFFICIENCY-001: a large task is not run as one unbounded
  // session. Explicit task.checkpoints (if declared) fix the exact stage
  // plan; otherwise the runner adapts at runtime -- only splitting into a
  // fresh session if a stage actually exhausts its time/turn budget, never
  // pre-emptively. context_strategy:"single" opts a task out entirely,
  // reproducing the pre-TOKEN-EFFICIENCY-001 all-or-nothing behavior.
  const declaredStages = planStages(task);
  const maxStages = task.context_strategy === "single" ? 1
    : declaredStages ? declaredStages.length
    : (Number(task.max_auto_stages) || DEFAULT_MAX_AUTO_STAGES);
  const stageDurationMinutes = Number(task.max_duration_minutes) || cliTimeoutMinutes;
  const model = task.model || null;
  // No real per-executor dispatch exists yet (MED-02 is still `blocked`) --
  // every session today actually runs via the Claude binary regardless of
  // what task.executor says, so this names that reality explicitly instead
  // of reading task.executor and pretending a Codex session already ran.
  // EGO_OS_RUNNER_FORCE_EXECUTOR exists solely so tests can exercise the
  // Codex-usage-snapshot path today without waiting on MED-02; production
  // never sets it.
  const resolvedExecutor = process.env.EGO_OS_RUNNER_FORCE_EXECUTOR || "claude";

  const existingSessions = (task.result && Array.isArray(task.result.sessions)) ? task.result.sessions.slice() : [];
  const sessions = existingSessions;
  let stageIndex = sessions.length; // resumes exactly where a prior waiting_for_limit pause left off

  task.status = "in_progress";
  task.started_at = task.started_at || new Date().toISOString();
  task.result = { ...(task.result || {}), sessions };
  save(file, task);
  fs.mkdirSync(LOG_DIR, { recursive: true });
  fs.mkdirSync(HANDOFF_DIR, { recursive: true });

  while (stageIndex < maxStages) {
    // Safe point: between stages. pause/stop_after_stage never interrupt a
    // session already in flight -- they only ever prevent the NEXT one from
    // starting. The task is left exactly where it is (its sessions[] array
    // already reflects every completed stage), so resuming later re-enters
    // this same loop at the same stageIndex -- identical to how
    // waiting_for_limit already resumes.
    // Not gated on commandAllowedInState here: whether a command was sane
    // to ISSUE was already validated once, by whoever wrote it (in
    // production, control_server.js checks that before writing); a stage
    // boundary is simply where the engine consumes whatever is currently
    // pending, matching the equally unconditional emergency_stop poll in
    // runClaude() above.
    const pendingBetweenStages = readPendingCommand();
    if (pendingBetweenStages && (pendingBetweenStages.command === "pause" || pendingBetweenStages.command === "stop_after_stage")) {
      const current = load(file);
      current.status = "checkpointing";
      current.result = { ...(current.result || {}), sessions, paused_before_stage: stageIndex + 1 };
      save(file, current);
      const commitResult = commitRunnerState(file, task.id, `${pendingBetweenStages.command} before stage ${stageIndex + 1}`);
      if (!commitResult.ok) console.error(`WARNING: could not commit ${task.id}'s checkpointing state: ${commitResult.reason}`);
      if (pendingBetweenStages.command === "pause") {
        clearPendingCommand();
        transition("pause_command", { reason: `paused before stage ${stageIndex + 1}`, taskId: task.id });
        transition("safe_point_reached", { reason: "no session in flight", taskId: task.id });
      } else {
        clearPendingCommand();
        transition("stop_after_stage_command", { reason: `stopping after stage ${stageIndex} completed`, taskId: task.id });
        transition("safe_point_reached", { reason: "no session in flight", taskId: task.id });
      }
      console.log(`${pendingBetweenStages.command.toUpperCase()} ${task.id} -- stopped before stage ${stageIndex + 1}, resumable from here`);
      return true; // an intentional, safe stop -- not a failure
    }

    const stageDef = declaredStages ? declaredStages[stageIndex] : null;
    const handoffBefore = readHandoff(task.id);
    const gitState = gitStateBlockNow();
    const relPath = path.relative(ROOT, file).replaceAll("\\", "/");
    const prompt = buildStagePrompt(task, relPath, gitState, stageIndex, maxStages, stageDef, handoffBefore, handoffPathFor(task.id));
    const sizeInfo = estimatePromptSize(prompt);
    console.log(`STAGE ${task.id} #${stageIndex + 1}/${maxStages} -- prompt ${sizeInfo.chars} chars (~${sizeInfo.approxTokens} tokens)${model ? ` -- model ${model}` : ""}`);

    const stamp = new Date().toISOString().replaceAll(/[:.]/g, "-");
    const logFile = path.join(LOG_DIR, `${stamp}-${task.id}-stage${stageIndex + 1}.log`);
    const stageStart = Date.now();
    const invocationArgs = claudeInvocationArgs({ maxTurns: cliMaxTurns, model });
    const output = await runClaude(prompt, invocationArgs, stageDurationMinutes * 60000, {
      pollEmergencyStop: () => {
        const pending = readPendingCommand();
        return Boolean(pending && pending.command === "emergency_stop");
      },
    });
    const durationMs = Date.now() - stageStart;
    fs.writeFileSync(logFile, (output.stdout || "") + (output.stderr || ""), "utf8");
    recordSessionUsage(task, output.stdout);

    if (output.interrupted) {
      // Emergency stop is the ONE command allowed to act mid-session. Per
      // spec: never delete files, never reset/checkout, mark the task
      // "interrupted" (not failed, not done), save diagnostics, and require
      // a recovery check on the next start -- handled by nextTask() simply
      // never selecting an "interrupted" task automatically.
      clearPendingCommand();
      const interruptedTask = load(file);
      interruptedTask.status = "interrupted";
      interruptedTask.result = {
        ...(interruptedTask.result || {}),
        sessions,
        runner_error: "emergency stop requested during a running session",
        interrupted_at: new Date().toISOString(),
        requires_recovery_check: true,
        log: logFile,
      };
      save(file, interruptedTask);
      const commitResult = commitRunnerState(file, task.id, "interrupted (emergency stop)");
      if (!commitResult.ok) console.error(`WARNING: could not commit ${task.id}'s interrupted state: ${commitResult.reason}`);
      transition("emergency_stop_command", { reason: "emergency stop during a running stage", taskId: task.id });
      console.error(`INTERRUPTED ${task.id} -- emergency stop requested mid-session; recovery check required before this task runs again`);
      await snapshotCodexUsageIfNeeded(interruptedTask, resolvedExecutor);
      return false;
    }

    const outcome = classifySessionOutcome(output);
    const handoffAfter = readHandoff(task.id);
    const sessionRecord = {
      stage: stageIndex + 1,
      model: model || "default",
      started_at: new Date(stageStart).toISOString(),
      duration_ms: durationMs,
      prompt_chars: sizeInfo.chars,
      prompt_approx_tokens: sizeInfo.approxTokens,
      handoff_words: handoffAfter ? handoffWordCount(handoffAfter) : null,
      outcome: outcome.outcome,
      log: logFile,
    };
    sessions.push(sessionRecord);

    const current = load(file); // whatever Claude itself wrote to status/result during the session
    current.result = { ...(current.result || {}), sessions };
    const clean = run("git", ["status", "--porcelain"]).stdout.trim() === "";
    const syncCheck = current.release === "automatic" ? verifyFinalSyncEvidence(current) : { ok: true };

    const decision = decideNextAction({
      sessionOutcome: outcome,
      taskStatus: current.status,
      workingTreeClean: clean,
      finalSyncOk: syncCheck,
      processExitedZero: output.status === 0,
      stageIndex,
      maxStages,
      handoffAfterStage: handoffAfter,
    });

    if (decision.action === "wait_for_limit") {
      current.status = "waiting_for_limit";
      current.result.retry_after = decision.retryAfter;
      current.result.rate_limit = decision.rateLimit;
      save(file, current);
      const commitResult = commitRunnerState(file, task.id, "waiting_for_limit");
      if (!commitResult.ok) console.error(`WARNING: could not commit ${task.id}'s waiting_for_limit state: ${commitResult.reason} -- next preflight() may see a dirty tree`);
      console.log(`WAITING_FOR_LIMIT ${task.id} -- retry after ${decision.retryAfter}`);
      await snapshotCodexUsageIfNeeded(current, resolvedExecutor);
      return true; // a legitimate pause, not a failure
    }
    if (decision.action === "auth_required") {
      // Never auto-retried like waiting_for_limit -- an auth/subscription
      // failure does not self-heal on a timer, and nextTask() naturally
      // excludes any status it doesn't explicitly allow (ready, or
      // waiting_for_limit past retry_after), so this task simply will not
      // be picked up again until a human fixes access and moves it back.
      current.status = "waiting_for_auth";
      current.result.auth_error = decision.fatal;
      current.result.finished_at = new Date().toISOString();
      save(file, current);
      const commitResult = commitRunnerState(file, task.id, "waiting_for_auth");
      if (!commitResult.ok) console.error(`WARNING: could not commit ${task.id}'s waiting_for_auth state: ${commitResult.reason} -- next preflight() may see a dirty tree`);
      console.error(`AUTHENTICATION_REQUIRED ${task.id} -- ${decision.fatal.category}: ${decision.fatal.matched} -- queue stopped, needs human action`);
      await snapshotCodexUsageIfNeeded(current, resolvedExecutor);
      return false; // a hard stop: every other queued task would hit the same wall
    }
    if (decision.action === "done") {
      save(file, current);
      const commitResult = commitRunnerState(file, task.id, "done bookkeeping");
      if (!commitResult.ok) console.error(`WARNING: could not commit ${task.id}'s done bookkeeping: ${commitResult.reason} -- next preflight() may see a dirty tree`);
      console.log(`DONE ${task.id} (${sessions.length} session(s))`);
      await snapshotCodexUsageIfNeeded(current, resolvedExecutor);
      return true;
    }
    if (decision.action === "blocked") {
      save(file, current);
      const commitResult = commitRunnerState(file, task.id, "blocked");
      if (!commitResult.ok) console.error(`WARNING: could not commit ${task.id}'s blocked state: ${commitResult.reason} -- next preflight() may see a dirty tree`);
      console.log(`BLOCKED ${task.id} — awaiting a real Owner decision (not a failure)`);
      await snapshotCodexUsageIfNeeded(current, resolvedExecutor);
      return true;
    }
    if (decision.action === "continue_next_stage") {
      save(file, current);
      const commitResult = commitRunnerState(file, task.id, `stage ${stageIndex + 1} handoff bookkeeping`);
      if (!commitResult.ok) console.error(`WARNING: could not commit ${task.id}'s stage bookkeeping: ${commitResult.reason} -- next stage's git-state block may show it as dirty`);
      console.log(`STAGE ${task.id} #${stageIndex + 1} ran out of time -- continuing with its handoff in a new session`);
      await snapshotCodexUsageIfNeeded(current, resolvedExecutor);
      stageIndex += 1;
      continue;
    }
    // decision.action === "fail"
    current.status = "failed";
    current.result = { ...current.result, runner_error: decision.reason, log: logFile, finished_at: new Date().toISOString() };
    save(file, current);
    {
      const commitResult = commitRunnerState(file, task.id, "failed");
      if (!commitResult.ok) console.error(`WARNING: could not commit ${task.id}'s failed state: ${commitResult.reason} -- next preflight() may see a dirty tree`);
    }
    console.error(`FAILED ${task.id} — queue stopped`);
    await snapshotCodexUsageIfNeeded(current, resolvedExecutor);
    return false;
  }

  // Exhausted the declared/auto stage budget without reaching a terminal
  // decision above -- treated as a failure, never an infinite retry loop.
  const current = load(file);
  current.status = "failed";
  current.result = { ...(current.result || {}), sessions, runner_error: `exhausted ${maxStages} stage(s) without reaching done/blocked`, finished_at: new Date().toISOString() };
  save(file, current);
  {
    const commitResult = commitRunnerState(file, task.id, "failed (stage budget exhausted)");
    if (!commitResult.ok) console.error(`WARNING: could not commit ${task.id}'s failed state: ${commitResult.reason} -- next preflight() may see a dirty tree`);
  }
  console.error(`FAILED ${task.id} — queue stopped (stage budget exhausted)`);
  await snapshotCodexUsageIfNeeded(current, resolvedExecutor);
  return false;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function main() {
  const args = process.argv.slice(2);
  const watch = args.includes("--watch"), dry = args.includes("--dry-run");
  const value = (name, fallback) => { const i = args.indexOf(name); return i >= 0 ? Number(args[i + 1]) : fallback; };
  const interval = value("--interval", 60), maxTurns = value("--max-turns", 80), timeout = value("--timeout-minutes", 90);
  try { fs.writeFileSync(LOCK, JSON.stringify({ pid: process.pid, created_at: new Date().toISOString() }), { flag: "wx" }); }
  catch { console.error(`STOP: runner lock exists: ${LOCK}`); return 1; }
  transition("start", { reason: dry ? "dry-run preview" : watch ? "watch mode" : "single-shot" });
  try {
    while (true) {
      // Blocks here regardless of WHERE the pause was actioned -- between
      // tasks (below) or between stages inside execute() -- so a paused
      // runner never looks for a next task while paused.
      while (runnerState === "paused") {
        await sleep(2000);
        const pendingWhilePaused = readPendingCommand();
        if (pendingWhilePaused && pendingWhilePaused.command === "resume") {
          clearPendingCommand();
          transition("resume_command", { reason: "resume requested" });
        } else if (pendingWhilePaused && pendingWhilePaused.command === "emergency_stop") {
          clearPendingCommand();
          transition("emergency_stop_command", { reason: "emergency stop while paused" });
          return 0;
        }
      }
      if (runnerState === "stopped") return 0; // finalized by a stop_after_stage/emergency_stop already actioned

      // Safe point: between tasks. The only place a command is honored
      // when nothing is currently running.
      const pending = readPendingCommand();
      if (pending && commandAllowedInState(pending.command, runnerState)) {
        if (pending.command === "emergency_stop") {
          clearPendingCommand();
          transition("emergency_stop_command", { reason: "emergency stop requested between tasks" });
          return 0;
        }
        if (pending.command === "stop_after_stage") {
          clearPendingCommand();
          transition("stop_after_stage_command", { reason: "stop requested between tasks" });
          transition("safe_point_reached", { reason: "no task in flight" });
          return 0;
        }
        if (pending.command === "pause") {
          clearPendingCommand();
          transition("pause_command", { reason: "pause requested between tasks" });
          transition("safe_point_reached", { reason: "no task in flight" });
          continue; // loops back to the paused-wait block above
        }
      }

      const selected = nextTask();
      if (!selected) {
        transition("no_ready_tasks");
        if (!watch) { console.log("No ready tasks."); transition("queue_exhausted", { reason: "no ready tasks, single-shot mode" }); return 0; }
        await sleep(interval * 1000);
        continue;
      }
      if (dry) { console.log(`NEXT ${selected.task.id}: ${selected.task.title}`); return 0; }
      transition("task_claimed", { taskId: selected.task.id });
      const ok = await execute(selected, maxTurns, timeout);
      if (!ok) { transition("task_failed", { taskId: selected.task.id, reason: "execute() returned false -- see the task's own result.runner_error" }); return 1; }
      transition("safe_point_reached_idle", { taskId: selected.task.id }); // a no-op if execute() already moved us to paused/stopped internally
      if (!watch) { transition("queue_exhausted", { reason: "single-shot mode, one task processed" }); return 0; }
    }
  } finally { if (fs.existsSync(LOCK)) fs.unlinkSync(LOCK); }
}

module.exports = {
  run, runClaude, killProcessTree, listProcessParents, load, save, preflight, nextTask, listTasks, execute, main,
  buildStagePrompt, gitStateBlockNow, handoffPathFor, readHandoff, commitRunnerState,
  readPendingCommand, clearPendingCommand, appendEvent, writeRunnerState, transition,
  readUsageTracker, writeUsageTracker, recordSessionUsage,
  snapshotCodexUsageIfNeeded, readLatestCodexUsageSnapshot,
  getRunnerState: () => runnerState,
  PRIORITY_RANK,
  CLAUDE, LOCK, LOG_DIR, HANDOFF_DIR, QUEUE, ROOT,
  CONTROL_DIR, COMMANDS_FILE, RUNNER_STATE_FILE, EVENTS_FILE, USAGE_FILE, CODEX_USAGE_LOG_FILE,
};

if (require.main === module) {
  main().then((code) => { process.exitCode = code; });
}
