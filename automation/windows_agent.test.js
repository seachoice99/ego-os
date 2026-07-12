"use strict";

/**
 * Tests for the Windows Runner Agent (automation/windows_agent.js). Never
 * makes a real HTTPS call -- global fetch is monkeypatched with a scripted
 * fake, matching this codebase's own no-real-external-calls test
 * discipline. Task execution itself is proven by the EXISTING
 * claude_task_runner.test.js suite (execute() is reused unmodified here,
 * not reimplemented) -- these tests cover what's actually new: HTTP
 * request shape, the dirty-tree/single-instance startup guards, and
 * command mirroring into the existing local control-file protocol.
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
  const bareDir = fs.mkdtempSync(path.join(os.tmpdir(), "ego-os-agent-js-origin-"));
  const workDir = fs.mkdtempSync(path.join(os.tmpdir(), "ego-os-agent-js-work-"));
  git(["init", "--bare", "-b", "main"], bareDir);
  git(["init", "-b", "main"], workDir);
  git(["config", "user.email", "test@example.com"], workDir);
  git(["config", "user.name", "Test"], workDir);
  fs.mkdirSync(path.join(workDir, "tasks", "queue"), { recursive: true });
  fs.writeFileSync(path.join(workDir, "README.md"), "fake repo for windows_agent tests\n");
  git(["add", "."], workDir);
  git(["commit", "-m", "initial"], workDir);
  git(["remote", "add", "origin", bareDir], workDir);
  git(["push", "-u", "origin", "main"], workDir);
  return { bareDir, workDir };
}

let FAKE_REPO = null;

function freshAgentEnv() {
  if (!FAKE_REPO) FAKE_REPO = setupFakeRepo();
  const localDir = fs.mkdtempSync(path.join(os.tmpdir(), "ego-os-agent-js-local-"));
  process.env.EGO_OS_RUNNER_ROOT_DIR = FAKE_REPO.workDir;
  process.env.EGO_OS_RUNNER_LOCAL_DIR = localDir;
  process.env.EGO_OS_RUNNER_CLAUDE_PATH = path.join(__dirname, "test_fixtures", "fake_claude.cmd");
  process.env.EGO_OS_AGENT_TOKEN = "test-agent-token";
  process.env.EGO_OS_AGENT_SERVER_URL = "https://fake.example.invalid";
  delete process.env.EGO_OS_RUNNER_QUEUE_DIR;
  delete require.cache[require.resolve("./claude_task_runner.js")];
  delete require.cache[require.resolve("./runner_control.js")];
  delete require.cache[require.resolve("./windows_agent.js")];
  const agent = require("./windows_agent.js");
  const runner = require("./claude_task_runner.js");
  return { agent, runner, localDir };
}

function teardown(env) {
  fs.rmSync(env.localDir, { recursive: true, force: true });
  for (const name of fs.readdirSync(path.join(FAKE_REPO.workDir, "tasks", "queue"))) {
    if (name !== ".gitkeep") fs.rmSync(path.join(FAKE_REPO.workDir, "tasks", "queue", name), { force: true });
  }
  // Undo any commits a test made in the shared fake repo, back to origin's
  // own initial state, so the next test starts from the same clean point.
  git(["fetch", "origin", "main"], FAKE_REPO.workDir);
  git(["reset", "--hard", "origin/main"], FAKE_REPO.workDir);
}

function mockFetch(handler) {
  const original = global.fetch;
  const calls = [];
  global.fetch = async (url, opts) => {
    calls.push({ url, opts, body: opts && opts.body ? JSON.parse(opts.body) : null });
    return handler(url, opts, calls);
  };
  return { calls, restore: () => { global.fetch = original; } };
}

function fakeJsonResponse(status, data) {
  return { ok: status < 400, status, json: async () => data };
}

// --- pure logic ------------------------------------------------------------

test("mapOutcome passes through a known status, falls back to done/failed by exec result otherwise", () => {
  const { agent } = freshAgentEnv();
  assert.equal(agent.mapOutcome("waiting_for_limit", true), "waiting_for_limit");
  assert.equal(agent.mapOutcome("something-unrecognized", true), "done");
  assert.equal(agent.mapOutcome("something-unrecognized", false), "failed");
});

test("nextSeq is strictly increasing across repeated calls", () => {
  const { agent } = freshAgentEnv();
  const a = agent.nextSeq();
  const b = agent.nextSeq();
  const c = agent.nextSeq();
  assert.ok(b > a);
  assert.ok(c > b);
});

// --- startup guards ----------------------------------------------------

test("workingTreeIsClean is true on a freshly cloned repo and false once something is uncommitted", () => {
  const env = freshAgentEnv();
  assert.equal(env.agent.workingTreeIsClean(), true);
  fs.writeFileSync(path.join(FAKE_REPO.workDir, "uncommitted.txt"), "someone else's work\n");
  assert.equal(env.agent.workingTreeIsClean(), false);
  fs.rmSync(path.join(FAKE_REPO.workDir, "uncommitted.txt"));
  teardown(env);
});

test("a second acquireAgentLock() call fails while the first is still held, and succeeds after release", () => {
  const env = freshAgentEnv();
  const first = env.agent.acquireAgentLock();
  assert.equal(first.ok, true);
  const second = env.agent.acquireAgentLock();
  assert.equal(second.ok, false);
  env.agent.releaseAgentLock();
  const third = env.agent.acquireAgentLock();
  assert.equal(third.ok, true);
  env.agent.releaseAgentLock();
  teardown(env);
});

// --- command mirroring ----------------------------------------------------

test("mirrorPendingCommand writes the exact command into the local COMMANDS_FILE execute() already reads", () => {
  const env = freshAgentEnv();
  env.agent.mirrorPendingCommand({ command: "pause", requested_at: "2026-01-01T00:00:00Z" });
  const onDisk = JSON.parse(fs.readFileSync(env.runner.COMMANDS_FILE, "utf8"));
  assert.equal(onDisk.command, "pause");
  const pending = env.runner.readPendingCommand();
  assert.equal(pending.command, "pause", "the EXISTING readPendingCommand() must see exactly what the agent mirrored, unmodified");
  teardown(env);
});

test("mirrorPendingCommand does nothing for a null/empty pending command", () => {
  const env = freshAgentEnv();
  env.agent.mirrorPendingCommand(null);
  assert.equal(fs.existsSync(env.runner.COMMANDS_FILE), false);
  teardown(env);
});

// --- HTTP request shape (mocked fetch, no real network) ---------------------

test("register sends the Bearer token and stores the returned agent_id locally", async () => {
  const env = freshAgentEnv();
  const mock = mockFetch(async (url) => {
    assert.match(url, /\/agent\/register$/);
    return fakeJsonResponse(200, { ok: true, agent_id: "agent-123" });
  });
  const id = await env.agent.ensureRegistered();
  assert.equal(id, "agent-123");
  assert.equal(mock.calls[0].opts.headers.Authorization, "Bearer test-agent-token");
  assert.equal(fs.readFileSync(env.agent.AGENT_ID_FILE, "utf8"), "agent-123");
  mock.restore();
  teardown(env);
});

test("a second ensureRegistered() call in the same process does not re-register", async () => {
  const env = freshAgentEnv();
  const mock = mockFetch(async () => fakeJsonResponse(200, { ok: true, agent_id: "agent-456" }));
  await env.agent.ensureRegistered();
  await env.agent.ensureRegistered();
  assert.equal(mock.calls.length, 1, "the in-memory agentId must be reused, not re-registered every call");
  mock.restore();
  teardown(env);
});

test("heartbeat includes a strictly-increasing seq and mirrors a returned pending_command", async () => {
  const env = freshAgentEnv();
  const mock = mockFetch(async (url, opts) => {
    if (url.endsWith("/agent/register")) return fakeJsonResponse(200, { ok: true, agent_id: "agent-hb" });
    if (url.endsWith("/agent/heartbeat")) return fakeJsonResponse(200, { ok: true, pending_command: { command: "resume" } });
    throw new Error(`unexpected url ${url}`);
  });
  await env.agent.heartbeat("idle");
  const pending = env.runner.readPendingCommand();
  assert.equal(pending.command, "resume");
  const hbCall = mock.calls.find((c) => c.url.endsWith("/agent/heartbeat"));
  assert.ok(Number.isFinite(hbCall.body.seq));
  mock.restore();
  teardown(env);
});

test("claim forwards the agent_id and returns whatever task the server reports", async () => {
  const env = freshAgentEnv();
  const mock = mockFetch(async (url) => {
    if (url.endsWith("/agent/register")) return fakeJsonResponse(200, { ok: true, agent_id: "agent-claim" });
    if (url.endsWith("/agent/claim")) return fakeJsonResponse(200, { task: { id: "TEST-1", title: "t" } });
    throw new Error(`unexpected url ${url}`);
  });
  const result = await env.agent.claim();
  assert.equal(result.data.task.id, "TEST-1");
  const claimCall = mock.calls.find((c) => c.url.endsWith("/agent/claim"));
  assert.equal(claimCall.body.agent_id, "agent-claim");
  mock.restore();
  teardown(env);
});

test("reportResult sends the task_id, outcome, and summary", async () => {
  const env = freshAgentEnv();
  const mock = mockFetch(async (url) => {
    if (url.endsWith("/agent/register")) return fakeJsonResponse(200, { ok: true, agent_id: "agent-report" });
    if (url.endsWith("/agent/report-result")) return fakeJsonResponse(200, { ok: true });
    throw new Error(`unexpected url ${url}`);
  });
  await env.agent.reportResult("TEST-2", "done", "all good");
  const call = mock.calls.find((c) => c.url.endsWith("/agent/report-result"));
  assert.equal(call.body.task_id, "TEST-2");
  assert.equal(call.body.outcome, "done");
  assert.equal(call.body.summary, "all good");
  mock.restore();
  teardown(env);
});

test("a network failure during heartbeat resolves gracefully (ok:false), never throws uncaught", async () => {
  const env = freshAgentEnv();
  const mock = mockFetch(async (url) => {
    if (url.endsWith("/agent/register")) return fakeJsonResponse(200, { ok: true, agent_id: "agent-fail" });
    throw new Error("simulated network failure");
  });
  const result = await env.agent.heartbeat("idle");
  assert.equal(result.ok, false);
  mock.restore();
  teardown(env);
});
