"use strict";

/**
 * Pure decision logic for token/usage-limit-efficient staged execution
 * (TOKEN-EFFICIENCY-001) -- no I/O, no child_process, no network, so every
 * rule here is directly unit-testable against synthetic data.
 *
 * The problem this exists to fix, measured from this repository's own
 * runner logs: a single unbounded `claude -p` session for one task grows
 * turn over turn (RUNNER-002, a trivial doc task, used 46 turns and 3.1M
 * cache-read tokens; DA-02, a real feature, used 86 turns and 9.3M
 * cache-read tokens; DA-03 burned 55 turns and 4.2M cache-read tokens
 * without even finishing). The fix is not a smaller starting prompt (those
 * were already lean, 6-9KB) -- it's bounding how long any single session
 * runs, handing off to a *fresh* session via a small, structured file
 * instead of replaying the conversation.
 */

const DEFAULT_MAX_AUTO_STAGES = 4;
const HANDOFF_WORD_LIMIT = 1500;
const HANDOFF_REQUIRED_FIELDS = ["summary", "commit", "changed_files", "checks", "remaining", "risks", "next_step"];

function countWords(text) {
  const trimmed = String(text ?? "").trim();
  return trimmed ? trimmed.split(/\s+/).length : 0;
}

// Sums words across every string/array-of-strings field -- a deliberately
// simple proxy for "is this handoff compact", not a strict token count.
function handoffWordCount(handoff) {
  let total = 0;
  for (const value of Object.values(handoff || {})) {
    if (typeof value === "string") total += countWords(value);
    else if (Array.isArray(value)) for (const v of value) total += countWords(String(v));
  }
  return total;
}

function validateHandoff(handoff) {
  if (!handoff || typeof handoff !== "object" || Array.isArray(handoff)) {
    return { ok: false, reason: "handoff is not a JSON object" };
  }
  const missing = HANDOFF_REQUIRED_FIELDS.filter((f) => !(f in handoff));
  if (missing.length) {
    return { ok: false, reason: `handoff missing required field(s): ${missing.join(", ")}` };
  }
  const words = handoffWordCount(handoff);
  if (words > HANDOFF_WORD_LIMIT) {
    return { ok: false, reason: `handoff is ${words} words, over the ${HANDOFF_WORD_LIMIT}-word limit` };
  }
  return { ok: true, words };
}

// --- Rate-limit detection ----------------------------------------------

// The CLI's own stream-json output already reports this structurally as a
// `rate_limit_event` line (verified live in this repo's own runner logs:
// {"type":"rate_limit_event","rate_limit_info":{"status":"allowed",
// "resetsAt":...,"rateLimitType":"five_hour",...}}). A `status` other than
// "allowed" is the CLI's own signal that a real usage/rate limit is in
// effect -- not a code defect, and not something to retry immediately.
// Falls back to recognizable plain-text phrases in case a limit surfaces
// only as stderr/plain text rather than a structured event.
const RATE_LIMIT_TEXT_PATTERNS = [
  "usage limit reached",
  "rate limit exceeded",
  "you've hit your usage limit",
  "usage limit will reset",
  "you are being rate limited",
];

function detectRateLimit(text) {
  if (!text) return null;
  const eventPattern = /\{"type":"rate_limit_event".*?\}\}/g;
  const matches = [...text.matchAll(eventPattern)];
  for (const m of matches.reverse()) {
    let evt;
    try {
      evt = JSON.parse(m[0]);
    } catch {
      continue;
    }
    const info = evt.rate_limit_info || {};
    if (info.status && info.status !== "allowed") {
      return { source: "rate_limit_event", status: info.status, rateLimitType: info.rateLimitType, resetsAt: info.resetsAt };
    }
  }
  const lowered = text.toLowerCase();
  for (const pattern of RATE_LIMIT_TEXT_PATTERNS) {
    if (lowered.includes(pattern)) return { source: "text_pattern", matched: pattern };
  }
  return null;
}

// resetsAt from the CLI may be a unix-seconds or unix-ms epoch; treat
// anything with 10 or fewer digits as seconds. Falls back to a
// conservative five-hour wait (matching the "five_hour" rate limit
// window actually observed) when no usable reset time is available --
// never a shorter, optimistic guess that would just waste another
// attempt immediately.
function retryAfterFromRateLimit(info, now = Date.now()) {
  if (info && info.resetsAt !== undefined && info.resetsAt !== null) {
    const raw = Number(info.resetsAt);
    if (Number.isFinite(raw)) {
      const ms = String(Math.trunc(raw)).length <= 10 ? raw * 1000 : raw;
      if (ms > now) return new Date(ms).toISOString();
    }
  }
  return new Date(now + 5 * 60 * 60 * 1000).toISOString();
}

function isRetryDue(retryAfterIso, now = Date.now()) {
  if (!retryAfterIso) return true;
  const t = Date.parse(retryAfterIso);
  return !Number.isFinite(t) || now >= t;
}

// --- Stage planning -------------------------------------------------------

// Explicit, task-author-declared checkpoints take priority: each becomes
// its own fresh session with its own focused prompt. Returns null when the
// task declares none, meaning "no pre-planned stages" -- the runner falls
// back to adaptive staging (only splitting into a new session if a stage
// actually runs out of its time/turn budget), never staging a task that
// doesn't need it.
function planStages(task) {
  if (Array.isArray(task.checkpoints) && task.checkpoints.length) {
    return task.checkpoints.map((c, i) => ({
      index: i,
      title: (c && c.title) || `Stage ${i + 1}`,
      prompt: (c && c.prompt) || "",
    }));
  }
  return null;
}

// --- Prompt building ---------------------------------------------------

function buildGitStateBlock({ headSha, statusPorcelain, recentCommits }) {
  const status = statusPorcelain && statusPorcelain.trim() ? statusPorcelain.trim() : "(clean)";
  const commits = (recentCommits || []).length ? recentCommits.map((c) => `- ${c}`).join("\n") : "(none)";
  return `GIT STATE:\nHEAD: ${headSha}\nStatus: ${status}\nRecent commits:\n${commits}`;
}

// Deliberately the ONLY carryover from a prior stage -- no conversation,
// no full diff, no raw logs. If handoff is null (first stage of a task),
// returns "" so the prompt has nothing to show for "prior work".
function buildHandoffBlock(handoff) {
  if (!handoff) return "";
  return `PRIOR STAGE HANDOFF (this is your ONLY context from earlier stages -- no prior conversation, no full diff, and no old logs are carried over; if you need more detail than this, read it from the repository yourself):\n${JSON.stringify(handoff, null, 2)}`;
}

function estimatePromptSize(promptText) {
  const chars = (promptText || "").length;
  return { chars, approxTokens: Math.ceil(chars / 4) };
}

// --- Fatal-pattern classification (RUNNER-CONTROL-UI fail-closed guard) --

// A child Claude process can print an authentication/subscription failure
// and still exit 0 -- observed directly: "Your organization has disabled
// Claude subscription access for Claude Code. Use an Anthropic API key
// instead, or ask your admin to enable access." Exit code alone is never
// sufficient evidence of success; these patterns must be checked and must
// win over any self-reported "done" status, regardless of exit code or
// working-tree cleanliness.
const FATAL_PATTERNS = [
  { category: "authentication_required", pattern: /disabled claude subscription access/i },
  { category: "authentication_required", pattern: /use an anthropic api key instead/i },
  { category: "authentication_required", pattern: /invalid api key/i },
  { category: "authentication_required", pattern: /authentication_error/i },
  { category: "permission_denied", pattern: /permission denied/i },
  { category: "model_unavailable", pattern: /model[_ ]not[_ ]found|model is not available/i },
  { category: "network_failure", pattern: /econnrefused|enotfound|network error|fetch failed/i },
];

function classifyFatalOutput(text) {
  if (!text) return null;
  for (const { category, pattern } of FATAL_PATTERNS) {
    const match = text.match(pattern);
    if (match) return { category, matched: match[0] };
  }
  return null;
}

// --- Session outcome classification -----------------------------------

// Distinguishes why a spawned session ended, from the runner's own
// deterministic, externally-observable signals -- never by trusting
// free-text self-report alone. Fatal-pattern detection runs FIRST and
// unconditionally: a recognized fatal condition (auth/subscription above
// all, but also permission/model/network) must never be classified as
// exited_clean, no matter the exit code.
function classifySessionOutcome({ status, signal, stdout, stderr }) {
  const combined = `${stdout || ""}\n${stderr || ""}`;
  const fatal = classifyFatalOutput(combined);
  if (fatal && fatal.category === "authentication_required") {
    return { outcome: "auth_required", fatal };
  }
  const rateLimit = detectRateLimit(combined);
  if (rateLimit) return { outcome: "rate_limited", rateLimit };
  if (fatal) return { outcome: "exited_error", status, fatal };
  if (signal) return { outcome: "timed_out_or_killed", signal };
  if (status === 0) return { outcome: "exited_clean" };
  return { outcome: "exited_error", status };
}

// --- The central stage-loop decision ------------------------------------

// A `claude` invocation never takes --continue/--resume anywhere in this
// codebase (verified by claudeInvocationArgs' own test coverage) -- every
// stage is architecturally a brand-new session. This function is what
// decides, after one such fresh session ends, what the runner does next.
// Pure: every input is a plain value the caller already observed, so the
// whole decision tree is unit-testable without a real (or fake) process.
function decideNextAction({
  sessionOutcome, // classifySessionOutcome() result
  taskStatus, // status Claude itself wrote to the task file after the session
  workingTreeClean,
  finalSyncOk, // { ok, reason } -- {ok:true} for a non-automatic-release task
  processExitedZero,
  stageIndex, // 0-based
  maxStages,
  handoffAfterStage, // parsed handoff JSON read from disk after the session, or null
}) {
  // Fail-closed: a recognized fatal pattern always wins, before anything
  // else is even considered -- including a self-reported "done" status and
  // a zero exit code. This is what prevents the exact defect reported live:
  // a child process printing an auth/subscription failure while still
  // exiting 0 and having already written status "done" to its own task file.
  if (sessionOutcome.outcome === "auth_required") {
    return { action: "auth_required", fatal: sessionOutcome.fatal };
  }
  if (sessionOutcome.fatal) {
    return { action: "fail", reason: `fatal condition detected (${sessionOutcome.fatal.category}): ${sessionOutcome.fatal.matched}` };
  }
  if (sessionOutcome.outcome === "rate_limited") {
    return {
      action: "wait_for_limit",
      retryAfter: retryAfterFromRateLimit(sessionOutcome.rateLimit),
      rateLimit: sessionOutcome.rateLimit,
    };
  }
  if (processExitedZero && taskStatus === "done" && workingTreeClean && finalSyncOk.ok) {
    return { action: "done" };
  }
  if (processExitedZero && taskStatus === "blocked" && workingTreeClean) {
    return { action: "blocked" };
  }
  if (sessionOutcome.outcome === "timed_out_or_killed") {
    if (stageIndex + 1 < maxStages) {
      const check = validateHandoff(handoffAfterStage);
      if (check.ok) return { action: "continue_next_stage", handoffCheck: check };
      return { action: "fail", reason: `stage ${stageIndex + 1} ran out of time with no usable handoff (${check.reason})` };
    }
    return { action: "fail", reason: `stage ${stageIndex + 1} ran out of time and no further stages remain (max ${maxStages})` };
  }
  return {
    action: "fail",
    reason: finalSyncOk.ok ? "Claude did not finish cleanly" : `final sync verification failed: ${finalSyncOk.reason}`,
  };
}

// The exact, fixed argv this runner ever passes to `claude` -- centralized
// so "never --continue/--resume across tasks or stages" is one small,
// directly testable function instead of an implicit property scattered
// across call sites.
function claudeInvocationArgs({ maxTurns, model }) {
  const args = ["-p", "--output-format", "stream-json", "--verbose", "--max-turns", String(maxTurns), "--dangerously-skip-permissions"];
  if (model) args.push("--model", String(model));
  return args;
}

module.exports = {
  DEFAULT_MAX_AUTO_STAGES,
  HANDOFF_WORD_LIMIT,
  HANDOFF_REQUIRED_FIELDS,
  countWords,
  handoffWordCount,
  validateHandoff,
  detectRateLimit,
  retryAfterFromRateLimit,
  isRetryDue,
  planStages,
  buildGitStateBlock,
  buildHandoffBlock,
  estimatePromptSize,
  FATAL_PATTERNS,
  classifyFatalOutput,
  classifySessionOutcome,
  decideNextAction,
  claudeInvocationArgs,
};
