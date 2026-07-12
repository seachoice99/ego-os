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
} = require("./runner_control.js");

const HOST = "127.0.0.1";
const PORT = Number(process.env.EGO_OS_CONTROL_PORT) || 4756;
const MAX_BODY_BYTES = 64 * 1024;
const WEB_DIR = process.env.EGO_OS_CONTROL_WEB_DIR || path.join(__dirname, "web");
const CONTROL_LOCK = process.env.EGO_OS_CONTROL_LOCK || path.join(path.dirname(runner.LOCK), "ego-os-control-server.lock");
const LOG_LINE_LIMIT = 500;
const EVENTS_LIMIT_DEFAULT = 200;

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

function handleStatus(req, res) {
  const state = readRunnerState();
  const tasks = runner.listTasks().map((x) => summarizeTask(x.task));
  const current = tasks.find((t) => t.id === state.current_task_id) || null;
  sendJson(res, 200, {
    runner_state: state.state,
    updated_at: state.updated_at,
    pid: state.pid,
    runner_actually_running: isRunnerActuallyRunning(),
    current_task: current,
    reason: state.reason || null,
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
  HOST, PORT, MAX_BODY_BYTES, WEB_DIR, CONTROL_LOCK,
};

if (require.main === module) {
  start().then((result) => {
    if (!result.ok) { console.error(`STOP: ${result.reason}`); process.exit(1); }
  });
}
