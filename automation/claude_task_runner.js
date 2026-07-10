#!/usr/bin/env node
"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const cp = require("child_process");

const ROOT = path.resolve(__dirname, "..");
const QUEUE = path.join(ROOT, "tasks", "queue");
const LOCAL = process.env.LOCALAPPDATA || os.homedir();
const LOCK = path.join(LOCAL, "ego-os-claude-runner.lock");
const LOG_DIR = path.join(LOCAL, "EgoOS", "claude-runner", "logs");
const CLAUDE = path.join(process.env.APPDATA || "", "npm", "claude.cmd");
const OWNER_ONLY = new Set(["destructive_data", "irreversible_migration", "payments", "secrets", "external_infrastructure"]);

function run(file, args, timeout = 60000) {
  return cp.spawnSync(file, args, { cwd: ROOT, encoding: "utf8", timeout, windowsHide: true });
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

function preflight() {
  const status = run("git", ["status", "--porcelain"]);
  if (status.status !== 0 || status.stdout.trim()) return [false, "working tree is not clean"];
  const fetch = run("git", ["fetch", "origin", "main"]);
  if (fetch.status !== 0) return [false, fetch.stderr.trim() || "git fetch failed"];
  const head = run("git", ["rev-parse", "HEAD"]).stdout.trim();
  const origin = run("git", ["rev-parse", "origin/main"]).stdout.trim();
  const branch = run("git", ["branch", "--show-current"]).stdout.trim();
  if (branch !== "main" || head !== origin) return [false, "local main must exactly match origin/main"];
  if (!fs.existsSync(CLAUDE)) return [false, `Claude CLI not found at ${CLAUDE}`];
  return [true, head];
}

function nextTask() {
  const rank = { P0: 0, P1: 1, P2: 2, P3: 3 };
  const tasks = fs.readdirSync(QUEUE).filter(x => x.endsWith(".yaml") && !x.startsWith("_")).map(name => {
    const file = path.join(QUEUE, name); return { file, task: load(file) };
  }).filter(x => x.task.status === "ready");
  tasks.sort((a, b) => (rank[a.task.priority] ?? 99) - (rank[b.task.priority] ?? 99) || a.file.localeCompare(b.file));
  return tasks[0] || null;
}

function makePrompt(file, task, head) {
  const criteria = task.acceptance.map(x => `- ${x}`).join("\n");
  const allowed = (task.allowed_paths || ["task-required repository paths"]).map(x => `- ${x}`).join("\n");
  const forbidden = (task.forbidden_paths || []).map(x => `- ${x}`).join("\n") || "- none beyond repository rules";
  const deploy = task.release === "automatic";
  return `You are the autonomous implementation and release worker for Ego OS.
Read CLAUDE.md and AI_ONBOARDING.md first. Work only on ${task.id} in ${path.relative(ROOT, file).replaceAll("\\", "/")}.
Starting commit: ${head}

TITLE: ${task.title}

PROMPT:
${task.prompt}

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
6. Tests must pass. Commit message starts with '${task.id}:'; push main to origin/main.
7. ${deploy ? "Deploy using DEPLOYMENT.md and require active service plus HTTP 200." : "Do not deploy."}
8. On any unsafe or incomplete step set status failed with the exact blocker and stop. Never claim success without evidence.

You are authorized for task-scoped edits, tests, commit, push main, and ${deploy ? "Ego OS deploy" : "no deployment"}. Owner-only exclusions remain hard stops.`;
}

function execute(selected, maxTurns, timeoutMinutes) {
  const { file, task } = selected;
  const risks = new Set(task.risks || []);
  if ([...risks].some(x => OWNER_ONLY.has(x)) && task.owner_approved !== true) {
    task.status = "blocked"; task.result = { error: "Owner-only risk lacks owner_approved: true" }; save(file, task); return false;
  }
  if (!["automatic", "no_deploy"].includes(task.release)) throw new Error("release must be automatic or no_deploy");
  const [ok, detail] = preflight();
  if (!ok) { console.error(`STOP: ${detail}`); return false; }
  task.status = "in_progress"; task.started_at = new Date().toISOString(); save(file, task);
  fs.mkdirSync(LOG_DIR, { recursive: true });
  const stamp = new Date().toISOString().replaceAll(/[:.]/g, "-");
  const logFile = path.join(LOG_DIR, `${stamp}-${task.id}.log`);
  console.log(`RUNNING ${task.id} — ${logFile}`);
  const output = run(CLAUDE, ["-p", makePrompt(file, task, detail), "--output-format", "stream-json", "--verbose",
    "--max-turns", String(maxTurns), "--dangerously-skip-permissions"], timeoutMinutes * 60000);
  fs.writeFileSync(logFile, (output.stdout || "") + (output.stderr || ""), "utf8");
  const current = load(file);
  const clean = run("git", ["status", "--porcelain"]).stdout.trim() === "";
  if (output.status === 0 && current.status === "done" && clean) { console.log(`DONE ${task.id}`); return true; }
  current.status = "failed";
  current.result = { ...(current.result || {}), runner_error: "Claude did not finish cleanly", log: logFile, finished_at: new Date().toISOString() };
  save(file, current); console.error(`FAILED ${task.id} — queue stopped`); return false;
}

function main() {
  const args = process.argv.slice(2);
  const watch = args.includes("--watch"), dry = args.includes("--dry-run");
  const value = (name, fallback) => { const i = args.indexOf(name); return i >= 0 ? Number(args[i + 1]) : fallback; };
  const interval = value("--interval", 60), maxTurns = value("--max-turns", 80), timeout = value("--timeout-minutes", 90);
  try { fs.writeFileSync(LOCK, JSON.stringify({ pid: process.pid, created_at: new Date().toISOString() }), { flag: "wx" }); }
  catch { console.error(`STOP: runner lock exists: ${LOCK}`); return 1; }
  try {
    while (true) {
      const selected = nextTask();
      if (!selected) { if (!watch) { console.log("No ready tasks."); return 0; } Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, interval * 1000); continue; }
      if (dry) { console.log(`NEXT ${selected.task.id}: ${selected.task.title}`); return 0; }
      if (!execute(selected, maxTurns, timeout)) return 1;
      if (!watch) return 0;
    }
  } finally { if (fs.existsSync(LOCK)) fs.unlinkSync(LOCK); }
}

process.exitCode = main();
