#!/usr/bin/env node
"use strict";

/**
 * RUNNER-CONTROL-UI: a small, local, dependency-free HTTP control server.
 * Binds to 127.0.0.1 ONLY -- never a public interface. Serves the plain
 * HTML/CSS/JS dashboard under automation/web/ and a minimal JSON API that
 * lets that dashboard observe and safely command the EXISTING runner
 * engine (claude_task_runner.js) -- this file never re-implements process
 * spawning, tree-kill, task loading, or state-machine rules; it only
 * spawns/monitors the engine and reads/writes the same file-based control
 * protocol the engine itself already honors (automation/runner_control.js).
 */

const http = require("http");
const fs = require("fs");
const path = require("path");
const cp = require("child_process");
const crypto = require("crypto");

const runner = require("./claude_task_runner.js");
const {
  isValidCommand,
  commandAllowedInState,
  isSafeTaskId,
  resolveTaskFile,
  taskActionAllowed,
  validateReorder,
  summarizeTask,
  maskSecrets,
  isLeaseExpired,
  buildLease,
  isReplayedRequest,
  isAgentOnline,
  AGENT_LEASE_MINUTES_DEFAULT,
} = require("./runner_control.js");

const HOST = "127.0.0.1";
const PORT = Number(process.env.EGO_OS_CONTROL_PORT) || 4756;
const MAX_BODY_BYTES = 64 * 1024;
const WEB_DIR = process.env.EGO_OS_CONTROL_WEB_DIR || path.join(__dirname, "web");
const CONTROL_LOCK = process.env.EGO_OS_CONTROL_LOCK || path.join(path.dirname(runner.LOCK), "ego-os-control-server.lock");
const LOG_LINE_LIMIT = 500;
const EVENTS_LIMIT_DEFAULT = 200;

// --- Windows Runner Agent coordination -------------------------------------
// Claude Code cannot run on this VPS (confirmed external blocker). This
// server no longer executes any task itself -- it hands one task at a time
// to a remote agent (the Owner's own Windows machine) over the same
// loopback-bound HTTP surface, authenticated by a SEPARATE token (never
// Owner Basic Auth, which is a human credential, not a machine one).
const AGENT_TOKEN_FILE = process.env.EGO_OS_AGENT_TOKEN_FILE || path.join(runner.CONTROL_DIR, "agent_token");
const AGENTS_FILE = process.env.EGO_OS_AGENTS_FILE || path.join(runner.CONTROL_DIR, "agents.json");
const PRODUCTION_DIR = process.env.EGO_OS_PRODUCTION_DIR || "/opt/ego-os";
const PRODUCTION_USER = process.env.EGO_OS_PRODUCTION_USER || "egoos";
const PRODUCTION_SERVICE = process.env.EGO_OS_PRODUCTION_SERVICE || "ego-os";

function getOrCreateAgentToken() {
  try {
    const existing = fs.readFileSync(AGENT_TOKEN_FILE, "utf8").trim();
    if (existing) return existing;
  } catch { /* not created yet */ }
  fs.mkdirSync(path.dirname(AGENT_TOKEN_FILE), { recursive: true });
  const token = crypto.randomBytes(32).toString("hex");
  fs.writeFileSync(AGENT_TOKEN_FILE, token, { mode: 0o600 });
  // Never log the full token -- it would land in journalctl/syslog and
  // count as disclosed. Only the last 4 characters are logged, purely so
  // an operator can confirm which rotation is active; the real value is
  // read directly from AGENT_TOKEN_FILE (mode 0600) by whoever needs it.
  console.log(`Generated new Windows agent token, ends in ...${token.slice(-4)}. Full value: ${AGENT_TOKEN_FILE} (not logged).`);
  return token;
}

function readAgents() {
  try { return JSON.parse(fs.readFileSync(AGENTS_FILE, "utf8")); } catch { return {}; }
}

function writeAgents(agents) {
  fs.mkdirSync(path.dirname(AGENTS_FILE), { recursive: true });
  fs.writeFileSync(AGENTS_FILE, JSON.stringify(agents, null, 2), "utf8");
}

function timingSafeTokenEqual(a, b) {
  const bufA = Buffer.from(String(a || ""));
  const bufB = Buffer.from(String(b || ""));
  if (bufA.length !== bufB.length) return false;
  return crypto.timingSafeEqual(bufA, bufB);
}

function authenticateAgentToken(req) {
  const authHeader = req.headers["authorization"] || "";
  const token = authHeader.startsWith("Bearer ") ? authHeader.slice(7) : null;
  // getOrCreateAgentToken() must run unconditionally -- if it were only
  // reached via the right side of `!token || ...`, short-circuit evaluation
  // would skip it on any unauthenticated request, so the token file would
  // never be created until someone already had a (possibly wrong) token to
  // send, a chicken-and-egg gap that leaves the Owner with no way to obtain
  // it in the first place.
  const expected = getOrCreateAgentToken();
  if (!token || !timingSafeTokenEqual(token, expected)) {
    return { ok: false, status: 401, error: "invalid or missing agent token" };
  }
  return { ok: true };
}

// Full auth for every agent route except register: token + a known
// agent_id + a strictly-increasing seq (replay/reuse defense -- see
// runner_control.isReplayedRequest). Never trusts agent_id/seq as
// anything other than plain values -- no code path evaluates them.
function authenticateAgentRequest(req, body) {
  const tokenCheck = authenticateAgentToken(req);
  if (!tokenCheck.ok) return tokenCheck;
  const agentId = typeof body.agent_id === "string" ? body.agent_id : null;
  if (!agentId || !/^[a-f0-9-]{8,64}$/i.test(agentId)) {
    return { ok: false, status: 400, error: "invalid agent_id" };
  }
  const seq = Number(body.seq);
  const agents = readAgents();
  const existing = agents[agentId];
  if (!existing) return { ok: false, status: 404, error: "unknown agent_id -- register first" };
  if (isReplayedRequest(seq, existing.last_seq)) {
    return { ok: false, status: 409, error: "replayed or out-of-order request (seq too low)" };
  }
  return { ok: true, agentId, seq, agents, existing };
}

function touchAgent(agents, agentId, seq, extra = {}) {
  const now = new Date().toISOString();
  const prior = agents[agentId] || { registered_at: now, name: null, last_seq: 0 };
  agents[agentId] = {
    ...prior,
    ...extra,
    last_seq: Number.isFinite(seq) && seq > (prior.last_seq || 0) ? seq : prior.last_seq,
    last_heartbeat_at: now,
  };
  writeAgents(agents);
  return agents[agentId];
}

function isProcessAlive(pid) {
  if (!pid) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

// The runner's own exclusive lock file is the one authoritative "is a
// runner already active for this workspace" signal -- re-reading it here
// rather than tracking our own copy of the child's liveness avoids ever
// disagreeing with the engine about its own state.
function isRunnerActuallyRunning() {
  if (!fs.existsSync(runner.LOCK)) return false;
  try {
    const lock = JSON.parse(fs.readFileSync(runner.LOCK, "utf8"));
    return isProcessAlive(lock.pid);
  } catch {
    return true; // an unreadable lock file is still a lock -- fail safe, never double-spawn
  }
}

function readRunnerState() {
  try {
    return JSON.parse(fs.readFileSync(runner.RUNNER_STATE_FILE, "utf8"));
  } catch {
    return { state: "stopped", updated_at: null, pid: null, current_task_id: null };
  }
}

function readEvents(limit) {
  try {
    const lines = fs.readFileSync(runner.EVENTS_FILE, "utf8").trim().split("\n").filter(Boolean);
    const parsed = [];
    for (const line of lines) {
      try { parsed.push(JSON.parse(line)); } catch { /* skip a corrupt line, never crash the whole read */ }
    }
    return parsed.slice(-limit);
  } catch {
    return [];
  }
}

function writeCommand(command) {
  fs.mkdirSync(runner.CONTROL_DIR, { recursive: true });
  fs.writeFileSync(runner.COMMANDS_FILE, JSON.stringify({ command, requested_at: new Date().toISOString() }), "utf8");
}

function startRunnerEngine() {
  if (isRunnerActuallyRunning()) return { ok: false, reason: "a runner is already running for this workspace" };
  const child = cp.spawn(process.execPath, [path.join(__dirname, "claude_task_runner.js"), "--watch"], {
    cwd: runner.ROOT,
    detached: true, // survives a control-server restart -- the engine is independent of this thin control layer
    stdio: "ignore",
    windowsHide: true,
  });
  child.unref();
  return { ok: true, pid: child.pid };
}

// --- tiny HTTP helpers (no framework) ---------------------------------

function sendJson(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Content-Length": Buffer.byteLength(payload) });
  res.end(payload);
}

function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    let received = 0;
    let tooLarge = false;
    let settled = false;
    const chunks = [];
    const settleReject = (err) => { if (!settled) { settled = true; reject(err); } };
    req.on("data", (chunk) => {
      received += chunk.length;
      if (received > MAX_BODY_BYTES) {
        // Deliberately does NOT req.destroy() here -- destroying the
        // incoming message tears down the underlying socket before the
        // 413 response can be written back on it, turning a clean
        // rejection into a raw connection reset on the client side
        // (confirmed live: fetch() saw "fetch failed", not a 413). Just
        // stop accumulating and let the stream drain normally so the
        // response can still be sent.
        tooLarge = true;
        chunks.length = 0;
        return;
      }
      if (!tooLarge) chunks.push(chunk);
    });
    req.on("end", () => {
      if (tooLarge) return settleReject({ status: 413, message: "request body too large" });
      if (!chunks.length) return resolve({});
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString("utf8")));
      } catch {
        settleReject({ status: 400, message: "invalid JSON body" });
      }
    });
    req.on("error", () => settleReject({ status: 400, message: "error reading request body" }));
  });
}

const STATIC_CONTENT_TYPES = { ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8" };

function serveStatic(req, res, urlPath) {
  const rel = urlPath === "/" ? "index.html" : urlPath.replace(/^\/+/, "");
  const resolved = path.resolve(WEB_DIR, rel);
  const normalizedWebDir = path.resolve(WEB_DIR) + path.sep;
  if (!resolved.startsWith(normalizedWebDir) || !fs.existsSync(resolved) || fs.statSync(resolved).isDirectory()) {
    sendJson(res, 404, { error: "not found" });
    return;
  }
  const ext = path.extname(resolved);
  res.writeHead(200, { "Content-Type": STATIC_CONTENT_TYPES[ext] || "application/octet-stream" });
  fs.createReadStream(resolved).pipe(res);
}

// --- route handlers -----------------------------------------------------

function summarizeAgents() {
  const agents = readAgents();
  const now = Date.now();
  return Object.entries(agents).map(([agent_id, a]) => ({
    agent_id,
    name: a.name || null,
    online: isAgentOnline(a.last_heartbeat_at, now),
    last_heartbeat_at: a.last_heartbeat_at || null,
    status: a.status || null,
    executor: a.executor || null,
  }));
}

function handleStatus(req, res) {
  const state = readRunnerState();
  const tasks = runner.listTasks().map((x) => summarizeTask(x.task));
  const current = tasks.find((t) => t.id === state.current_task_id) || null;
  const agents = summarizeAgents();
  sendJson(res, 200, {
    runner_state: state.state,
    updated_at: state.updated_at,
    pid: state.pid,
    runner_actually_running: isRunnerActuallyRunning(),
    current_task: current,
    reason: state.reason || null,
    agents,
    any_agent_online: agents.some((a) => a.online),
  });
}

function handleTasks(req, res) {
  sendJson(res, 200, { tasks: runner.listTasks().map((x) => summarizeTask(x.task)) });
}

function handleTaskDetail(req, res, id) {
  const file = resolveTaskFile(runner.QUEUE, id, path);
  if (!file || !fs.existsSync(file)) return sendJson(res, 404, { error: `unknown task id: ${id}` });
  const task = runner.load(file);
  const handoff = runner.readHandoff(id);
  sendJson(res, 200, { task, handoff });
}

function handleEvents(req, res, query) {
  const limit = Math.min(Number(query.get("limit")) || EVENTS_LIMIT_DEFAULT, 2000);
  sendJson(res, 200, { events: readEvents(limit) });
}

function handleLogs(req, res, query) {
  const requested = query.get("file");
  if (!requested) return sendJson(res, 400, { error: "missing required 'file' query parameter" });
  // Logs are named <timestamp>-<taskId>-stage<N>.log directly under
  // LOG_DIR -- resolve and confirm containment exactly like a task file,
  // never accept a path that escapes LOG_DIR.
  const resolved = path.resolve(runner.LOG_DIR, requested);
  const normalizedLogDir = path.resolve(runner.LOG_DIR) + path.sep;
  if (!resolved.startsWith(normalizedLogDir) || !fs.existsSync(resolved)) {
    return sendJson(res, 404, { error: "unknown log file" });
  }
  const content = fs.readFileSync(resolved, "utf8");
  const lines = content.split("\n");
  const tail = lines.slice(-LOG_LINE_LIMIT).join("\n");
  sendJson(res, 200, { file: requested, truncated: lines.length > LOG_LINE_LIMIT, content: maskSecrets(tail) });
}

async function handleRunnerCommand(req, res, command) {
  let body = {};
  try { body = await readJsonBody(req); } catch (e) { return sendJson(res, e.status || 400, { error: e.message }); }
  if (command === "start") {
    // A registered Windows agent is always already polling once its own
    // Task Scheduler entry has launched it -- there is no local process to
    // spawn on this box anymore (Claude Code cannot run here). "Start"
    // then just means "if paused, resume" -- the SAME queued-command path
    // pause/resume/etc. already use, picked up by the agent's own
    // heartbeat poll rather than a local commands.json read. Only when NO
    // agent has ever registered does the original local-spawn behavior
    // apply, preserving this server's original (pre-agent) local-testing
    // use unchanged.
    if (Object.keys(readAgents()).length > 0) {
      writeCommand("resume");
      return sendJson(res, 202, { ok: true, command: "start", note: "no local process to start -- queued a resume for the Windows agent's next heartbeat poll" });
    }
    const result = startRunnerEngine();
    return sendJson(res, result.ok ? 200 : 409, result);
  }
  if (command === "emergency_stop" && body.confirm !== true) {
    return sendJson(res, 400, { error: "emergency_stop requires { confirm: true } in the request body" });
  }
  const state = readRunnerState().state;
  if (!commandAllowedInState(command, state)) {
    return sendJson(res, 409, { error: `'${command}' is not valid while the runner is '${state}'` });
  }
  writeCommand(command);
  sendJson(res, 202, { ok: true, command, note: "queued -- honored at the next safe point (emergency_stop may act immediately)" });
}

async function handleTaskAction(req, res, id, action) {
  let body = {};
  try { body = await readJsonBody(req); } catch (e) { return sendJson(res, e.status || 400, { error: e.message }); }
  const dangerousActions = new Set(["skip", "retry"]);
  if (dangerousActions.has(action) && body.confirm !== true) {
    return sendJson(res, 400, { error: `'${action}' requires { confirm: true } in the request body` });
  }
  const file = resolveTaskFile(runner.QUEUE, id, path);
  if (!file || !fs.existsSync(file)) return sendJson(res, 404, { error: `unknown task id: ${id}` });
  const task = runner.load(file);
  if (!taskActionAllowed(action, task.status)) {
    return sendJson(res, 409, { error: `'${action}' is not valid for a task currently '${task.status}'` });
  }
  const reason = typeof body.reason === "string" ? body.reason.slice(0, 500) : null;
  if (action === "hold") {
    task.result = { ...(task.result || {}), held_from_status: task.status };
    task.status = "held";
  } else if (action === "unhold") {
    task.status = (task.result && task.result.held_from_status) || "ready";
  } else if (action === "skip") {
    task.result = { ...(task.result || {}), skip_reason: reason };
    task.status = "skipped";
  } else if (action === "retry") {
    task.result = { ...(task.result || {}), sessions: [], retry_reason: reason };
    task.status = "ready";
  }
  runner.save(file, task);
  sendJson(res, 200, { ok: true, task_id: id, action, new_status: task.status });
}

async function handleReorder(req, res) {
  let body = {};
  try { body = await readJsonBody(req); } catch (e) { return sendJson(res, e.status || 400, { error: e.message }); }
  const order = body.order;
  if (!Array.isArray(order) || order.some((id) => !isSafeTaskId(id))) {
    return sendJson(res, 400, { error: "'order' must be an array of valid task ids" });
  }
  const all = runner.listTasks();
  const tasksById = Object.fromEntries(all.map((x) => [x.task.id, x.task]));
  const check = validateReorder(order, tasksById);
  if (!check.ok) return sendJson(res, 409, { error: check.reason });
  const fileById = Object.fromEntries(all.map((x) => [x.task.id, x.file]));
  order.forEach((id, index) => {
    const task = tasksById[id];
    task.queue_order = index;
    runner.save(fileById[id], task);
  });
  sendJson(res, 200, { ok: true, order });
}

// --- agent route handlers -------------------------------------------------

async function handleAgentRegister(req, res) {
  let body = {};
  try { body = await readJsonBody(req); } catch (e) { return sendJson(res, e.status || 400, { error: e.message }); }
  const tokenCheck = authenticateAgentToken(req);
  if (!tokenCheck.ok) return sendJson(res, tokenCheck.status, { error: tokenCheck.error });
  const agents = readAgents();
  // Idempotent: an agent restarting reuses its own previously-issued id
  // (if it still remembers it and the server still knows it) rather than
  // minting a new identity every reboot.
  const requested = typeof body.agent_id === "string" ? body.agent_id : null;
  const agentId = requested && agents[requested] ? requested : crypto.randomUUID();
  const name = typeof body.name === "string" ? body.name.slice(0, 100) : "windows-agent";
  touchAgent(agents, agentId, 0, { name, registered_at: (agents[agentId] && agents[agentId].registered_at) || new Date().toISOString() });
  sendJson(res, 200, { ok: true, agent_id: agentId });
}

async function handleAgentHeartbeat(req, res) {
  let body = {};
  try { body = await readJsonBody(req); } catch (e) { return sendJson(res, e.status || 400, { error: e.message }); }
  const auth = authenticateAgentRequest(req, body);
  if (!auth.ok) return sendJson(res, auth.status, { error: auth.error });
  touchAgent(auth.agents, auth.agentId, auth.seq, {
    executor: "claude",
    status: typeof body.status === "string" ? body.status.slice(0, 100) : null,
  });
  // The first heartbeat from any agent is this server's own signal that
  // the runner is alive -- mirrors what the old local main() loop did with
  // its own transition("start", ...) at startup, just now driven by the
  // remote agent's heartbeat instead of a local process boot.
  if (readRunnerState().state === "stopped") {
    runner.transition("start", { reason: `agent ${auth.agentId} heartbeat` });
  }
  let pending = null;
  try { pending = JSON.parse(fs.readFileSync(runner.COMMANDS_FILE, "utf8")); } catch { /* none pending */ }
  sendJson(res, 200, { ok: true, pending_command: pending });
}

async function handleAgentClaim(req, res) {
  let body = {};
  try { body = await readJsonBody(req); } catch (e) { return sendJson(res, e.status || 400, { error: e.message }); }
  const auth = authenticateAgentRequest(req, body);
  if (!auth.ok) return sendJson(res, auth.status, { error: auth.error });
  touchAgent(auth.agents, auth.agentId, auth.seq);

  // Pull first so any human /automation action (hold/skip/reorder -- each
  // already committed by this same server) is visible before deciding
  // what's next; never hand out a task based on state that might already
  // be stale.
  runner.run("git", ["pull", "--ff-only", "origin", "main"]);

  const selected = runner.nextTask();
  if (!selected) return sendJson(res, 200, { task: null });

  const current = runner.load(selected.file);
  const preClaimStatus = current.status;
  current.status = "claimed";
  current.result = { ...(current.result || {}), pre_claim_status: preClaimStatus, agent_lease: buildLease(auth.agentId, AGENT_LEASE_MINUTES_DEFAULT) };
  runner.save(selected.file, current);
  const commitResult = runner.commitRunnerState(selected.file, current.id, `claimed by agent ${auth.agentId}`);
  if (!commitResult.ok) {
    // Never hand out a task the server couldn't actually persist as
    // claimed -- a concurrent claim (a second agent, or a retry) could
    // otherwise pick up the exact same task from a dirty/uncommitted disk
    // state that looks claimed locally but was never durably recorded.
    current.status = preClaimStatus;
    delete current.result.agent_lease;
    runner.save(selected.file, current);
    return sendJson(res, 500, { error: `could not commit claim: ${commitResult.reason}` });
  }
  runner.transition("task_claimed", { reason: `claimed by agent ${auth.agentId}`, taskId: current.id });
  sendJson(res, 200, { task: current });
}

async function handleAgentReportState(req, res) {
  let body = {};
  try { body = await readJsonBody(req); } catch (e) { return sendJson(res, e.status || 400, { error: e.message }); }
  const auth = authenticateAgentRequest(req, body);
  if (!auth.ok) return sendJson(res, auth.status, { error: auth.error });
  touchAgent(auth.agents, auth.agentId, auth.seq);
  const taskId = typeof body.task_id === "string" ? body.task_id : null;
  if (taskId && !isSafeTaskId(taskId)) return sendJson(res, 400, { error: "invalid task_id" });
  const event = typeof body.event === "string" ? body.event : null;
  if (!event) return sendJson(res, 400, { error: "missing event" });
  const reason = typeof body.reason === "string" ? body.reason.slice(0, 500) : null;
  const transitioned = runner.transition(event, { reason, taskId, sessionId: auth.agentId });
  sendJson(res, 200, { ok: true, transitioned });
}

async function handleAgentReportCheckpoint(req, res) {
  let body = {};
  try { body = await readJsonBody(req); } catch (e) { return sendJson(res, e.status || 400, { error: e.message }); }
  const auth = authenticateAgentRequest(req, body);
  if (!auth.ok) return sendJson(res, auth.status, { error: auth.error });
  touchAgent(auth.agents, auth.agentId, auth.seq);
  const taskId = typeof body.task_id === "string" ? body.task_id : null;
  if (taskId && !isSafeTaskId(taskId)) return sendJson(res, 400, { error: "invalid task_id" });
  runner.appendEvent({
    ts: new Date().toISOString(),
    event: "checkpoint",
    previous_state: null,
    new_state: null,
    reason: typeof body.summary === "string" ? body.summary.slice(0, 500) : null,
    task_id: taskId,
    session_id: auth.agentId,
  });
  sendJson(res, 200, { ok: true });
}

async function handleAgentReportResult(req, res) {
  let body = {};
  try { body = await readJsonBody(req); } catch (e) { return sendJson(res, e.status || 400, { error: e.message }); }
  const auth = authenticateAgentRequest(req, body);
  if (!auth.ok) return sendJson(res, auth.status, { error: auth.error });
  touchAgent(auth.agents, auth.agentId, auth.seq);
  const taskId = typeof body.task_id === "string" ? body.task_id : null;
  if (!taskId || !isSafeTaskId(taskId)) return sendJson(res, 400, { error: "invalid task_id" });
  const outcome = typeof body.outcome === "string" ? body.outcome : null;
  const validOutcomes = new Set(["done", "failed", "blocked", "waiting_for_limit", "waiting_for_auth", "checkpointing", "interrupted"]);
  if (!validOutcomes.has(outcome)) return sendJson(res, 400, { error: `invalid outcome: ${outcome}` });

  // The agent's own commit (pushed from its local checkout) is the
  // authoritative record of what actually happened -- pull it in now so
  // this server's copy (and therefore /automation) reflects the real
  // task file, not a value trusted blindly from the HTTP body.
  runner.run("git", ["pull", "--ff-only", "origin", "main"]);

  const eventByOutcome = {
    done: "safe_point_reached_idle",
    blocked: "owner_gate_blocked",
    checkpointing: "safe_point_reached",
    waiting_for_limit: "rate_limited",
    waiting_for_auth: "auth_required",
    failed: "task_failed",
    interrupted: "emergency_stop_command",
  };
  runner.transition(eventByOutcome[outcome] || "task_failed", {
    reason: typeof body.summary === "string" ? body.summary.slice(0, 500) : outcome,
    taskId,
    sessionId: auth.agentId,
  });
  sendJson(res, 200, { ok: true });
}

async function handleAgentRequestDeploy(req, res) {
  let body = {};
  try { body = await readJsonBody(req); } catch (e) { return sendJson(res, e.status || 400, { error: e.message }); }
  const auth = authenticateAgentRequest(req, body);
  if (!auth.ok) return sendJson(res, auth.status, { error: auth.error });
  touchAgent(auth.agents, auth.agentId, auth.seq);

  const taskId = body.task_id;
  const commitSha = body.commit_sha;
  if (!isSafeTaskId(taskId)) return sendJson(res, 400, { error: "invalid task_id" });
  if (typeof commitSha !== "string" || !/^[0-9a-f]{7,40}$/i.test(commitSha)) {
    return sendJson(res, 400, { error: "invalid commit_sha" });
  }

  // Never trust the agent's claim about what it pushed -- confirm the
  // commit is genuinely reachable from origin/main before touching
  // production at all. Only ever fixed, hardcoded git/systemctl
  // invocations below -- no shell string ever comes from the agent.
  runner.run("git", ["fetch", "origin", "main"]);
  const originHead = runner.run("git", ["rev-parse", "origin/main"]).stdout.trim();
  const ancestorCheck = runner.run("git", ["merge-base", "--is-ancestor", commitSha, "origin/main"]);
  if (ancestorCheck.status !== 0) {
    return sendJson(res, 409, { error: `commit ${commitSha} is not an ancestor of origin/main (${originHead}) -- refusing to deploy` });
  }

  const pull = cp.spawnSync("sudo", ["-u", PRODUCTION_USER, "git", "-C", PRODUCTION_DIR, "pull", "--ff-only", "origin", "main"], { encoding: "utf8" });
  if (pull.status !== 0) return sendJson(res, 500, { error: `production pull failed: ${(pull.stderr || "").trim()}` });
  const prodHeadResult = cp.spawnSync("sudo", ["-u", PRODUCTION_USER, "git", "-C", PRODUCTION_DIR, "rev-parse", "HEAD"], { encoding: "utf8" });
  const productionHead = (prodHeadResult.stdout || "").trim();
  const restart = cp.spawnSync("systemctl", ["restart", PRODUCTION_SERVICE], { encoding: "utf8" });
  if (restart.status !== 0) return sendJson(res, 500, { error: `service restart failed: ${(restart.stderr || "").trim()}`, production_head: productionHead });

  sendJson(res, 200, { ok: true, production_head: productionHead, origin_head: originHead, task_id: taskId });
}

// --- router --------------------------------------------------------------

async function router(req, res) {
  const remote = req.socket.remoteAddress;
  if (remote !== "127.0.0.1" && remote !== "::1" && remote !== "::ffff:127.0.0.1") {
    res.writeHead(403); res.end(); return; // defense in depth beyond the HOST bind itself
  }

  const url = new URL(req.url, `http://${HOST}`);
  const parts = url.pathname.split("/").filter(Boolean);

  try {
    if (req.method === "GET" && url.pathname === "/api/status") return handleStatus(req, res);
    if (req.method === "GET" && url.pathname === "/api/tasks") return handleTasks(req, res);
    if (req.method === "GET" && parts[0] === "api" && parts[1] === "tasks" && parts.length === 3) return handleTaskDetail(req, res, parts[2]);
    if (req.method === "GET" && url.pathname === "/api/events") return handleEvents(req, res, url.searchParams);
    if (req.method === "GET" && url.pathname === "/api/logs") return handleLogs(req, res, url.searchParams);

    if (req.method === "POST" && parts[0] === "api" && parts[1] === "runner" && parts.length === 3) {
      const command = { start: "start", pause: "pause", resume: "resume", "stop-after-stage": "stop_after_stage", "emergency-stop": "emergency_stop" }[parts[2]];
      if (!command) return sendJson(res, 404, { error: "unknown runner command" });
      if (command !== "start" && !isValidCommand(command)) return sendJson(res, 400, { error: "invalid command" });
      return await handleRunnerCommand(req, res, command);
    }
    if (req.method === "POST" && parts[0] === "api" && parts[1] === "tasks" && parts.length === 4 && ["hold", "unhold", "retry", "skip"].includes(parts[3])) {
      if (!isSafeTaskId(parts[2])) return sendJson(res, 400, { error: "invalid task id" });
      return await handleTaskAction(req, res, parts[2], parts[3]);
    }
    if (req.method === "POST" && url.pathname === "/api/tasks/reorder") return await handleReorder(req, res);

    if (req.method === "POST" && url.pathname === "/api/agent/register") return await handleAgentRegister(req, res);
    if (req.method === "POST" && url.pathname === "/api/agent/heartbeat") return await handleAgentHeartbeat(req, res);
    if (req.method === "POST" && url.pathname === "/api/agent/claim") return await handleAgentClaim(req, res);
    if (req.method === "POST" && url.pathname === "/api/agent/report-state") return await handleAgentReportState(req, res);
    if (req.method === "POST" && url.pathname === "/api/agent/report-checkpoint") return await handleAgentReportCheckpoint(req, res);
    if (req.method === "POST" && url.pathname === "/api/agent/report-result") return await handleAgentReportResult(req, res);
    if (req.method === "POST" && url.pathname === "/api/agent/request-deploy") return await handleAgentRequestDeploy(req, res);

    if (req.method === "GET") return serveStatic(req, res, url.pathname);
    sendJson(res, 404, { error: "not found" });
  } catch (error) {
    sendJson(res, 500, { error: "internal error", detail: error.message });
  }
}

// Returns {ok:true} once this process holds CONTROL_LOCK, or {ok:false,
// reason, existingPid} if another live control server already holds it --
// never process.exit()s itself, so callers (including tests) decide what
// to do with the result. Exactly one control server per workspace, mirroring
// the runner engine's own exclusive lock file.
function acquireControlLock() {
  try {
    fs.mkdirSync(path.dirname(CONTROL_LOCK), { recursive: true });
    fs.writeFileSync(CONTROL_LOCK, JSON.stringify({ pid: process.pid, created_at: new Date().toISOString() }), { flag: "wx" });
    return { ok: true };
  } catch {
    let existingPid = null;
    try { existingPid = JSON.parse(fs.readFileSync(CONTROL_LOCK, "utf8")).pid; } catch { /* ignore */ }
    if (existingPid && isProcessAlive(existingPid)) {
      return { ok: false, reason: `a control server is already running (pid ${existingPid})`, existingPid };
    }
    // Stale lock from a crashed prior instance -- safe to reclaim.
    fs.writeFileSync(CONTROL_LOCK, JSON.stringify({ pid: process.pid, created_at: new Date().toISOString() }), "utf8");
    return { ok: true, reclaimed: true };
  }
}

function releaseControlLock() {
  try { fs.unlinkSync(CONTROL_LOCK); } catch { /* already gone */ }
}

// opts.port lets tests bind an OS-assigned ephemeral port (0) instead of
// the fixed default, so parallel test runs never collide on a real port.
// opts.attachSignalHandlers (default true) is turned off by tests -- every
// call otherwise adds a NEW pair of process-level SIGINT/SIGTERM listeners
// that is never removed, which both warns (MaxListenersExceededWarning)
// and keeps the process from exiting cleanly across repeated start() calls
// in one test run; the real CLI entrypoint below only ever calls start() once.
function start(opts = {}) {
  const lock = acquireControlLock();
  if (!lock.ok) return { ok: false, reason: lock.reason };
  const server = http.createServer((req, res) => { router(req, res); });
  const port = opts.port ?? PORT;
  return new Promise((resolve) => {
    server.listen(port, HOST, () => {
      console.log(`Ego OS runner control server listening on http://${HOST}:${server.address().port} (loopback only)`);
      let cleanupHandlers = null;
      if (opts.attachSignalHandlers !== false) {
        const cleanup = () => { releaseControlLock(); process.exit(0); };
        process.on("SIGINT", cleanup);
        process.on("SIGTERM", cleanup);
        cleanupHandlers = () => { process.off("SIGINT", cleanup); process.off("SIGTERM", cleanup); };
      }
      resolve({ ok: true, server, port: server.address().port, removeSignalHandlers: cleanupHandlers || (() => {}) });
    });
  });
}

module.exports = {
  start, router, isRunnerActuallyRunning, readRunnerState, readEvents, writeCommand, startRunnerEngine,
  acquireControlLock, releaseControlLock,
  getOrCreateAgentToken, readAgents, writeAgents, touchAgent, authenticateAgentToken, authenticateAgentRequest, summarizeAgents,
  HOST, PORT, MAX_BODY_BYTES, WEB_DIR, CONTROL_LOCK, AGENT_TOKEN_FILE, AGENTS_FILE,
};

if (require.main === module) {
  start().then((result) => {
    if (!result.ok) { console.error(`STOP: ${result.reason}`); process.exit(1); }
  });
}
