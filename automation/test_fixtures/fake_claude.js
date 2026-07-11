#!/usr/bin/env node
"use strict";

/**
 * A mock/fake stand-in for the real `claude` CLI, used ONLY by
 * claude_task_runner.test.js (TOKEN-EFFICIENCY-001). Never launched
 * outside tests -- real integration behavior (fresh process per stage,
 * argv, stdin piping, timeout/tree-kill) is exercised for real against
 * this fake, without ever spawning a real Claude Code session.
 *
 * Controlled entirely via environment variables (spawnSync inherits the
 * parent's env by default) so each test scenario is just a different
 * EGO_OS_FAKE_SCENARIO value:
 *
 *   instant_done         -- writes status "done" (+ final_sync if the
 *                            task is release:automatic) to the task file,
 *                            writes a valid handoff, exits 0.
 *   instant_blocked       -- writes status "blocked", exits 0.
 *   rate_limited          -- emits a rate_limit_event with a non-"allowed"
 *                            status, exits non-zero.
 *   hang_forever           -- spawns a detached grandchild (to prove
 *                            tree-kill cleans up more than just the direct
 *                            child) and then hangs until killed.
 *   hang_once_then_done    -- hangs and leaves a handoff on the first
 *                            invocation (tracked via EGO_OS_FAKE_MARKER_FILE);
 *                            completes normally on the second, simulating a
 *                            real timeout -> continue-with-handoff stage.
 */

const fs = require("fs");

const args = process.argv.slice(2);
if (args.includes("--version")) {
  process.stdout.write("fake-claude 0.0.0-test\n");
  process.exit(0);
}

// Read stdin fully before doing anything -- mirrors the real CLI's
// `input: promptText` stdin-piping invocation, and proves that plumbing
// still works end to end against this fake.
try {
  fs.readFileSync(0, "utf8");
} catch {
  /* no stdin available -- fine for --version-only invocations */
}

const scenario = process.env.EGO_OS_FAKE_SCENARIO || "instant_done";
const taskFile = process.env.EGO_OS_FAKE_TASK_FILE;
const handoffFile = process.env.EGO_OS_FAKE_HANDOFF_FILE;
const markerFile = process.env.EGO_OS_FAKE_MARKER_FILE;

function loadTask() {
  return JSON.parse(fs.readFileSync(taskFile, "utf8"));
}
function saveTask(t) {
  fs.writeFileSync(taskFile, JSON.stringify(t, null, 2) + "\n", "utf8");
}
function emitResult() {
  process.stdout.write(JSON.stringify({ type: "result", subtype: "success", num_turns: 1, is_error: false }) + "\n");
}
function writeHandoff(fields) {
  if (!handoffFile) return;
  fs.writeFileSync(handoffFile, JSON.stringify({
    summary: "fake stage", commit: null, changed_files: [], checks: "none (fake)",
    remaining: "nothing -- task complete", risks: "none", next_step: "none",
    ...fields,
  }));
}

function finishDone() {
  const t = loadTask();
  t.status = "done";
  t.result = t.result || {};
  if (t.release === "automatic") {
    t.result.final_sync = { local_head: "fakehead", origin_head: "fakehead", production_head: "fakehead", restart_performed: false };
  }
  saveTask(t);
  writeHandoff({ remaining: "nothing -- task complete" });
  emitResult();
  process.exit(0);
}

switch (scenario) {
  case "instant_done": {
    finishDone();
    break;
  }
  case "instant_blocked": {
    const t = loadTask();
    t.status = "blocked";
    t.result = { ...(t.result || {}), reason: "fake: awaiting owner decision" };
    saveTask(t);
    emitResult();
    process.exit(0);
    break;
  }
  case "rate_limited": {
    process.stdout.write(JSON.stringify({
      type: "rate_limit_event",
      rate_limit_info: { status: "rejected", resetsAt: Math.floor(Date.now() / 1000) + 3600, rateLimitType: "five_hour" },
    }) + "\n");
    process.exit(1);
    break;
  }
  case "hang_forever": {
    // A normal (non-detached) grandchild -- this is the shape that
    // actually matters: the real orphaned-process defect this fixture
    // exists to guard against was cmd.exe -> claude.cmd -> claude.exe,
    // an ordinary parent/child chain, not a deliberately detached one.
    // Windows' explicitly-detached process groups are a different, harder
    // problem `taskkill /T` cannot reliably reach -- a known, documented
    // limitation, not something this fixture claims to solve.
    const cpMod = require("child_process");
    if (markerFile) {
      const child = cpMod.spawn(process.execPath, ["-e", "setInterval(()=>{}, 1000);"], { stdio: "ignore" });
      fs.writeFileSync(markerFile, String(child.pid));
    }
    setInterval(() => {}, 1000);
    break;
  }
  case "hang_once_then_done": {
    if (markerFile && fs.existsSync(markerFile)) {
      finishDone();
    } else {
      if (markerFile) fs.writeFileSync(markerFile, "seen");
      writeHandoff({
        summary: "fake stage 1 ran out of time", commit: "fakeabc", changed_files: ["fake.txt"],
        checks: "partial", remaining: "finish the rest", risks: "none", next_step: "continue in stage 2",
      });
      setInterval(() => {}, 1000); // hang until timeout-killed
    }
    break;
  }
  default:
    process.stderr.write(`fake_claude: unknown scenario ${scenario}\n`);
    process.exit(2);
}
