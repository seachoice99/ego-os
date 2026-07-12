"use strict";

/**
 * Integration tests for the Windows Runner Agent coordination endpoints
 * (control_server.js's /api/agent/*). Same pattern as control_server.test.js:
 * a real HTTP server on an ephemeral port, real fetch() requests, an
 * isolated throwaway git repo. Never involves a real Claude process --
 * these endpoints don't run anything, they only coordinate.
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
  const bareDir = fs.mkdtempSync(path.join(os.tmpdir(), "ego-os-agent-origin-"));
  const workDir = fs.mkdtempSync(path.join(os.tmpdir(), "ego-os-agent-work-"));
  git(["init", "--bare", "-b", "main"], bareDir);
  git(["init", "-b", "main"], workDir);
  git(["config", "user.email", "test@example.com"], workDir);
  git(["config", "user.name", "Test"], workDir);
  fs.mkdirSync(path.join(workDir, "tasks", "queue"), { recursive: true });
  fs.writeFileSync(path.join(workDir, "README.md"), "fake repo for agent coordination tests\n");
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
  const localDir = fs.mkdtempSync(path.join(os.tmpdir(), "ego-os-agent-local-"));
  process.env.EGO_OS_RUNNER_ROOT_DIR = FAKE_REPO.workDir;
  process.env.EGO_OS_RUNNER_LOCAL_DIR = localDir;
  process.env.EGO_OS_RUNNER_CLAUDE_PATH = path.join(__dirname, "test_fixtures", "fake_claude.cmd");
  process.env.EGO_OS_CONTROL_LOCK = path.join(localDir, "control-server.lock");
  process.env.EGO_OS_AGENT_TOKEN_FILE = path.join(localDir, "agent_token");
  process.env.EGO_OS_AGENTS_FILE = path.join(localDir, "agents.json");
  delete process.env.EGO_OS_RUNNER_QUEUE_DIR;
  delete require.cache[require.resolve("./claude_task_runner.js")];
  delete require.cache[require.resolve("./runner_control.js")];
  delete require.cache[require.resolve("./control_server.js")];
  const runner = require("./claude_task_runner.js");
  const controlServer = require("./control_server.js");
  const result = await controlServer.start({ port: 0, attachSignalHandlers: false });
  assert.equal(result.ok, true, result.reason);
  const base = `http://127.0.0.1:${result.port}`;
  const token = controlServer.getOrCreateAgentToken();
  return {
    runner, controlServer, localDir, base, server: result.server, token,
    queueDir: path.join(FAKE_REPO.workDir, "tasks", "queue"),
  };
}

function teardown(env) {
  env.controlServer.releaseControlLock();
  if (env.server.closeAllConnections) env.server.closeAllConnections();
  env.server.close();
  fs.rmSync(env.localDir, { recursive: true, force: true });
  for (const name of fs.readdirSync(env.queueDir)) {
    if (name !== ".gitkeep") fs.rmSync(path.join(env.queueDir, name), { force: true });
  }
}

async function agentPost(env, route, token, bodyObj) {
  return fetch(`${env.base}${route}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify(bodyObj || {}),
  });
}

async function registerAgent(env, name = "test-agent") {
  const res = await agentPost(env, "/api/agent/register", env.token, { name });
  assert.equal(res.status, 200);
  const body = await res.json();
  return body.agent_id;
}

// --- authentication ----------------------------------------------------

test("agent register without a token is rejected", async () => {
  const env = await freshServerEnv();
  const res = await agentPost(env, "/api/agent/register", null, { name: "x" });
  assert.equal(res.status, 401);
  teardown(env);
});

test("agent register with the wrong token is rejected", async () => {
  const env = await freshServerEnv();
  const res = await agentPost(env, "/api/agent/register", "totally-wrong-token", { name: "x" });
  assert.equal(res.status, 401);
  teardown(env);
});

test("agent register with the correct token succeeds and returns an agent_id", async () => {
  const env = await freshServerEnv();
  const res = await agentPost(env, "/api/agent/register", env.token, { name: "windows-desktop" });
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.ok(body.agent_id);
  teardown(env);
});

test("register is idempotent -- re-registering a known agent_id returns the same id", async () => {
  const env = await freshServerEnv();
  const first = await registerAgent(env);
  const res = await agentPost(env, "/api/agent/register", env.token, { agent_id: first, name: "windows-desktop" });
  const body = await res.json();
  assert.equal(body.agent_id, first);
  teardown(env);
});

test("an unregistered agent_id is rejected on any authenticated route", async () => {
  const env = await freshServerEnv();
  const res = await agentPost(env, "/api/agent/heartbeat", env.token, { agent_id: "00000000-0000-0000-0000-000000000000", seq: 1 });
  assert.equal(res.status, 404);
  teardown(env);
});

// --- heartbeat + online/offline -------------------------------------------

test("heartbeat with a valid, registered agent succeeds and status reflects it online", async () => {
  const env = await freshServerEnv();
  const agentId = await registerAgent(env);
  const res = await agentPost(env, "/api/agent/heartbeat", env.token, { agent_id: agentId, seq: 1, status: "idle" });
  assert.equal(res.status, 200);
  const statusRes = await fetch(`${env.base}/api/status`);
  const status = await statusRes.json();
  assert.equal(status.any_agent_online, true);
  assert.equal(status.agents.find((a) => a.agent_id === agentId).online, true);
  teardown(env);
});

test("an agent that never heartbeats shows offline", async () => {
  const env = await freshServerEnv();
  const statusRes = await fetch(`${env.base}/api/status`);
  const status = await statusRes.json();
  assert.equal(status.any_agent_online, false);
  assert.deepEqual(status.agents, []);
  teardown(env);
});

// --- replay / reused request rejection -------------------------------------

test("a request with seq <= last accepted seq is rejected as a replay", async () => {
  const env = await freshServerEnv();
  const agentId = await registerAgent(env);
  const first = await agentPost(env, "/api/agent/heartbeat", env.token, { agent_id: agentId, seq: 5 });
  assert.equal(first.status, 200);
  const replay = await agentPost(env, "/api/agent/heartbeat", env.token, { agent_id: agentId, seq: 5 });
  assert.equal(replay.status, 409);
  const older = await agentPost(env, "/api/agent/heartbeat", env.token, { agent_id: agentId, seq: 3 });
  assert.equal(older.status, 409);
  const higher = await agentPost(env, "/api/agent/heartbeat", env.token, { agent_id: agentId, seq: 6 });
  assert.equal(higher.status, 200);
  teardown(env);
});

// --- single claim, no double-claim -----------------------------------------

test("claim returns the only ready task, and a second claim afterward gets nothing", async () => {
  const env = await freshServerEnv();
  const agentId = await registerAgent(env);
  writeTask(env.queueDir, { id: "TEST-CLAIM-ONE" });
  git(["add", "."], FAKE_REPO.workDir);
  git(["commit", "-m", "Queue TEST-CLAIM-ONE"], FAKE_REPO.workDir);
  git(["push", "origin", "main"], FAKE_REPO.workDir);

  const first = await agentPost(env, "/api/agent/claim", env.token, { agent_id: agentId, seq: 1 });
  assert.equal(first.status, 200);
  const firstBody = await first.json();
  assert.equal(firstBody.task.id, "TEST-CLAIM-ONE");
  assert.equal(firstBody.task.status, "claimed");
  assert.equal(firstBody.task.result.agent_lease.agent_id, agentId);

  const second = await agentPost(env, "/api/agent/claim", env.token, { agent_id: agentId, seq: 2 });
  const secondBody = await second.json();
  assert.equal(secondBody.task, null, "the same task must never be handed out twice while its lease is live");
  teardown(env);
});

test("a claimed task is durably committed -- reflected in the real task file on disk", async () => {
  const env = await freshServerEnv();
  const agentId = await registerAgent(env);
  writeTask(env.queueDir, { id: "TEST-CLAIM-COMMIT" });
  git(["add", "."], FAKE_REPO.workDir);
  git(["commit", "-m", "Queue TEST-CLAIM-COMMIT"], FAKE_REPO.workDir);
  git(["push", "origin", "main"], FAKE_REPO.workDir);

  await agentPost(env, "/api/agent/claim", env.token, { agent_id: agentId, seq: 1 });
  const onDisk = env.runner.load(path.join(env.queueDir, "TEST-CLAIM-COMMIT.yaml"));
  assert.equal(onDisk.status, "claimed");
  const status = env.runner.run("git", ["status", "--porcelain"]);
  assert.equal(status.stdout.trim(), "", "the claim must be committed, not left as a dirty working tree");
  teardown(env);
});

// --- lease expiry --------------------------------------------------------

test("an expired lease reverts the task to its pre-claim status and makes it claimable again", async () => {
  const env = await freshServerEnv();
  const agentId = await registerAgent(env);
  const file = path.join(env.queueDir, "TEST-LEASE-EXPIRE.yaml");
  const task = writeTask(env.queueDir, {
    id: "TEST-LEASE-EXPIRE",
    status: "claimed",
    result: {
      pre_claim_status: "ready",
      agent_lease: { agent_id: "some-other-agent", claimed_at: new Date(Date.now() - 3600000).toISOString(), expires_at: new Date(Date.now() - 1000).toISOString() },
    },
  });
  git(["add", "."], FAKE_REPO.workDir);
  git(["commit", "-m", "Queue TEST-LEASE-EXPIRE (pre-claimed, expired)"], FAKE_REPO.workDir);
  git(["push", "origin", "main"], FAKE_REPO.workDir);

  const res = await agentPost(env, "/api/agent/claim", env.token, { agent_id: agentId, seq: 1 });
  const body = await res.json();
  assert.equal(body.task.id, "TEST-LEASE-EXPIRE", "an expired lease must free the task for a new claim");
  assert.equal(body.task.result.agent_lease.agent_id, agentId, "the NEW agent now holds the lease, not the one that abandoned it");
  void task;
  teardown(env);
});

test("a lease that has NOT expired is not claimable by a second agent", async () => {
  const env = await freshServerEnv();
  const agentId = await registerAgent(env, "second-agent");
  writeTask(env.queueDir, {
    id: "TEST-LEASE-ACTIVE",
    status: "claimed",
    result: {
      pre_claim_status: "ready",
      agent_lease: { agent_id: "first-agent", claimed_at: new Date().toISOString(), expires_at: new Date(Date.now() + 3600000).toISOString() },
    },
  });
  git(["add", "."], FAKE_REPO.workDir);
  git(["commit", "-m", "Queue TEST-LEASE-ACTIVE (live lease)"], FAKE_REPO.workDir);
  git(["push", "origin", "main"], FAKE_REPO.workDir);

  const res = await agentPost(env, "/api/agent/claim", env.token, { agent_id: agentId, seq: 1 });
  const body = await res.json();
  assert.equal(body.task, null, "a task still validly leased to another agent must not be claimable");
  teardown(env);
});

// --- command forwarding: pause/resume/emergency-stop visible via heartbeat ---

test("a pause command queued via the Owner-facing API is returned to the agent's next heartbeat", async () => {
  const env = await freshServerEnv();
  const agentId = await registerAgent(env);
  // The runner starts "stopped" until an agent's first heartbeat signals
  // it's alive (mirrors the old local main()'s own startup transition) --
  // pause is only a legal command once the runner is actually running.
  await agentPost(env, "/api/agent/heartbeat", env.token, { agent_id: agentId, seq: 1 });

  const pauseRes = await fetch(`${env.base}/api/runner/pause`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  assert.equal(pauseRes.status, 202);

  const hb = await agentPost(env, "/api/agent/heartbeat", env.token, { agent_id: agentId, seq: 2 });
  const body = await hb.json();
  assert.equal(body.pending_command.command, "pause");
  teardown(env);
});

test("emergency-stop still requires confirm:true even when agents are registered", async () => {
  const env = await freshServerEnv();
  await registerAgent(env);
  const res = await fetch(`${env.base}/api/runner/emergency-stop`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  assert.equal(res.status, 400);
  teardown(env);
});

test("'start' with a registered agent queues a resume command instead of spawning a local process", async () => {
  const env = await freshServerEnv();
  const agentId = await registerAgent(env);
  const res = await fetch(`${env.base}/api/runner/start`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  assert.equal(res.status, 202);
  const hb = await agentPost(env, "/api/agent/heartbeat", env.token, { agent_id: agentId, seq: 1 });
  const body = await hb.json();
  assert.equal(body.pending_command.command, "resume");
  teardown(env);
});

// --- path traversal / invalid task id on agent routes -----------------------

test("report-result rejects a path-traversal-shaped task_id", async () => {
  const env = await freshServerEnv();
  const agentId = await registerAgent(env);
  const res = await agentPost(env, "/api/agent/report-result", env.token, { agent_id: agentId, seq: 1, task_id: "../../etc/passwd", outcome: "done" });
  assert.equal(res.status, 400);
  teardown(env);
});

test("report-result rejects an invalid outcome value", async () => {
  const env = await freshServerEnv();
  const agentId = await registerAgent(env);
  const res = await agentPost(env, "/api/agent/report-result", env.token, { agent_id: agentId, seq: 1, task_id: "DA-01", outcome: "totally-fine-i-swear" });
  assert.equal(res.status, 400);
  teardown(env);
});

// --- agent cannot execute arbitrary server commands -------------------------

test("request-deploy never runs a shell string from the agent -- an invalid commit_sha shape is rejected before any git/systemctl call", async () => {
  const env = await freshServerEnv();
  const agentId = await registerAgent(env);
  const res = await agentPost(env, "/api/agent/request-deploy", env.token, {
    agent_id: agentId, seq: 1, task_id: "DA-01", commit_sha: "abc; rm -rf /",
  });
  assert.equal(res.status, 400);
  teardown(env);
});

test("request-deploy refuses a commit_sha that is not actually an ancestor of origin/main", async () => {
  const env = await freshServerEnv();
  const agentId = await registerAgent(env);
  const res = await agentPost(env, "/api/agent/request-deploy", env.token, {
    agent_id: agentId, seq: 1, task_id: "DA-01", commit_sha: "0000000000000000000000000000000000000f",
  });
  assert.equal(res.status, 409);
  teardown(env);
});

// --- secret masking: the agent token itself is never echoed back -----------

test("no API response ever echoes the raw agent token back", async () => {
  const env = await freshServerEnv();
  const res = await agentPost(env, "/api/agent/register", env.token, { name: "x" });
  const text = await res.text();
  assert.doesNotMatch(text, new RegExp(env.token));
  teardown(env);
});

test("generating a new agent token never logs the full value -- only the last 4 characters", async () => {
  const localDir = fs.mkdtempSync(path.join(os.tmpdir(), "ego-os-agent-tokenlog-"));
  process.env.EGO_OS_AGENT_TOKEN_FILE = path.join(localDir, "agent_token");
  delete require.cache[require.resolve("./control_server.js")];
  delete require.cache[require.resolve("./claude_task_runner.js")];
  delete require.cache[require.resolve("./runner_control.js")];
  const controlServer = require("./control_server.js");

  const originalLog = console.log;
  const logged = [];
  console.log = (...args) => { logged.push(args.join(" ")); };
  let token;
  try {
    token = controlServer.getOrCreateAgentToken();
  } finally {
    console.log = originalLog;
  }

  const combinedLog = logged.join("\n");
  assert.doesNotMatch(
    combinedLog,
    new RegExp(token),
    "the full agent token must never be written to console/log output"
  );
  assert.match(
    combinedLog,
    new RegExp(token.slice(-4).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")),
    "a short, non-identifying suffix should still be logged so an operator can confirm rotation happened"
  );
  fs.rmSync(localDir, { recursive: true, force: true });
});
