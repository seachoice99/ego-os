"use strict";

/**
 * Integration tests for the RUNNER-CONTROL-UI local control API. Spins up
 * a REAL http server on an OS-assigned ephemeral port against an isolated
 * fake repo + local dir (same pattern as claude_task_runner.test.js), and
 * makes real HTTP requests via the built-in fetch -- proving the actual
 * request/response behavior, not just the route handlers in isolation.
 */

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const path = require("path");
const os = require("os");
const cp = require("child_process");

function git(args, cwd) {
  const result = cp.spawnSync("git", args, { cwd, encoding: "utf8" });
  if (result.status !== 0) throw new Error(`git ${args.join(" ")} failed: ${result.stderr}`);
  return result.stdout;
}

function setupFakeRepo() {
  const bareDir = fs.mkdtempSync(path.join(os.tmpdir(), "ego-os-control-origin-"));
  const workDir = fs.mkdtempSync(path.join(os.tmpdir(), "ego-os-control-work-"));
  git(["init", "--bare", "-b", "main"], bareDir);
  git(["init", "-b", "main"], workDir);
  git(["config", "user.email", "test@example.com"], workDir);
  git(["config", "user.name", "Test"], workDir);
  fs.mkdirSync(path.join(workDir, "tasks", "queue"), { recursive: true });
  fs.writeFileSync(path.join(workDir, "README.md"), "fake repo for control_server tests\n");
  git(["add", "."], workDir);
  git(["commit", "-m", "initial"], workDir);
  git(["remote", "add", "origin", bareDir], workDir);
  git(["push", "-u", "origin", "main"], workDir);
  return { bareDir, workDir };
}

let FAKE_REPO = null;

function writeTask(queueDir, overrides) {
  const task = {
    id: "TEST-001", status: "ready", priority: "P1", title: "Test task",
    prompt: "Do the test thing.", acceptance: ["it works"],
    allowed_paths: [], forbidden_paths: [], risks: [],
    owner_approved: false, release: "no_deploy", result: null,
    ...overrides,
  };
  fs.writeFileSync(path.join(queueDir, `${task.id}.yaml`), JSON.stringify(task, null, 2) + "\n", "utf8");
  return task;
}

async function freshServerEnv() {
  if (!FAKE_REPO) FAKE_REPO = setupFakeRepo();
  const localDir = fs.mkdtempSync(path.join(os.tmpdir(), "ego-os-control-local-"));
  const lockFile = path.join(localDir, "control-server.lock");
  process.env.EGO_OS_RUNNER_ROOT_DIR = FAKE_REPO.workDir;
  process.env.EGO_OS_RUNNER_LOCAL_DIR = localDir;
  process.env.EGO_OS_RUNNER_CLAUDE_PATH = path.join(__dirname, "test_fixtures", "fake_claude.cmd");
  process.env.EGO_OS_CONTROL_LOCK = lockFile;
  process.env.EGO_OS_CONTROL_WEB_DIR = path.join(__dirname, "web");
  delete process.env.EGO_OS_RUNNER_QUEUE_DIR;
  delete require.cache[require.resolve("./claude_task_runner.js")];
  delete require.cache[require.resolve("./runner_control.js")];
  delete require.cache[require.resolve("./control_server.js")];
  const runner = require("./claude_task_runner.js");
  const controlServer = require("./control_server.js");
  const result = await controlServer.start({ port: 0, attachSignalHandlers: false });
  assert.equal(result.ok, true, result.reason);
  const base = `http://127.0.0.1:${result.port}`;
  return {
    runner, controlServer, localDir, base, server: result.server,
    queueDir: path.join(FAKE_REPO.workDir, "tasks", "queue"),
  };
}

function teardown(env) {
  env.controlServer.releaseControlLock();
  // closeAllConnections forces any lingering keep-alive sockets (from
  // fetch()'s own connection pool) shut immediately -- without it,
  // server.close() alone waits for those to end on their own, which can
  // keep the whole test process from exiting after the last test finishes.
  if (env.server.closeAllConnections) env.server.closeAllConnections();
  env.server.close();
  fs.rmSync(env.localDir, { recursive: true, force: true });
  // Clear any task files this test wrote into the shared fake repo's queue.
  for (const name of fs.readdirSync(env.queueDir)) {
    if (name !== ".gitkeep") fs.rmSync(path.join(env.queueDir, name), { force: true });
  }
}

// --- binding -------------------------------------------------------------

test("the control server binds to 127.0.0.1 only, never a public interface", async () => {
  const env = await freshServerEnv();
  const addr = env.server.address();
  assert.equal(addr.address, "127.0.0.1");
  teardown(env);
});

// --- status / tasks --------------------------------------------------------

test("GET /api/status returns a default stopped state when the runner has never run", async () => {
  const env = await freshServerEnv();
  const res = await fetch(`${env.base}/api/status`);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.runner_state, "stopped");
  assert.equal(body.runner_actually_running, false);
  teardown(env);
});

test("GET /api/tasks lists queued tasks in the summarized shape, no secrets, no full prompt dump", async () => {
  const env = await freshServerEnv();
  writeTask(env.queueDir, { id: "TEST-QUEUE-1", title: "Do a thing" });
  const res = await fetch(`${env.base}/api/tasks`);
  const body = await res.json();
  assert.equal(res.status, 200);
  const found = body.tasks.find((t) => t.id === "TEST-QUEUE-1");
  assert.ok(found);
  assert.equal(found.title, "Do a thing");
  assert.equal(found.prompt, undefined, "the summarized queue shape must not include the full task prompt");
  teardown(env);
});

test("GET /api/tasks attaches a casual project group and display_summary for the dashboard's card view", async () => {
  const env = await freshServerEnv();
  writeTask(env.queueDir, { id: "MED-99", title: "Some technical title" });
  const res = await fetch(`${env.base}/api/tasks`);
  const body = await res.json();
  const found = body.tasks.find((t) => t.id === "MED-99");
  assert.equal(found.group_key, "multi-executor");
  assert.equal(found.display_summary, "Some technical title", "falls back to title when display_summary is absent");
  teardown(env);
});

test("GET /api/usage returns an honest empty tracker before any session has ever run", async () => {
  const env = await freshServerEnv();
  const res = await fetch(`${env.base}/api/usage`);
  const body = await res.json();
  assert.equal(res.status, 200);
  assert.equal(body.usage.claude.total_sessions, 0);
  assert.equal(body.usage.codex.total_sessions, 0);
  teardown(env);
});

test("GET /api/usage reflects a session recorded by recordSessionUsage", async () => {
  const env = await freshServerEnv();
  env.runner.recordSessionUsage(
    { id: "TEST-QUEUE-1" },
    JSON.stringify({ type: "result", total_cost_usd: 0.05, usage: { input_tokens: 10, output_tokens: 20 } }),
  );
  const res = await fetch(`${env.base}/api/usage`);
  const body = await res.json();
  assert.equal(body.usage.claude.total_sessions, 1);
  assert.ok(Math.abs(body.usage.claude.total_cost_usd - 0.05) < 1e-9);
  teardown(env);
});

test("GET /api/usage enriches codex with the latest real rate-limit snapshot when one has been logged", async () => {
  const fakeCodex = path.join(__dirname, "test_fixtures", process.platform === "win32" ? "fake_codex_app_server.cmd" : "fake_codex_app_server.js");
  process.env.EGO_OS_CODEX_APP_SERVER_PATH = fakeCodex;
  process.env.EGO_OS_FAKE_CODEX_SCENARIO = "full_response";
  delete require.cache[require.resolve("./codex_usage.js")];
  const env = await freshServerEnv();
  await env.runner.snapshotCodexUsageIfNeeded({ id: "TEST-QUEUE-1", status: "done" }, "codex");
  const res = await fetch(`${env.base}/api/usage`);
  const body = await res.json();
  assert.ok(body.usage.codex.rate_limits);
  assert.equal(body.usage.codex.rate_limits.task_id, "TEST-QUEUE-1");
  assert.equal(body.usage.codex.rate_limits.status, "available");
  delete process.env.EGO_OS_CODEX_APP_SERVER_PATH;
  delete process.env.EGO_OS_FAKE_CODEX_SCENARIO;
  teardown(env);
});

// --- path traversal defenses ---------------------------------------------

test("GET /api/tasks/:id rejects a path-traversal id instead of resolving it", async () => {
  const env = await freshServerEnv();
  const res = await fetch(`${env.base}/api/tasks/${encodeURIComponent("../../../../etc/passwd")}`);
  assert.notEqual(res.status, 200);
  teardown(env);
});

test("GET /api/logs rejects a file parameter that tries to escape LOG_DIR", async () => {
  const env = await freshServerEnv();
  const res = await fetch(`${env.base}/api/logs?file=${encodeURIComponent("../../../../windows/system32/config/sam")}`);
  assert.equal(res.status, 404);
  teardown(env);
});

test("GET /api/logs returns masked content for a real log file inside LOG_DIR", async () => {
  const env = await freshServerEnv();
  fs.mkdirSync(env.runner.LOG_DIR, { recursive: true });
  const logFile = path.join(env.runner.LOG_DIR, "sample-stage1.log");
  fs.writeFileSync(logFile, "normal output\nOWNER_PASSWORD=hunter2verysecret\nmore output\n", "utf8");
  const res = await fetch(`${env.base}/api/logs?file=sample-stage1.log`);
  const body = await res.json();
  assert.equal(res.status, 200);
  assert.doesNotMatch(body.content, /hunter2verysecret/);
  assert.match(body.content, /\[REDACTED\]/);
  teardown(env);
});

// --- request size limits --------------------------------------------------

test("an oversized POST body is rejected with 413, not silently truncated or crashed", async () => {
  const env = await freshServerEnv();
  const huge = "x".repeat(200 * 1024);
  const res = await fetch(`${env.base}/api/tasks/reorder`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ order: [huge] }),
  });
  assert.equal(res.status, 413);
  teardown(env);
});

// --- confirmation required for dangerous actions --------------------------

test("POST /api/runner/emergency-stop without confirm:true is rejected", async () => {
  const env = await freshServerEnv();
  const res = await fetch(`${env.base}/api/runner/emergency-stop`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  assert.equal(res.status, 400);
  teardown(env);
});

test("POST /api/tasks/:id/skip without confirm:true is rejected; with confirm it succeeds and is recorded", async () => {
  const env = await freshServerEnv();
  writeTask(env.queueDir, { id: "TEST-SKIP-ME" });
  const rejected = await fetch(`${env.base}/api/tasks/TEST-SKIP-ME/skip`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  assert.equal(rejected.status, 400);

  const accepted = await fetch(`${env.base}/api/tasks/TEST-SKIP-ME/skip`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm: true, reason: "no longer needed" }),
  });
  assert.equal(accepted.status, 200);
  const task = env.runner.load(path.join(env.queueDir, "TEST-SKIP-ME.yaml"));
  assert.equal(task.status, "skipped");
  assert.equal(task.result.skip_reason, "no longer needed");
  teardown(env);
});

test("POST /api/tasks/:id/retry is refused on a task that is not failed/waiting_for_auth/interrupted", async () => {
  const env = await freshServerEnv();
  writeTask(env.queueDir, { id: "TEST-RETRY-READY", status: "ready" });
  const res = await fetch(`${env.base}/api/tasks/TEST-RETRY-READY/retry`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm: true }),
  });
  assert.equal(res.status, 409);
  teardown(env);
});

// --- reorder ---------------------------------------------------------------

test("POST /api/tasks/reorder writes queue_order and nextTask() then honors it", async () => {
  const env = await freshServerEnv();
  writeTask(env.queueDir, { id: "TEST-ORDER-A", priority: "P1" });
  writeTask(env.queueDir, { id: "TEST-ORDER-B", priority: "P1" });
  const res = await fetch(`${env.base}/api/tasks/reorder`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ order: ["TEST-ORDER-B", "TEST-ORDER-A"] }),
  });
  assert.equal(res.status, 200);
  const selected = env.runner.nextTask();
  assert.equal(selected.task.id, "TEST-ORDER-B", "reorder must actually change nextTask()'s pick, not just be recorded cosmetically");
  teardown(env);
});

// --- single control server per workspace -----------------------------------

test("a second start() attempt in the same workspace is refused while the first still holds the lock", async () => {
  const env = await freshServerEnv();
  const second = env.controlServer.acquireControlLock();
  assert.equal(second.ok, false);
  assert.match(second.reason, /already running/);
  teardown(env);
});

// --- non-loopback rejection (defense in depth beyond the HOST bind) --------

test("router() rejects a request whose socket remoteAddress is not loopback", async () => {
  const env = await freshServerEnv();
  const fakeReq = { method: "GET", url: "/api/status", socket: { remoteAddress: "10.0.0.5" } };
  let statusCode = null;
  const fakeRes = { writeHead: (code) => { statusCode = code; }, end: () => {} };
  await env.controlServer.router(fakeReq, fakeRes);
  assert.equal(statusCode, 403);
  teardown(env);
});
