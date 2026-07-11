"use strict";

/**
 * Pure decision logic for the runner's final-sync protocol -- no I/O, no
 * child_process, no network. This exists to fix a real production defect:
 * after RUNNER-001, the Claude-recorded "done" metadata commit was pushed
 * to origin/main but never itself deployed, so production silently ended
 * up one commit behind origin/main even though the task's own result
 * claimed success. Every function here is deterministic on plain data so
 * the decision rules can be unit-tested without a real git repo, a real
 * Claude subprocess, or a real VPS.
 */

// The only path that is unconditionally safe to fast-forward onto
// production without a restart: the executing task's own queue file.
// Deliberately not a glob over tasks/queue/*.yaml -- touching a *different*
// task's file mid-run is exactly the concurrent-task hazard the runner's
// own "never touch another in-progress task's files" rule guards against,
// so it must never be folded into "safe metadata" automatically.
function permittedMetadataPaths(taskFilePath) {
  return new Set([taskFilePath]);
}

// Any changed path matching this can never be part of a metadata-only
// fast-forward, even if it technically belongs to this task's own commits --
// it always requires the normal deploy/restart/health-check cycle.
const RESTART_REQUIRED_RE = /^(ego_os\/|requirements(-dev)?\.txt$|.*\/migrations?\/)/;

/**
 * Classifies a set of changed file paths (git diff --name-only between the
 * deployed implementation commit and the candidate final HEAD).
 * Returns { action: "ff_no_restart" } or { action: "restart_required", paths }.
 */
function classifyChangedPaths(changedFiles, taskFilePath) {
  const allowed = permittedMetadataPaths(taskFilePath);
  const restartPaths = changedFiles.filter((f) => RESTART_REQUIRED_RE.test(f));
  if (restartPaths.length > 0) {
    return { action: "restart_required", paths: restartPaths, reason: "application code, dependency, or migration path changed" };
  }
  const unexpected = changedFiles.filter((f) => !allowed.has(f));
  if (unexpected.length > 0) {
    return { action: "restart_required", paths: unexpected, reason: "path outside the permitted release-metadata set changed" };
  }
  return { action: "ff_no_restart" };
}

/**
 * commits: array of { sha, message }, every commit strictly between the
 * deployed implementation commit and the candidate final HEAD. A commit
 * whose message does not start with "<taskId>:" means real, unrelated
 * history landed on main while this task was mid-flight -- an automatic
 * metadata-only fast-forward could then silently carry along someone
 * else's untested application code.
 */
function findForeignCommits(commits, taskId) {
  const prefix = `${taskId}:`;
  return commits.filter((c) => !c.message.startsWith(prefix));
}

/**
 * The single entry point the runner protocol (and its prompt) follows to
 * decide what to do with the final metadata commit. All four stop/branch
 * conditions from the spec are represented as distinct actions so a test
 * can assert on the *reason*, not just pass/fail.
 */
function planFinalSync({
  taskId,
  taskFilePath,
  implementationCommit,
  productionHead,
  localHead,
  originHead,
  commitsSinceImplementation,
  changedFilesSinceImplementation,
}) {
  if (productionHead !== implementationCommit) {
    return {
      action: "stop_diverged",
      reason: `production HEAD (${productionHead}) does not match the deployed implementation commit (${implementationCommit}) -- production changed out of band`,
    };
  }
  if (localHead !== originHead) {
    return {
      action: "stop_diverged",
      reason: `local HEAD (${localHead}) does not match origin/main (${originHead}) -- origin advanced unexpectedly or the push did not land`,
    };
  }
  const foreign = findForeignCommits(commitsSinceImplementation, taskId);
  if (foreign.length > 0) {
    return {
      action: "stop_diverged",
      reason: `foreign commit(s) interleaved between the implementation commit and the final commit: ${foreign.map((c) => c.sha).join(", ")}`,
    };
  }
  const classification = classifyChangedPaths(changedFilesSinceImplementation, taskFilePath);
  return classification;
}

/**
 * After a sync attempt (fast-forward or full restart-deploy), the three
 * heads must be identical before the task is allowed to claim "done".
 */
function verifyFinalHeads({ localHead, originHead, productionHead }) {
  return Boolean(localHead) && localHead === originHead && originHead === productionHead;
}

/**
 * Deterministic, runner-side guard against the exact failure mode this
 * module exists to prevent: a task file claiming status "done" without
 * ever having recorded (and satisfied) real final-sync evidence. Used by
 * claude_task_runner.js's own post-execution check -- independent of
 * whatever the spawned Claude process self-reports.
 */
function verifyFinalSyncEvidence(task) {
  const sync = task && task.result && task.result.final_sync;
  if (!sync) {
    return { ok: false, reason: "no result.final_sync evidence recorded" };
  }
  const { local_head, origin_head, production_head } = sync;
  if (!local_head || !origin_head || !production_head) {
    return { ok: false, reason: "result.final_sync is missing one or more head values" };
  }
  if (!verifyFinalHeads({ localHead: local_head, originHead: origin_head, productionHead: production_head })) {
    return {
      ok: false,
      reason: `result.final_sync heads do not match: local=${local_head} origin=${origin_head} production=${production_head}`,
    };
  }
  return { ok: true };
}

module.exports = {
  RESTART_REQUIRED_RE,
  permittedMetadataPaths,
  classifyChangedPaths,
  findForeignCommits,
  planFinalSync,
  verifyFinalHeads,
  verifyFinalSyncEvidence,
};
