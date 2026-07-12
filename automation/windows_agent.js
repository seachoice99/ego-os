#!/usr/bin/env node
"use strict";

/**
 * Windows Runner Agent -- the piece of SERVER-RUNNER-DARK-UI that actually
 * runs Claude Code, since it cannot run on the production VPS (confirmed
 * external blocker). The VPS keeps the queue, the state machine, and
 * /automation; this agent is a thin outbound-only HTTPS client that claims
 * one task at a time and reuses claude_task_runner.js's own execute()
 * UNMODIFIED to actually run it -- every stage/commit/push/pause/
 * emergency-stop/fatal-classification rule that already exists keeps
 * working exactly as before. This file adds no new task-execution logic
 * of its own; it only sources the task from the VPS instead of a local
 * queue directory, and reports back over HTTPS instead of the local
 * commands.json file alone.
 *
 * Never accepts an inbound connection and never opens a local port -- the
 * only network activity here is outbound POSTs to EGO_OS_AGENT_SERVER_URL.
 */

const fs = require("fs");
const path = require("path");

const runner = require("./claude_task_runner.js");

const SERVER_URL = (process.env.EGO_OS_AGENT_SERVER_URL || "https://os.fiveseven.ru").replace(/\/+$/, "");
const AGENT_TOKEN = process.env.EGO_OS_AGENT_TOKEN || "";
const AGENT_NAME = process.env.EGO_OS_AGENT_NAME || "windows-desktop";
const HEARTBEAT_INTERVAL_MS = Number(process.env.EGO_OS_AGENT_HEARTBEAT_MS) || 10000;
const CLAIM_INTERVAL_MS = Number(process.env.EGO_OS_AGENT_CLAIM_INTERVAL_MS) || 15000;
const MAX_TURNS = Number(process.env.EGO_OS_AGENT_MAX_TURNS) || 80;
const TIMEOUT_MINUTES = Number(process.env.EGO_OS_AGENT_TIMEOUT_MINUTES) || 90;

const AGENT_LOCK = path.join(path.dirname(runner.LOCK), "ego-os-windows-agent.lock");
const AGENT_ID_FILE = path.join(runner.CONTROL_DIR, "agent_id.txt");

// --- seq: a strictly-increasing per-process counter, seeded from the
// clock so a fresh process restart's first value is (in every realistic
// case) higher than the last one the server ever saw -- the server-side
// replay check only requires "always increasing within what it's seen",
// never a specific starting point.
let seqCounter = Date.now();
function nextSeq() { return ++seqCounter; }

function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

async function agentPost(operation, body) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20000);
  try {
    const res = await fetch(`${SERVER_URL}/agent/${operation}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${AGENT_TOKEN}` },
      body: JSON.stringify({ ...body, seq: nextSeq() }),
      signal: controller.signal,
    });
    let data = null;
    try { data = await res.json(); } catch { /* no body */ }
    return { ok: res.ok, status: res.status, data };
  } catch (error) {
    return { ok: false, status: null, data: null, error: error.message };
  } finally {
    clearTimeout(timeout);
  }
}

function loadOrCreateAgentId() {
  try {
    const existing = fs.readFileSync(AGENT_ID_FILE, "utf8").trim();
    if (existing) return existing;
  } catch { /* not created yet */ }
  return null; // registered lazily on first successful /agent/register call
}

function saveAgentId(id) {
  fs.mkdirSync(path.dirname(AGENT_ID_FILE), { recursive: true });
  fs.writeFileSync(AGENT_ID_FILE, id, "utf8");
}

let agentId = null;

async function ensureRegistered() {
  if (agentId) return agentId;
  const known = loadOrCreateAgentId();
  const result = await agentPost("register", { agent_id: known, name: AGENT_NAME });
  if (!result.ok || !result.data || !result.data.agent_id) {
    throw new Error(`agent registration failed: ${result.status} ${(result.data && result.data.error) || result.error || ""}`);
  }
  agentId = result.data.agent_id;
  saveAgentId(agentId);
  return agentId;
}

// --- mirror the server's pending command into the SAME local
// commands.json file execute()/runClaude() already poll on their own --
// no change to that existing logic needed at all.
function mirrorPendingCommand(pending) {
  if (!pending || !pending.command) return;
  fs.mkdirSync(runner.CONTROL_DIR, { recursive: true });
  fs.writeFileSync(runner.COMMANDS_FILE, JSON.stringify(pending), "utf8");
}

async function heartbeat(status) {
  const id = await ensureRegistered();
  const result = await agentPost("heartbeat", { agent_id: id, status });
  if (result.ok && result.data) mirrorPendingCommand(result.data.pending_command);
  return result;
}

async function reportState(event, taskId, reason) {
  const id = await ensureRegistered();
  return agentPost("report-state", { agent_id: id, event, task_id: taskId, reason });
}

async function reportCheckpoint(taskId, summary) {
  const id = await ensureRegistered();
  return agentPost("report-checkpoint", { agent_id: id, task_id: taskId, summary });
}

async function reportResult(taskId, outcome, summary) {
  const id = await ensureRegistered();
  return agentPost("report-result", { agent_id: id, task_id: taskId, outcome, summary });
}

async function claim() {
  const id = await ensureRegistered();
  return agentPost("claim", { agent_id: id });
}

const KNOWN_OUTCOMES = new Set(["done", "failed", "blocked", "waiting_for_limit", "waiting_for_auth", "checkpointing", "interrupted"]);
function mapOutcome(status, execOk) {
  if (KNOWN_OUTCOMES.has(status)) return status;
  return execOk ? "done" : "failed";
}

async function runClaimedTask(claimedTask) {
  console.log(`CLAIMED ${claimedTask.id} -- ${claimedTask.title}`);
  runner.run("git", ["pull", "--ff-only", "origin", "main"]);
  const localFile = path.join(runner.QUEUE, `${claimedTask.id}.yaml`);
  if (!fs.existsSync(localFile)) {
    console.error(`STOP ${claimedTask.id}: local task file missing after claim+pull -- refusing to fabricate one`);
    await reportResult(claimedTask.id, "failed", "local task file missing after claim and git pull");
    return;
  }
  const localTask = runner.load(localFile);
  await reportState("task_claimed", claimedTask.id, "agent starting execution");
  await reportCheckpoint(claimedTask.id, "starting execute()");

  const ok = await runner.execute({ file: localFile, task: localTask }, MAX_TURNS, TIMEOUT_MINUTES);

  const finalTask = runner.load(localFile);
  const outcome = mapOutcome(finalTask.status, ok);
  console.log(`RESULT ${claimedTask.id}: ${outcome}`);
  await reportResult(claimedTask.id, outcome, finalTask.result && finalTask.result.summary);
}

// --- single-instance lock, matching the existing runner's own pattern --
function acquireAgentLock() {
  try {
    fs.mkdirSync(path.dirname(AGENT_LOCK), { recursive: true });
    fs.writeFileSync(AGENT_LOCK, JSON.stringify({ pid: process.pid, created_at: new Date().toISOString() }), { flag: "wx" });
    return { ok: true };
  } catch {
    let existingPid = null;
    try { existingPid = JSON.parse(fs.readFileSync(AGENT_LOCK, "utf8")).pid; } catch { /* ignore */ }
    if (existingPid) {
      try { process.kill(existingPid, 0); return { ok: false, reason: `already running (pid ${existingPid})` }; } catch { /* dead, stale lock */ }
    }
    fs.writeFileSync(AGENT_LOCK, JSON.stringify({ pid: process.pid, created_at: new Date().toISOString() }), "utf8");
    return { ok: true, reclaimed: true };
  }
}

function releaseAgentLock() {
  try { fs.unlinkSync(AGENT_LOCK); } catch { /* already gone */ }
}

// --- startup safety: never run against someone else's uncommitted work --
function workingTreeIsClean() {
  const status = runner.run("git", ["status", "--porcelain"]);
  return status.status === 0 && status.stdout.trim() === "";
}

let stopping = false;

async function heartbeatLoop() {
  while (!stopping) {
    try {
      await heartbeat(currentStatusLabel);
    } catch (error) {
      console.error(`heartbeat failed: ${error.message}`);
    }
    await sleep(HEARTBEAT_INTERVAL_MS);
  }
}

let currentStatusLabel = "idle";
let currentlyBusy = false;

async function claimLoop() {
  while (!stopping) {
    if (!currentlyBusy) {
      const pending = runner.readPendingCommand();
      const blocked = pending && (pending.command === "pause" || pending.command === "stop_after_stage");
      if (!blocked) {
        if (!workingTreeIsClean()) {
          console.error("STOP: working tree is not clean (uncommitted changes present) -- refusing to claim a task until it is");
        } else {
          const result = await claim();
          if (result.ok && result.data && result.data.task) {
            currentlyBusy = true;
            currentStatusLabel = "running";
            try {
              await runClaimedTask(result.data.task);
            } finally {
              currentlyBusy = false;
              currentStatusLabel = "idle";
            }
          } else if (!result.ok) {
            console.error(`claim failed: ${result.status} ${(result.data && result.data.error) || result.error || ""}`);
          }
        }
      }
    }
    await sleep(CLAIM_INTERVAL_MS);
  }
}

async function main() {
  if (!AGENT_TOKEN) {
    console.error("STOP: EGO_OS_AGENT_TOKEN is not set -- refusing to start with no credential");
    return 1;
  }
  const lock = acquireAgentLock();
  if (!lock.ok) {
    console.error(`STOP: ${lock.reason}`);
    return 1;
  }
  if (!workingTreeIsClean()) {
    console.error(`STOP: ${runner.ROOT} has uncommitted changes -- refusing to start against someone else's in-progress work. Commit, stash, or resolve it first.`);
    releaseAgentLock();
    return 1;
  }
  console.log(`Ego OS Windows Runner Agent starting -- server: ${SERVER_URL}, checkout: ${runner.ROOT}`);
  await ensureRegistered();
  console.log(`Registered as agent_id ${agentId}`);

  const cleanup = () => {
    stopping = true;
    releaseAgentLock();
    process.exit(0);
  };
  process.on("SIGINT", cleanup);
  process.on("SIGTERM", cleanup);

  await Promise.all([heartbeatLoop(), claimLoop()]);
  return 0;
}

module.exports = {
  main, heartbeat, claim, reportState, reportCheckpoint, reportResult, ensureRegistered,
  mirrorPendingCommand, workingTreeIsClean, acquireAgentLock, releaseAgentLock, mapOutcome, nextSeq,
  AGENT_LOCK, AGENT_ID_FILE, SERVER_URL,
};

if (require.main === module) {
  main().then((code) => { if (code) process.exitCode = code; });
}
