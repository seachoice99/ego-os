"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  classifyChangedPaths,
  planFinalSync,
  verifyFinalHeads,
  verifyFinalSyncEvidence,
} = require("./release_sync.js");

const TASK_FILE = "tasks/queue/RUNNER-002.yaml";

// --- 1. metadata-only final commit -> fast-forward without restart --------

test("metadata-only change (task's own YAML) classifies as ff_no_restart", () => {
  const result = classifyChangedPaths([TASK_FILE], TASK_FILE);
  assert.equal(result.action, "ff_no_restart");
});

test("planFinalSync allows ff_no_restart when everything lines up and only the task YAML changed", () => {
  const plan = planFinalSync({
    taskId: "RUNNER-002",
    taskFilePath: TASK_FILE,
    implementationCommit: "aaa111",
    productionHead: "aaa111",
    localHead: "bbb222",
    originHead: "bbb222",
    commitsSinceImplementation: [{ sha: "bbb222", message: "RUNNER-002: mark done with deployment evidence" }],
    changedFilesSinceImplementation: [TASK_FILE],
  });
  assert.equal(plan.action, "ff_no_restart");
});

// --- 2. final commit contains application code -> restart required --------

test("a change under ego_os/ classifies as restart_required", () => {
  const result = classifyChangedPaths([TASK_FILE, "ego_os/main.py"], TASK_FILE);
  assert.equal(result.action, "restart_required");
  assert.deepEqual(result.paths, ["ego_os/main.py"]);
});

test("requirements.txt, templates under ego_os/, and migrations all require a restart", () => {
  assert.equal(classifyChangedPaths(["requirements.txt"], TASK_FILE).action, "restart_required");
  assert.equal(classifyChangedPaths(["requirements-dev.txt"], TASK_FILE).action, "restart_required");
  assert.equal(classifyChangedPaths(["ego_os/templates/skills.html"], TASK_FILE).action, "restart_required");
  assert.equal(classifyChangedPaths(["ego_os/migrations/0002_add_skills.sql"], TASK_FILE).action, "restart_required");
});

test("an unexpected path outside the permitted metadata set also requires a restart, not a silent skip", () => {
  const result = classifyChangedPaths([TASK_FILE, "some_other_file.md"], TASK_FILE);
  assert.equal(result.action, "restart_required");
  assert.deepEqual(result.paths, ["some_other_file.md"]);
});

test("planFinalSync requires a restart when the final diff touches application code", () => {
  const plan = planFinalSync({
    taskId: "RUNNER-002",
    taskFilePath: TASK_FILE,
    implementationCommit: "aaa111",
    productionHead: "aaa111",
    localHead: "bbb222",
    originHead: "bbb222",
    commitsSinceImplementation: [{ sha: "bbb222", message: "RUNNER-002: mark done" }],
    changedFilesSinceImplementation: [TASK_FILE, "ego_os/skills.py"],
  });
  assert.equal(plan.action, "restart_required");
});

// --- 3. production diverged -> stop ----------------------------------------

test("planFinalSync stops when production HEAD does not match the deployed implementation commit", () => {
  const plan = planFinalSync({
    taskId: "RUNNER-002",
    taskFilePath: TASK_FILE,
    implementationCommit: "aaa111",
    productionHead: "zzz999", // someone/something changed production out of band
    localHead: "bbb222",
    originHead: "bbb222",
    commitsSinceImplementation: [{ sha: "bbb222", message: "RUNNER-002: mark done" }],
    changedFilesSinceImplementation: [TASK_FILE],
  });
  assert.equal(plan.action, "stop_diverged");
  assert.match(plan.reason, /production HEAD/);
});

// --- 4. origin advanced unexpectedly -> stop --------------------------------

test("planFinalSync stops when local HEAD does not match origin/main", () => {
  const plan = planFinalSync({
    taskId: "RUNNER-002",
    taskFilePath: TASK_FILE,
    implementationCommit: "aaa111",
    productionHead: "aaa111",
    localHead: "bbb222",
    originHead: "ccc333", // origin moved past what we pushed
    commitsSinceImplementation: [{ sha: "bbb222", message: "RUNNER-002: mark done" }],
    changedFilesSinceImplementation: [TASK_FILE],
  });
  assert.equal(plan.action, "stop_diverged");
  assert.match(plan.reason, /origin\/main/);
});

test("planFinalSync stops when a foreign (non-task-prefixed) commit is interleaved", () => {
  const plan = planFinalSync({
    taskId: "RUNNER-002",
    taskFilePath: TASK_FILE,
    implementationCommit: "aaa111",
    productionHead: "aaa111",
    localHead: "ccc333",
    originHead: "ccc333",
    commitsSinceImplementation: [
      { sha: "bbb222", message: "Unrelated hotfix from someone else" },
      { sha: "ccc333", message: "RUNNER-002: mark done" },
    ],
    changedFilesSinceImplementation: [TASK_FILE],
  });
  assert.equal(plan.action, "stop_diverged");
  assert.match(plan.reason, /foreign commit/);
});

// --- 5. final HEAD equality is checked --------------------------------------

test("verifyFinalHeads is true only when all three heads are identical and non-empty", () => {
  assert.equal(verifyFinalHeads({ localHead: "abc", originHead: "abc", productionHead: "abc" }), true);
  assert.equal(verifyFinalHeads({ localHead: "abc", originHead: "abc", productionHead: "def" }), false);
  assert.equal(verifyFinalHeads({ localHead: "abc", originHead: "def", productionHead: "abc" }), false);
  assert.equal(verifyFinalHeads({ localHead: "", originHead: "", productionHead: "" }), false);
});

// --- 6. failed final synchronization cannot leave status done without evidence --

test("verifyFinalSyncEvidence rejects a task with no final_sync recorded at all", () => {
  const task = { status: "done", result: {} };
  const check = verifyFinalSyncEvidence(task);
  assert.equal(check.ok, false);
  assert.match(check.reason, /no result\.final_sync/);
});

test("verifyFinalSyncEvidence rejects mismatched heads even if status claims done", () => {
  const task = {
    status: "done",
    result: {
      final_sync: { local_head: "abc", origin_head: "abc", production_head: "old999" },
    },
  };
  const check = verifyFinalSyncEvidence(task);
  assert.equal(check.ok, false);
  assert.match(check.reason, /do not match/);
});

test("verifyFinalSyncEvidence accepts a task whose recorded final_sync heads all match", () => {
  const task = {
    status: "done",
    result: {
      final_sync: { local_head: "abc123", origin_head: "abc123", production_head: "abc123", restart_performed: false },
    },
  };
  const check = verifyFinalSyncEvidence(task);
  assert.equal(check.ok, true);
});

test("verifyFinalSyncEvidence rejects partial evidence (missing production_head)", () => {
  const task = {
    status: "done",
    result: { final_sync: { local_head: "abc123", origin_head: "abc123" } },
  };
  const check = verifyFinalSyncEvidence(task);
  assert.equal(check.ok, false);
  assert.match(check.reason, /missing/);
});
