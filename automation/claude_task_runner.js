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
// Overridable so tests can point the runner at a fake/mock executable
// instead of ever spawning a real Claude Code process.
const CLAUDE = process.env.EGO_OS_RUNNER_CLAUDE_PATH || path.join(process.env.APPDATA || "", "npm", "claude.cmd");
const OWNER_ONLY = new Set(["destructive_data", "irreversible_migration", "payments", "secrets", "external_infrastructure"]);

function run(file, args, timeout = 60000, opts = {}) {
  return cp.spawnSync(file, args, { cwd: ROOT, encoding: "utf8", timeout, windowsHide: true, ...opts });
}

// `taskkill /F /T /PID X` is a documented-unreliable heuristic on
// Windows for anything beyond a shallow tree -- proven live by this
// module's own tests: it reliably killed the direct child (cmd.exe) but
// left a grandchild several process-layers deep (cmd.exe -> claude.cmd ->
// claude.exe, or in tests cmd.exe -> node -> node) still running. Walk
// the real process tree ourselves via WMI's Win32_Process (its own
// ParentProcessId is the same mechanism that correctly diagnosed this
// defect) and kill every descendant explicitly, rather than trusting
// /T's single heuristic pass to cascade correctly.
function killProcessTree(pid) {
  if (!pid) return;
  const query = cp.spawnSync("powershell", [
    "-NoProfile", "-Command",
    "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId | ConvertTo-Json -Compress",
  ], { encoding: "utf8", windowsHide: true });
  let processes = [];
  try {
    const parsed = JSON.parse(query.stdout || "[]");
    processes = Array.isArray(parsed) ? parsed : [parsed];
  } catch {
    processes = [];
  }
  const byParent = new Map();
  for (const p of processes) {
    if (p.ParentProcessId == null) continue;
    const list = byParent.get(p.ParentProcessId) || [];
    list.push(p.ProcessId);
    byParent.set(p.ParentProcessId, list);
  }
  const toKill = [];
  const stack = [Number(pid)];
  const seen = new Set();
  while (stack.length) {
    const current = stack.pop();
    if (seen.has(current)) continue;
    seen.add(current);
    toKill.push(current);
    for (const child of byParent.get(current) || []) stack.push(child);
  }
  for (const targetPid of toKill) {
    cp.spawnSync("taskkill", ["/F", "/PID", String(targetPid)], { windowsHide: true });
  }
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
function runClaude(promptText, args, timeoutMs) {
  return new Promise((resolve) => {
    const child = cp.spawn(CLAUDE, args, { cwd: ROOT, shell: true, windowsHide: true });
    let stdout = "", stderr = "", timedOut = false, settled = false;
    if (child.stdout) child.stdout.on("data", (d) => { stdout += d.toString(); });
    if (child.stderr) child.stderr.on("data", (d) => { stderr += d.toString(); });

    const timer = setTimeout(() => {
      timedOut = true;
      killProcessTree(child.pid);
    }, timeoutMs);

    function finish(result) {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
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
      finish({ status, signal: timedOut ? (signal || "SIGTERM") : signal, stdout, stderr, pid: child.pid });
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
  if (!fs.existsSync(CLAUDE)) return [false, `Claude CLI not found at ${CLAUDE}`];
  // Confirms the .cmd is actually invokable this way (shell:true, absolute
  // path, no untrusted content in argv) before committing to a task run --
  // catches an EINVAL/quoting regression before it burns a task attempt.
  const probe = await runClaude("", ["--version"], 15000);
  if (probe.status !== 0 || probe.error) return [false, `Claude CLI probe failed: ${(probe.error && probe.error.message) || probe.stderr || "non-zero exit"}`];
  return [true, head];
}

function nextTask() {
  const rank = { P0: 0, P1: 1, P2: 2, P3: 3 };
  const now = Date.now();
  const tasks = fs.readdirSync(QUEUE).filter(x => x.endsWith(".yaml") && !x.startsWith("_")).map(name => {
    const file = path.join(QUEUE, name); return { file, task: load(file) };
  }).filter(x => {
    if (x.task.status === "ready") return true;
    // A task parked waiting_for_limit becomes eligible again once its own
    // recorded retry_after has passed -- never sooner, so the runner never
    // spends an attempt (or paid usage credits) trying to beat a limit
    // that hasn't actually reset yet.
    if (x.task.status === "waiting_for_limit") {
      return isRetryDue(x.task.result && x.task.result.retry_after, now);
    }
    return false;
  });
  tasks.sort((a, b) => (rank[a.task.priority] ?? 99) - (rank[b.task.priority] ?? 99) || a.file.localeCompare(b.file));
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
    const output = await runClaude(prompt, invocationArgs, stageDurationMinutes * 60000);
    const durationMs = Date.now() - stageStart;
    fs.writeFileSync(logFile, (output.stdout || "") + (output.stderr || ""), "utf8");

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
      console.log(`WAITING_FOR_LIMIT ${task.id} -- retry after ${decision.retryAfter}`);
      return true; // a legitimate pause, not a failure
    }
    if (decision.action === "done") {
      save(file, current);
      console.log(`DONE ${task.id} (${sessions.length} session(s))`);
      return true;
    }
    if (decision.action === "blocked") {
      save(file, current);
      console.log(`BLOCKED ${task.id} — awaiting a real Owner decision (not a failure)`);
      return true;
    }
    if (decision.action === "continue_next_stage") {
      save(file, current);
      console.log(`STAGE ${task.id} #${stageIndex + 1} ran out of time -- continuing with its handoff in a new session`);
      stageIndex += 1;
      continue;
    }
    // decision.action === "fail"
    current.status = "failed";
    current.result = { ...current.result, runner_error: decision.reason, log: logFile, finished_at: new Date().toISOString() };
    save(file, current);
    console.error(`FAILED ${task.id} — queue stopped`);
    return false;
  }

  // Exhausted the declared/auto stage budget without reaching a terminal
  // decision above -- treated as a failure, never an infinite retry loop.
  const current = load(file);
  current.status = "failed";
  current.result = { ...(current.result || {}), sessions, runner_error: `exhausted ${maxStages} stage(s) without reaching done/blocked`, finished_at: new Date().toISOString() };
  save(file, current);
  console.error(`FAILED ${task.id} — queue stopped (stage budget exhausted)`);
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
  try {
    while (true) {
      const selected = nextTask();
      if (!selected) { if (!watch) { console.log("No ready tasks."); return 0; } await sleep(interval * 1000); continue; }
      if (dry) { console.log(`NEXT ${selected.task.id}: ${selected.task.title}`); return 0; }
      if (!(await execute(selected, maxTurns, timeout))) return 1;
      if (!watch) return 0;
    }
  } finally { if (fs.existsSync(LOCK)) fs.unlinkSync(LOCK); }
}

module.exports = {
  run, runClaude, killProcessTree, load, save, preflight, nextTask, execute, main,
  buildStagePrompt, gitStateBlockNow, handoffPathFor, readHandoff,
  CLAUDE, LOCK, LOG_DIR, HANDOFF_DIR, QUEUE, ROOT,
};

if (require.main === module) {
  main().then((code) => { process.exitCode = code; });
}
