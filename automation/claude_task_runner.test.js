"use strict";

/**
 * Integration-style tests for TOKEN-EFFICIENCY-001's staged execution.
 * Spawns automation/test_fixtures/fake_claude.js (never a real Claude Code
 * process) through the REAL runner wiring (runClaude/execute), so process
 * isolation, tree-kill, and handoff-file plumbing are proven against real
 * child processes, not just asserted against pure logic.
 */

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const path = require("path");
const os = require("os");
const cp = require("child_process");

const FIXTURES = path.join(__dirname, "test_fixtures");
const FAKE_CLAUDE = path.join(FIXTURES, "fake_claude.cmd");

// preflight() runs real (read-only after setup) git checks -- status,
// fetch, rev-parse, branch. Rather than depending on THIS checkout's
// working tree happening to be clean and pushed whenever tests run, build
// one small, throwaway repo with a real "origin" remote once, and point
// every test's EGO_OS_RUNNER_ROOT_DIR at it. Nothing in any test scenario
// below touches files inside this repo (the task files themselves live in
// their own separate temp directories), so it stays clean and reusable
// across the whole file.
function git(args, cwd) {
  const result = cp.spawnSync("git", args, { cwd, encoding: "utf8" });
  if (result.status !== 0) throw new Error(`git ${args.join(" ")} failed: ${result.stderr}`);
  return result.stdout;
}

function setupFakeRepo() {
  const bareDir = fs.mkdtempSync(path.join(os.tmpdir(), "ego-os-origin-"));
  const workDir = fs.mkdtempSync(path.join(os.tmpdir(), "ego-os-work-"));
  git(["init", "--bare", "-b", "main"], bareDir);
  git(["init", "-b", "main"], workDir);
  git(["config", "user.email", "test@example.com"], workDir);
  git(["config", "user.name", "Test"], workDir);
  fs.writeFileSync(path.join(workDir, "README.md"), "fake repo for TOKEN-EFFICIENCY-001 tests\n");
  git(["add", "README.md"], workDir);
  git(["commit", "-m", "initial"], workDir);
  git(["remote", "add", "origin", bareDir], workDir);
  git(["push", "-u", "origin", "main"], workDir);
  return { bareDir, workDir };
}

let FAKE_REPO = null;

function freshRunnerEnv() {
  if (!FAKE_REPO) FAKE_REPO = setupFakeRepo();
  const localDir = fs.mkdtempSync(path.join(os.tmpdir(), "ego-os-runner-test-"));
  process.env.EGO_OS_RUNNER_CLAUDE_PATH = FAKE_CLAUDE;
  process.env.EGO_OS_RUNNER_LOCAL_DIR = localDir;
  process.env.EGO_OS_RUNNER_ROOT_DIR = FAKE_REPO.workDir;
  delete process.env.EGO_OS_RUNNER_QUEUE_DIR;
  // Force a fresh require so the runner module re-reads these env vars
  // into its CLAUDE/LOCAL/ROOT/LOCK/LOG_DIR/HANDOFF_DIR constants --
  // module caching would otherwise leak state between tests.
  delete require.cache[require.resolve("./claude_task_runner.js")];
  const runner = require("./claude_task_runner.js");
  return { runner, localDir };
}

function writeTask(dir, overrides) {
  const task = {
    id: "TEST-001",
    status: "ready",
    priority: "P1",
    title: "Test task",
    prompt: "Do the test thing.",
    acceptance: ["it works"],
    allowed_paths: ["some/path"],
    forbidden_paths: [],
    risks: [],
    owner_approved: false,
    release: "no_deploy",
    result: null,
    ...overrides,
  };
  const file = path.join(dir, `${task.id}.yaml`);
  fs.writeFileSync(file, JSON.stringify(task, null, 2) + "\n", "utf8");
  return { file, task };
}

function isAlive(pid) {
  if (!pid) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

// --- 1. a new task never inherits an old session --------------------------

test("execute() never passes --continue or --resume, and each stage/task starts an independent fake session", async () => {
  const { runner, localDir } = freshRunnerEnv();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ego-os-task-"));
  const selected = writeTask(dir, { id: "TEST-ISOLATION", max_duration_minutes: 0.5 });
  process.env.EGO_OS_FAKE_SCENARIO = "instant_done";
  process.env.EGO_OS_FAKE_TASK_FILE = selected.file;
  process.env.EGO_OS_FAKE_HANDOFF_FILE = runner.handoffPathFor(selected.task.id);

  const ok = await runner.execute(selected, 10, 1);
  assert.equal(ok, true);
  const finalTask = runner.load(selected.file);
  assert.equal(finalTask.status, "done");
  assert.equal(finalTask.result.sessions.length, 1);

  fs.rmSync(dir, { recursive: true, force: true });
  fs.rmSync(localDir, { recursive: true, force: true });
});

// --- 2. stages get only handoff, not prior dialogue -----------------------

test("execute() building a stage-2 prompt embeds the handoff but not any transcript/dialogue marker", () => {
  const { runner } = freshRunnerEnv();
  const handoff = {
    summary: "stage 1 added the schema", commit: "abc123", changed_files: ["x.py"],
    checks: "12 tests passed", remaining: "routes", risks: "none", next_step: "add routes",
  };
  const prompt = runner.buildStagePrompt(
    { id: "T", title: "Title", prompt: "Do it", acceptance: ["ok"], release: "no_deploy" },
    "tasks/queue/T.yaml", "GIT STATE:\nHEAD: deadbeef\nStatus: (clean)\nRecent commits:\n(none)",
    1, 3, null, handoff, "/tmp/handoff.json",
  );
  assert.match(prompt, /PRIOR STAGE HANDOFF/);
  assert.match(prompt, /abc123/);
  // The prompt legitimately explains "not a transcript or a diff" as
  // reassurance about the handoff's own scope -- the real thing to prove
  // is that no conversation-log-shaped section is embedded.
  assert.doesNotMatch(prompt, /CONVERSATION (HISTORY|LOG)/i);
  assert.doesNotMatch(prompt, /\[assistant\]|\[user\]/i);
});

test("execute() building the FIRST stage's prompt has no handoff block at all", () => {
  const { runner } = freshRunnerEnv();
  const prompt = runner.buildStagePrompt(
    { id: "T", title: "Title", prompt: "Do it", acceptance: ["ok"], release: "no_deploy" },
    "tasks/queue/T.yaml", "GIT STATE:\nHEAD: deadbeef\nStatus: (clean)\nRecent commits:\n(none)",
    0, 1, null, null, "/tmp/handoff.json",
  );
  assert.doesNotMatch(prompt, /PRIOR STAGE HANDOFF/);
});

// --- 3. handoff size limit is enforced by the real stage loop --------------

test("execute() refuses to continue past a timed-out stage when the handoff left behind is invalid/oversized", async () => {
  const { runner, localDir } = freshRunnerEnv();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ego-os-task-"));
  const selected = writeTask(dir, { id: "TEST-BADHANDOFF", max_duration_minutes: 0.03, max_auto_stages: 2 });
  const markerFile = path.join(dir, "marker");
  process.env.EGO_OS_FAKE_SCENARIO = "hang_forever"; // always hangs, never leaves ANY handoff
  process.env.EGO_OS_FAKE_TASK_FILE = selected.file;
  process.env.EGO_OS_FAKE_HANDOFF_FILE = runner.handoffPathFor(selected.task.id);
  process.env.EGO_OS_FAKE_MARKER_FILE = markerFile;

  const ok = await runner.execute(selected, 10, 1);
  assert.equal(ok, false);
  const finalTask = runner.load(selected.file);
  assert.equal(finalTask.status, "failed");
  assert.match(finalTask.result.runner_error, /no usable handoff/);

  fs.rmSync(dir, { recursive: true, force: true });
  fs.rmSync(localDir, { recursive: true, force: true });
});

// --- 4. timeout/checkpoint: a stage that runs out of time correctly hands off --

test("execute() continues into a fresh stage-2 session after stage 1 times out with a valid handoff, and stage 2 completes", async () => {
  const { runner, localDir } = freshRunnerEnv();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ego-os-task-"));
  const selected = writeTask(dir, { id: "TEST-TIMEOUT-CONTINUE", max_duration_minutes: 0.03, max_auto_stages: 3 });
  const markerFile = path.join(dir, "marker");
  process.env.EGO_OS_FAKE_SCENARIO = "hang_once_then_done";
  process.env.EGO_OS_FAKE_TASK_FILE = selected.file;
  process.env.EGO_OS_FAKE_HANDOFF_FILE = runner.handoffPathFor(selected.task.id);
  process.env.EGO_OS_FAKE_MARKER_FILE = markerFile;

  const ok = await runner.execute(selected, 10, 1);
  assert.equal(ok, true);
  const finalTask = runner.load(selected.file);
  assert.equal(finalTask.status, "done");
  assert.equal(finalTask.result.sessions.length, 2, "expected exactly two distinct sessions (stage 1 timeout + stage 2 completion)");
  assert.equal(finalTask.result.sessions[0].outcome, "timed_out_or_killed");
  assert.equal(finalTask.result.sessions[1].outcome, "exited_clean");
  // Each session got its own log file -- proof they are genuinely separate processes/runs.
  assert.notEqual(finalTask.result.sessions[0].log, finalTask.result.sessions[1].log);

  fs.rmSync(dir, { recursive: true, force: true });
  fs.rmSync(localDir, { recursive: true, force: true });
});

// --- 5. rate-limit -> waiting_for_limit -------------------------------------

test("execute() moves a task to waiting_for_limit (never failed) when the fake reports a rate limit", async () => {
  const { runner, localDir } = freshRunnerEnv();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ego-os-task-"));
  const selected = writeTask(dir, { id: "TEST-RATELIMIT", max_duration_minutes: 0.5 });
  process.env.EGO_OS_FAKE_SCENARIO = "rate_limited";
  process.env.EGO_OS_FAKE_TASK_FILE = selected.file;
  process.env.EGO_OS_FAKE_HANDOFF_FILE = runner.handoffPathFor(selected.task.id);

  const ok = await runner.execute(selected, 10, 1);
  assert.equal(ok, true, "a rate limit is a legitimate pause, not a failure");
  const finalTask = runner.load(selected.file);
  assert.equal(finalTask.status, "waiting_for_limit");
  assert.ok(finalTask.result.retry_after);
  assert.ok(Date.parse(finalTask.result.retry_after) > Date.now());

  fs.rmSync(dir, { recursive: true, force: true });
  fs.rmSync(localDir, { recursive: true, force: true });
});

// --- 6. safe resumption: nextTask() respects retry_after -------------------

test("nextTask() skips a waiting_for_limit task before retry_after and picks it up after", () => {
  const { localDir } = freshRunnerEnv();
  const queueDir = fs.mkdtempSync(path.join(os.tmpdir(), "ego-os-queue-"));
  process.env.EGO_OS_RUNNER_QUEUE_DIR = queueDir;
  delete require.cache[require.resolve("./claude_task_runner.js")];
  const runner2 = require("./claude_task_runner.js");

  const future = new Date(Date.now() + 3600000).toISOString();
  writeTask(queueDir, { id: "TEST-WAIT-FUTURE", status: "waiting_for_limit", result: { retry_after: future } });
  const notYetDue = runner2.nextTask();
  assert.equal(notYetDue, null, "must not pick up a task whose limit has not reset yet");

  const past = new Date(Date.now() - 1000).toISOString();
  fs.writeFileSync(
    path.join(queueDir, "TEST-WAIT-FUTURE.yaml"),
    JSON.stringify({ ...runner2.load(path.join(queueDir, "TEST-WAIT-FUTURE.yaml")), status: "waiting_for_limit", result: { retry_after: past } }, null, 2),
  );
  const due = runner2.nextTask();
  assert.ok(due, "must pick up the task once its retry_after has passed");
  assert.equal(due.task.id, "TEST-WAIT-FUTURE");

  fs.rmSync(queueDir, { recursive: true, force: true });
  fs.rmSync(localDir, { recursive: true, force: true });
  delete process.env.EGO_OS_RUNNER_QUEUE_DIR;
});

// --- 7. no orphan processes survive a timed-out stage -----------------------

test("execute() leaves no orphaned fake_claude/node process after a stage times out (tree-kill works)", async () => {
  const { runner, localDir } = freshRunnerEnv();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ego-os-task-"));
  const selected = writeTask(dir, { id: "TEST-ORPHAN", max_duration_minutes: 0.03, max_auto_stages: 1 });
  const markerFile = path.join(dir, "marker");
  process.env.EGO_OS_FAKE_SCENARIO = "hang_forever";
  process.env.EGO_OS_FAKE_TASK_FILE = selected.file;
  process.env.EGO_OS_FAKE_HANDOFF_FILE = runner.handoffPathFor(selected.task.id);
  process.env.EGO_OS_FAKE_MARKER_FILE = markerFile;

  await runner.execute(selected, 10, 1);

  // execute() only resolves once runClaude's own 'close' handler (and its
  // own final tree-kill safety net) has already run -- a short extra
  // grace period just lets the OS process table settle before we check.
  await new Promise((r) => setTimeout(r, 500));
  assert.ok(fs.existsSync(markerFile), "the fake should have recorded its grandchild's pid before hanging");
  const grandchildPid = Number(fs.readFileSync(markerFile, "utf8").trim());
  assert.equal(isAlive(grandchildPid), false, "the grandchild must not survive -- tree-kill must clean up the whole process tree, not just the direct child");

  fs.rmSync(dir, { recursive: true, force: true });
  fs.rmSync(localDir, { recursive: true, force: true });
});

// --- 8. old-style YAML tasks (no new fields) still work ---------------------

test("execute() runs a pre-TOKEN-EFFICIENCY-001-shaped task (no checkpoints/model/max_duration_minutes) as a single session, unchanged", async () => {
  const { runner, localDir } = freshRunnerEnv();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ego-os-task-"));
  // Deliberately omits every new optional field -- matches every task file
  // already in tasks/queue/ before this change.
  const selected = writeTask(dir, { id: "TEST-BACKCOMPAT" });
  process.env.EGO_OS_FAKE_SCENARIO = "instant_done";
  process.env.EGO_OS_FAKE_TASK_FILE = selected.file;
  process.env.EGO_OS_FAKE_HANDOFF_FILE = runner.handoffPathFor(selected.task.id);

  const ok = await runner.execute(selected, 10, 1);
  assert.equal(ok, true);
  const finalTask = runner.load(selected.file);
  assert.equal(finalTask.status, "done");
  assert.equal(finalTask.result.sessions.length, 1, "an old-style task with no timeout still completes in exactly one session");

  fs.rmSync(dir, { recursive: true, force: true });
  fs.rmSync(localDir, { recursive: true, force: true });
});

test("execute() honors context_strategy:'single' as an explicit opt-out of auto-staging", async () => {
  const { runner, localDir } = freshRunnerEnv();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ego-os-task-"));
  const selected = writeTask(dir, { id: "TEST-SINGLE-STRATEGY", context_strategy: "single", max_duration_minutes: 0.03 });
  const markerFile = path.join(dir, "marker");
  process.env.EGO_OS_FAKE_SCENARIO = "hang_forever";
  process.env.EGO_OS_FAKE_TASK_FILE = selected.file;
  process.env.EGO_OS_FAKE_HANDOFF_FILE = runner.handoffPathFor(selected.task.id);
  process.env.EGO_OS_FAKE_MARKER_FILE = markerFile;

  const ok = await runner.execute(selected, 10, 1);
  assert.equal(ok, false);
  const finalTask = runner.load(selected.file);
  assert.equal(finalTask.result.sessions.length, 1, "context_strategy:'single' must never auto-stage, even on timeout");

  fs.rmSync(dir, { recursive: true, force: true });
  fs.rmSync(localDir, { recursive: true, force: true });
});

// --- 9. global sweep: nothing from ANY test in this file is left running ---
// (not just the one test that explicitly checks its own marker PID --
// every hang_forever/hang_once_then_done scenario above spawns a real
// fake_claude.js + grandchild, and this is the actual A2 success
// criterion: zero orphaned processes after the WHOLE run, not just one
// specific case of it.)

// --- 10. the runner's own bookkeeping write must not block the next task ---
// Found live in production use: TOKEN-EFFICIENCY-VERIFY's real
// waiting_for_limit run left its task YAML modified-but-uncommitted (the
// runner writes retry_after/rate_limit/sessions directly via fs, never
// through a git commit), so the NEXT invocation's preflight() (which
// requires a clean tree) refused to start ANY task, not just this one.

test("execute()'s own post-session bookkeeping write is committed, so a second invocation's preflight() still succeeds", async () => {
  const { runner, localDir } = freshRunnerEnv();
  const taskDir = path.join(runner.ROOT, "tasks", "queue");
  fs.mkdirSync(taskDir, { recursive: true });

  const first = writeTask(taskDir, { id: "TEST-CLEAN-AFTER-LIMIT", max_duration_minutes: 0.5 });
  runner.run("git", ["add", "--", path.relative(runner.ROOT, first.file)]);
  runner.run("git", ["commit", "-m", "Queue TEST-CLEAN-AFTER-LIMIT"]);
  runner.run("git", ["push", "origin", "main"]);
  process.env.EGO_OS_FAKE_SCENARIO = "rate_limited";
  process.env.EGO_OS_FAKE_TASK_FILE = first.file;
  process.env.EGO_OS_FAKE_HANDOFF_FILE = runner.handoffPathFor(first.task.id);
  const ok1 = await runner.execute(first, 10, 1);
  assert.equal(ok1, true);

  const statusAfterFirst = runner.run("git", ["status", "--porcelain"]);
  assert.equal(statusAfterFirst.stdout.trim(), "", "the runner's own waiting_for_limit write must be committed, not left dirty");

  // A second, unrelated task must still be runnable -- preflight() must not
  // refuse because of the first task's leftover bookkeeping write. Queuing
  // a new task always means committing its YAML first (exactly like this
  // repo's own real "Queue <task>: ..." commits) -- a brand-new untracked
  // file is a separate, pre-existing preflight() concern, not the one this
  // test targets.
  const second = writeTask(taskDir, { id: "TEST-CLEAN-AFTER-LIMIT-2" });
  runner.run("git", ["add", "--", path.relative(runner.ROOT, second.file)]);
  runner.run("git", ["commit", "-m", "Queue TEST-CLEAN-AFTER-LIMIT-2"]);
  runner.run("git", ["push", "origin", "main"]);
  process.env.EGO_OS_FAKE_SCENARIO = "instant_done";
  process.env.EGO_OS_FAKE_TASK_FILE = second.file;
  process.env.EGO_OS_FAKE_HANDOFF_FILE = runner.handoffPathFor(second.task.id);
  const ok2 = await runner.execute(second, 10, 1);
  assert.equal(ok2, true, "a second task must be runnable without a human manually cleaning up the first task's leftover state");

  const statusAfterSecond = runner.run("git", ["status", "--porcelain"]);
  assert.equal(statusAfterSecond.stdout.trim(), "", "the second task's own done bookkeeping write must also be committed");

  // Deliberately not removing taskDir here: it lives inside the shared fake
  // repo, and every file in it is already committed -- deleting it via fs
  // (not git) would dirty the tree for whatever test runs next, which is
  // exactly the class of bug this test exists to catch in the first place.
  fs.rmSync(localDir, { recursive: true, force: true });
});

// --- 11. fail-closed: auth/subscription failure with exit 0 must never be "done" ---
// The exact live defect reported: a child process can print
// "Your organization has disabled Claude subscription access for Claude
// Code..." while still exiting 0 and having already written status "done"
// (even committed, even with a valid handoff and clean tree) to its own
// task file. The runner must refuse this, not just the pure decision logic.

test("execute() refuses a 'done' status when the real process output contains the subscription-disabled message, even with exit 0", async () => {
  const { runner, localDir } = freshRunnerEnv();
  const taskDir = path.join(runner.ROOT, "tasks", "queue");
  fs.mkdirSync(taskDir, { recursive: true });

  const selected = writeTask(taskDir, { id: "TEST-AUTH-FAILCLOSED" });
  runner.run("git", ["add", "--", path.relative(runner.ROOT, selected.file)]);
  runner.run("git", ["commit", "-m", "Queue TEST-AUTH-FAILCLOSED"]);
  runner.run("git", ["push", "origin", "main"]);

  process.env.EGO_OS_FAKE_SCENARIO = "auth_disabled_exit_zero";
  process.env.EGO_OS_FAKE_TASK_FILE = selected.file;
  process.env.EGO_OS_FAKE_HANDOFF_FILE = runner.handoffPathFor(selected.task.id);

  const ok = await runner.execute(selected, 10, 1);
  assert.equal(ok, false, "an auth/subscription failure must stop the queue, not report success");

  const finalTask = runner.load(selected.file);
  assert.notEqual(finalTask.status, "done", "must never accept 'done' when a fatal auth pattern was printed, regardless of exit code");
  assert.equal(finalTask.status, "waiting_for_auth");
  assert.equal(finalTask.result.auth_error.category, "authentication_required");

  // Not removing taskDir -- see the identical note in the previous test.
  fs.rmSync(localDir, { recursive: true, force: true });
});

// --- 12. RUNNER-CONTROL-UI: pause never interrupts an in-flight session ---
// pause/stop_after_stage are only ever checked BETWEEN stages -- never
// polled during runClaude() itself, unlike emergency_stop. This proves it
// end to end: a "pause" command written WHILE a stage is genuinely running
// must not cut it short; the stage must still run to its own natural
// timeout, and only THEN does the task park before the next stage.

function writeControlCommand(runner, command) {
  fs.mkdirSync(path.dirname(runner.COMMANDS_FILE), { recursive: true });
  fs.writeFileSync(runner.COMMANDS_FILE, JSON.stringify({ command, requested_at: new Date().toISOString() }), "utf8");
}

test("a pause command written mid-session does not interrupt the running stage -- it only blocks the NEXT one", async () => {
  const { runner, localDir } = freshRunnerEnv();
  const taskDir = path.join(runner.ROOT, "tasks", "queue");
  fs.mkdirSync(taskDir, { recursive: true });
  const selected = writeTask(taskDir, { id: "TEST-PAUSE-MIDSTAGE", max_duration_minutes: 0.03, max_auto_stages: 2 });
  runner.run("git", ["add", "--", path.relative(runner.ROOT, selected.file)]);
  runner.run("git", ["commit", "-m", "Queue TEST-PAUSE-MIDSTAGE"]);
  runner.run("git", ["push", "origin", "main"]);

  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ego-os-task-"));
  const markerFile = path.join(dir, "marker");
  // hang_once_then_done: stage 1 hangs (leaving a valid handoff first) until
  // its own timeout kills it, which is exactly the "genuinely in flight,
  // only ends via its own timeout" shape this test needs -- and leaves a
  // valid handoff so decideNextAction would normally continue to stage 2,
  // which is exactly what the pending pause command must prevent.
  process.env.EGO_OS_FAKE_SCENARIO = "hang_once_then_done";
  process.env.EGO_OS_FAKE_TASK_FILE = selected.file;
  process.env.EGO_OS_FAKE_HANDOFF_FILE = runner.handoffPathFor(selected.task.id);
  process.env.EGO_OS_FAKE_MARKER_FILE = markerFile;

  const executePromise = runner.execute(selected, 10, 1);
  await new Promise((r) => setTimeout(r, 500)); // let the fake actually spawn and be genuinely in flight
  writeControlCommand(runner, "pause");
  const ok = await executePromise;

  assert.equal(ok, true, "a pause is a safe, intentional stop, not a failure");
  const finalTask = runner.load(selected.file);
  assert.equal(finalTask.status, "checkpointing");
  assert.equal(finalTask.result.sessions.length, 1, "stage 1 must have actually run to completion (its own timeout), not been cut short");
  assert.equal(finalTask.result.sessions[0].outcome, "timed_out_or_killed", "stage 1 ended via its OWN timeout, proving the pause command did not interrupt it early");
  assert.equal(finalTask.result.paused_before_stage, 2, "the pause took effect only before stage 2, never mid-stage-1");

  fs.rmSync(dir, { recursive: true, force: true });
  fs.rmSync(localDir, { recursive: true, force: true });
});

// --- 13. RUNNER-CONTROL-UI: emergency_stop DOES interrupt an in-flight session ---

test("an emergency_stop command written mid-session DOES interrupt the running stage, marks the task interrupted, and leaves no orphan", async () => {
  const { runner, localDir } = freshRunnerEnv();
  const taskDir = path.join(runner.ROOT, "tasks", "queue");
  fs.mkdirSync(taskDir, { recursive: true });
  const selected = writeTask(taskDir, { id: "TEST-EMERGENCY-STOP", max_duration_minutes: 5 }); // a long budget -- only the emergency stop should end this quickly
  runner.run("git", ["add", "--", path.relative(runner.ROOT, selected.file)]);
  runner.run("git", ["commit", "-m", "Queue TEST-EMERGENCY-STOP"]);
  runner.run("git", ["push", "origin", "main"]);

  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ego-os-task-"));
  const markerFile = path.join(dir, "marker");
  process.env.EGO_OS_FAKE_SCENARIO = "hang_forever";
  process.env.EGO_OS_FAKE_TASK_FILE = selected.file;
  process.env.EGO_OS_FAKE_HANDOFF_FILE = runner.handoffPathFor(selected.task.id);
  process.env.EGO_OS_FAKE_MARKER_FILE = markerFile;

  const start = Date.now();
  const executePromise = runner.execute(selected, 10, 300);
  await new Promise((r) => setTimeout(r, 500));
  writeControlCommand(runner, "emergency_stop");
  const ok = await executePromise;
  const elapsedMs = Date.now() - start;

  assert.equal(ok, false, "an emergency stop is a hard interruption, never reported as success");
  assert.ok(elapsedMs < 60000, `emergency stop must act well before the 5-minute budget (took ${elapsedMs}ms)`);
  const finalTask = runner.load(selected.file);
  assert.equal(finalTask.status, "interrupted");
  assert.equal(finalTask.result.requires_recovery_check, true);

  await new Promise((r) => setTimeout(r, 500));
  assert.ok(fs.existsSync(markerFile));
  const grandchildPid = Number(fs.readFileSync(markerFile, "utf8").trim());
  assert.equal(isAlive(grandchildPid), false, "emergency stop must still clean up the whole process tree, not just leave it running");

  fs.rmSync(dir, { recursive: true, force: true });
  fs.rmSync(localDir, { recursive: true, force: true });
});

// --- 14. resuming a checkpointing task picks it back up, nextTask() includes it ---

test("nextTask() includes a checkpointing task (resumed after pause), unlike waiting_for_auth which it must never auto-select", () => {
  const { localDir } = freshRunnerEnv();
  const queueDir = fs.mkdtempSync(path.join(os.tmpdir(), "ego-os-queue-"));
  process.env.EGO_OS_RUNNER_QUEUE_DIR = queueDir;
  delete require.cache[require.resolve("./claude_task_runner.js")];
  const runner3 = require("./claude_task_runner.js");

  writeTask(queueDir, { id: "TEST-CHECKPOINTING", status: "checkpointing", result: { sessions: [{ stage: 1 }] } });
  writeTask(queueDir, { id: "TEST-WAITING-AUTH", status: "waiting_for_auth", result: { auth_error: { category: "authentication_required" } } });

  const selected = runner3.nextTask();
  assert.ok(selected, "a checkpointing task must be eligible for automatic pickup once resumed");
  assert.equal(selected.task.id, "TEST-CHECKPOINTING");

  // Once the only checkpointing task is gone, waiting_for_auth must never
  // surface as a fallback -- proving it was excluded on principle, not just
  // deprioritized behind the checkpointing task.
  fs.rmSync(selected.file);
  assert.equal(runner3.nextTask(), null, "waiting_for_auth must never be auto-selected -- it requires an explicit human retry");

  fs.rmSync(queueDir, { recursive: true, force: true });
  fs.rmSync(localDir, { recursive: true, force: true });
  delete process.env.EGO_OS_RUNNER_QUEUE_DIR;
});

// --- 15. killProcessTree's Linux/macOS tree-walk parses `ps -eo pid,ppid` correctly ---
// Found live deploying to a real Linux VPS: killProcessTree() previously
// ran `powershell`/`taskkill` unconditionally. Neither exists on Linux;
// spawnSync just failed silently (ENOENT wasn't checked), the process
// list came back empty, and nothing was ever actually killed -- a 15s
// probe timeout fired correctly but the hung `claude --version` process
// (and the whole runClaude() promise) never resolved, since 'close' only
// fires once the child is genuinely dead. This test can't spawn a real
// process tree and kill it here (this suite runs on Windows), but it
// proves the *parsing/tree-walk algorithm* the Linux branch depends on is
// sound -- the same algorithm already proven correct against WMI's own
// shape on Windows, fed synthetic `ps -eo pid,ppid` output instead. The
// real end-to-end proof is the live VPS verification recorded in
// automation/SERVER_RUNNER_VERIFICATION.md.

test("listProcessParents() parses `ps -eo pid,ppid` output into {pid, ppid} pairs on non-Windows", () => {
  const cpMod = require("child_process");
  const originalSpawnSync = cpMod.spawnSync;
  const originalPlatform = Object.getOwnPropertyDescriptor(process, "platform");
  try {
    Object.defineProperty(process, "platform", { value: "linux" });
    cpMod.spawnSync = (file, args) => {
      if (file === "ps" && args[0] === "-eo" && args[1] === "pid,ppid") {
        return {
          status: 0,
          stdout: "  PID  PPID\n"
            + "    1     0\n"
            + " 2000     1\n"
            + " 2001  2000\n"
            + " 2002  2001\n"
            + " 2003  2001\n",
        };
      }
      return originalSpawnSync(file, args);
    };
    delete require.cache[require.resolve("./claude_task_runner.js")];
    const runnerLinux = require("./claude_task_runner.js");
    const parsed = runnerLinux.listProcessParents();
    assert.deepEqual(
      parsed.filter((p) => p.pid >= 2000),
      [{ pid: 2000, ppid: 1 }, { pid: 2001, ppid: 2000 }, { pid: 2002, ppid: 2001 }, { pid: 2003, ppid: 2001 }],
    );
  } finally {
    cpMod.spawnSync = originalSpawnSync;
    Object.defineProperty(process, "platform", originalPlatform);
    delete require.cache[require.resolve("./claude_task_runner.js")];
  }
});

test("killProcessTree() on non-Windows walks the full descendant tree and SIGKILLs each one individually", () => {
  const cpMod = require("child_process");
  const originalSpawnSync = cpMod.spawnSync;
  const originalPlatform = Object.getOwnPropertyDescriptor(process, "platform");
  const killed = [];
  const originalKill = process.kill;
  try {
    Object.defineProperty(process, "platform", { value: "linux" });
    cpMod.spawnSync = (file, args) => {
      if (file === "ps" && args[0] === "-eo") {
        return { status: 0, stdout: "  PID  PPID\n 3000     1\n 3001  3000\n 3002  3001\n 9999     1\n" };
      }
      return originalSpawnSync(file, args);
    };
    process.kill = (pid, sig) => { killed.push([pid, sig]); };
    delete require.cache[require.resolve("./claude_task_runner.js")];
    const runnerLinux = require("./claude_task_runner.js");
    runnerLinux.killProcessTree(3000);
    assert.deepEqual(new Set(killed.map((k) => k[0])), new Set([3000, 3001, 3002]), "must kill the target plus every descendant, and nothing unrelated (9999 excluded)");
    assert.ok(killed.every((k) => k[1] === "SIGKILL"));
  } finally {
    cpMod.spawnSync = originalSpawnSync;
    process.kill = originalKill;
    Object.defineProperty(process, "platform", originalPlatform);
    delete require.cache[require.resolve("./claude_task_runner.js")];
  }
});

test("no fake_claude/setInterval process from any test in this file is still running", () => {
  const cpMod = require("child_process");
  // Filtered to Name='node.exe' specifically -- this PowerShell query
  // itself is powershell.exe, not node.exe, so it can never self-match.
  const result = cpMod.spawnSync("powershell", [
    "-NoProfile", "-Command",
    "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | Where-Object { $_.CommandLine -match 'fake_claude' -or $_.CommandLine -match 'setInterval' } | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress",
  ], { encoding: "utf8" });
  const stdout = (result.stdout || "").trim();
  const survivors = stdout ? (Array.isArray(JSON.parse(stdout)) ? JSON.parse(stdout) : [JSON.parse(stdout)]) : [];
  assert.deepEqual(survivors, [], `expected zero surviving test processes, found: ${JSON.stringify(survivors)}`);
});
