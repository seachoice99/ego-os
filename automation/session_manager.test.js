"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  HANDOFF_WORD_LIMIT,
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
  classifyFatalOutput,
  parseStreamJsonLines,
  trustedFatalScanText,
  classifySessionOutcome,
  decideNextAction,
  claudeInvocationArgs,
} = require("./session_manager.js");

const VALID_HANDOFF = {
  summary: "Added the digital_assets table and its store functions.",
  commit: "abc1234",
  changed_files: ["ego_os/store.py", "tests/test_digital_assets.py"],
  checks: "130 pytest passed",
  remaining: "HTTP routes (owned by a later stage)",
  risks: "none identified",
  next_step: "wire up GET /assets",
};

// --- handoff validation ---------------------------------------------------

test("validateHandoff accepts a well-formed, compact handoff", () => {
  const result = validateHandoff(VALID_HANDOFF);
  assert.equal(result.ok, true);
  assert.ok(result.words < HANDOFF_WORD_LIMIT);
});

test("validateHandoff rejects a missing required field", () => {
  const { next_step, ...incomplete } = VALID_HANDOFF;
  const result = validateHandoff(incomplete);
  assert.equal(result.ok, false);
  assert.match(result.reason, /next_step/);
});

test("validateHandoff rejects a handoff over the word limit", () => {
  const bloated = { ...VALID_HANDOFF, summary: "word ".repeat(HANDOFF_WORD_LIMIT + 10) };
  const result = validateHandoff(bloated);
  assert.equal(result.ok, false);
  assert.match(result.reason, /word limit/);
});

test("validateHandoff rejects a non-object (e.g. a raw string or array)", () => {
  assert.equal(validateHandoff("just some text").ok, false);
  assert.equal(validateHandoff(["a", "b"]).ok, false);
  assert.equal(validateHandoff(null).ok, false);
});

test("countWords / handoffWordCount handle empty and whitespace-only input", () => {
  assert.equal(countWords(""), 0);
  assert.equal(countWords("   "), 0);
  assert.equal(handoffWordCount({}), 0);
});

// --- rate limit detection --------------------------------------------------

test("detectRateLimit finds a structured rate_limit_event with a non-allowed status", () => {
  const stdout = '{"type":"system","subtype":"init"}\n' +
    '{"type":"rate_limit_event","rate_limit_info":{"status":"rejected","resetsAt":9999999999,"rateLimitType":"five_hour"}}\n';
  const result = detectRateLimit(stdout);
  assert.ok(result);
  assert.equal(result.source, "rate_limit_event");
  assert.equal(result.status, "rejected");
});

test("detectRateLimit ignores a rate_limit_event whose status is 'allowed'", () => {
  const stdout = '{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":9999999999,"rateLimitType":"five_hour"}}\n';
  assert.equal(detectRateLimit(stdout), null);
});

test("detectRateLimit falls back to recognizable plain-text phrases", () => {
  const result = detectRateLimit("Error: you've hit your usage limit for this period.");
  assert.ok(result);
  assert.equal(result.source, "text_pattern");
});

test("detectRateLimit returns null for ordinary output", () => {
  assert.equal(detectRateLimit("All tests passed. Committing now."), null);
  assert.equal(detectRateLimit(""), null);
  assert.equal(detectRateLimit(null), null);
});

test("retryAfterFromRateLimit uses a future resetsAt (seconds epoch) when present", () => {
  const now = Date.parse("2026-01-01T00:00:00Z");
  const resetsAtSeconds = Math.floor(now / 1000) + 3600; // one hour later, seconds epoch
  const iso = retryAfterFromRateLimit({ resetsAt: resetsAtSeconds }, now);
  assert.equal(iso, new Date((resetsAtSeconds) * 1000).toISOString());
});

test("retryAfterFromRateLimit falls back to a conservative five-hour wait with no usable resetsAt", () => {
  const now = Date.parse("2026-01-01T00:00:00Z");
  const iso = retryAfterFromRateLimit({}, now);
  assert.equal(iso, new Date(now + 5 * 60 * 60 * 1000).toISOString());
  const iso2 = retryAfterFromRateLimit(undefined, now);
  assert.equal(iso2, new Date(now + 5 * 60 * 60 * 1000).toISOString());
});

test("isRetryDue is false before retry_after and true at/after it", () => {
  const now = Date.parse("2026-01-01T00:00:00Z");
  const future = new Date(now + 60000).toISOString();
  const past = new Date(now - 60000).toISOString();
  assert.equal(isRetryDue(future, now), false);
  assert.equal(isRetryDue(past, now), true);
  assert.equal(isRetryDue(null, now), true);
});

// --- stage planning ----------------------------------------------------

test("planStages returns null when the task declares no checkpoints (backward compatible)", () => {
  assert.equal(planStages({}), null);
  assert.equal(planStages({ checkpoints: [] }), null);
  assert.equal(planStages({ id: "OLD-001", prompt: "do the thing" }), null);
});

test("planStages returns one stage per declared checkpoint, in order", () => {
  const stages = planStages({ checkpoints: [{ title: "Schema" }, { title: "Routes", prompt: "add routes" }] });
  assert.equal(stages.length, 2);
  assert.equal(stages[0].index, 0);
  assert.equal(stages[0].title, "Schema");
  assert.equal(stages[1].prompt, "add routes");
});

// --- prompt building: stage 2+ gets handoff, not dialogue -----------------

test("buildHandoffBlock is empty for the first stage (no prior handoff)", () => {
  assert.equal(buildHandoffBlock(null), "");
});

test("buildHandoffBlock renders the handoff JSON and never claims to carry a conversation", () => {
  const block = buildHandoffBlock(VALID_HANDOFF);
  assert.match(block, /PRIOR STAGE HANDOFF/);
  assert.match(block, /abc1234/);
  assert.doesNotMatch(block, /transcript/i);
});

test("buildGitStateBlock renders HEAD, status, and recent commits compactly", () => {
  const block = buildGitStateBlock({ headSha: "deadbeef", statusPorcelain: "", recentCommits: ["deadbeef fix: thing", "cafefeed prior commit"] });
  assert.match(block, /HEAD: deadbeef/);
  assert.match(block, /\(clean\)/);
  assert.match(block, /fix: thing/);
});

test("estimatePromptSize reports a measurable, loggable size", () => {
  const size = estimatePromptSize("a".repeat(400));
  assert.equal(size.chars, 400);
  assert.equal(size.approxTokens, 100);
});

// --- session outcome classification -----------------------------------

test("classifySessionOutcome recognizes a rate limit before a signal-based kill", () => {
  const stdout = '{"type":"rate_limit_event","rate_limit_info":{"status":"rejected","resetsAt":9999999999}}';
  const result = classifySessionOutcome({ status: null, signal: "SIGTERM", stdout, stderr: "" });
  assert.equal(result.outcome, "rate_limited");
});

test("classifySessionOutcome reports timed_out_or_killed for a signal-terminated process with no rate limit", () => {
  const result = classifySessionOutcome({ status: null, signal: "SIGTERM", stdout: "still working...", stderr: "" });
  assert.equal(result.outcome, "timed_out_or_killed");
});

test("classifySessionOutcome reports exited_clean / exited_error from a plain exit status", () => {
  assert.equal(classifySessionOutcome({ status: 0, signal: null, stdout: "", stderr: "" }).outcome, "exited_clean");
  assert.equal(classifySessionOutcome({ status: 1, signal: null, stdout: "", stderr: "boom" }).outcome, "exited_error");
});

// --- claudeInvocationArgs: never --continue/--resume ------------------

test("claudeInvocationArgs never includes --continue or --resume, regardless of input", () => {
  const cases = [
    claudeInvocationArgs({ maxTurns: 10 }),
    claudeInvocationArgs({ maxTurns: 120, model: "claude-haiku-4-5-20251001" }),
    claudeInvocationArgs({ maxTurns: 1 }),
  ];
  for (const args of cases) {
    assert.ok(!args.includes("--continue"), "must never pass --continue");
    assert.ok(!args.includes("--resume"), "must never pass --resume");
  }
});

test("claudeInvocationArgs includes --model only when one is given, and each call is independent", () => {
  const withModel = claudeInvocationArgs({ maxTurns: 50, model: "claude-sonnet-5" });
  const withoutModel = claudeInvocationArgs({ maxTurns: 50 });
  assert.ok(withModel.includes("--model"));
  assert.ok(withModel.includes("claude-sonnet-5"));
  assert.ok(!withoutModel.includes("--model"));
  // Calling it again with different input must not leak state from a
  // prior call -- each stage's args are built fresh.
  const again = claudeInvocationArgs({ maxTurns: 999 });
  assert.ok(!again.includes("--model"));
  assert.ok(again.includes("999"));
});

// --- decideNextAction: the central stage-loop decision ------------------

const BASE_DECISION_INPUT = {
  sessionOutcome: { outcome: "exited_clean" },
  taskStatus: "in_progress",
  workingTreeClean: true,
  finalSyncOk: { ok: true },
  processExitedZero: true,
  stageIndex: 0,
  maxStages: 1,
  handoffAfterStage: null,
};

test("decideNextAction: done requires clean exit, status done, clean tree, and final_sync evidence", () => {
  const result = decideNextAction({ ...BASE_DECISION_INPUT, taskStatus: "done" });
  assert.equal(result.action, "done");
});

test("decideNextAction: done is refused if final_sync verification failed, even with status done", () => {
  const result = decideNextAction({ ...BASE_DECISION_INPUT, taskStatus: "done", finalSyncOk: { ok: false, reason: "heads differ" } });
  assert.equal(result.action, "fail");
  assert.match(result.reason, /heads differ/);
});

test("decideNextAction: blocked is accepted as a legitimate non-failure outcome", () => {
  const result = decideNextAction({ ...BASE_DECISION_INPUT, taskStatus: "blocked" });
  assert.equal(result.action, "blocked");
});

test("decideNextAction: a rate-limited session always waits for the limit, regardless of stage/status", () => {
  const result = decideNextAction({
    ...BASE_DECISION_INPUT,
    sessionOutcome: { outcome: "rate_limited", rateLimit: { source: "rate_limit_event", status: "rejected" } },
  });
  assert.equal(result.action, "wait_for_limit");
  assert.ok(result.retryAfter);
});

test("decideNextAction: a timed-out stage with a valid handoff and remaining stage budget continues", () => {
  const result = decideNextAction({
    ...BASE_DECISION_INPUT,
    sessionOutcome: { outcome: "timed_out_or_killed", signal: "SIGTERM" },
    stageIndex: 0,
    maxStages: 3,
    handoffAfterStage: VALID_HANDOFF,
  });
  assert.equal(result.action, "continue_next_stage");
});

test("decideNextAction: a timed-out stage with an INVALID handoff fails instead of continuing blindly", () => {
  const result = decideNextAction({
    ...BASE_DECISION_INPUT,
    sessionOutcome: { outcome: "timed_out_or_killed", signal: "SIGTERM" },
    stageIndex: 0,
    maxStages: 3,
    handoffAfterStage: { summary: "no other fields" },
  });
  assert.equal(result.action, "fail");
  assert.match(result.reason, /no usable handoff/);
});

test("decideNextAction: a timed-out stage with no stage budget left fails instead of looping forever", () => {
  const result = decideNextAction({
    ...BASE_DECISION_INPUT,
    sessionOutcome: { outcome: "timed_out_or_killed", signal: "SIGTERM" },
    stageIndex: 2,
    maxStages: 3,
    handoffAfterStage: VALID_HANDOFF,
  });
  assert.equal(result.action, "fail");
  assert.match(result.reason, /no further stages remain/);
});

test("decideNextAction: an ordinary non-timeout, non-done exit is a real failure, not a retry", () => {
  const result = decideNextAction({ ...BASE_DECISION_INPUT, sessionOutcome: { outcome: "exited_error", status: 1 } });
  assert.equal(result.action, "fail");
});

// --- fatal-pattern classification (RUNNER-CONTROL-UI fail-closed guard) ---
// The exact live defect this guards against: a child Claude process prints
// an authentication/subscription failure but still exits 0 -- exit code
// alone must never be read as success.

test("classifyFatalOutput recognizes the real subscription-disabled message", () => {
  const text = "Your organization has disabled Claude subscription access for Claude Code. Use an Anthropic API key instead, or ask your admin to enable access";
  const result = classifyFatalOutput(text);
  assert.ok(result);
  assert.equal(result.category, "authentication_required");
});

test("classifyFatalOutput returns null for ordinary, non-fatal output", () => {
  assert.equal(classifyFatalOutput("Wrote 3 files. Tests passed. Committed abc123."), null);
});

test("classifySessionOutcome reports auth_required for the subscription message even with a clean (status 0) exit -- real signal via stderr", () => {
  // Real stderr is the CLI's own diagnostic channel, never tool output --
  // one of the two trusted sources RUNNER-FALSE-AUTH-001 keeps scanning.
  const stdout = '{"type":"result","subtype":"success","is_error":false,"result":"done"}\n';
  const stderr = "Your organization has disabled Claude subscription access for Claude Code. Use an Anthropic API key instead, or ask your admin to enable access\n";
  const result = classifySessionOutcome({ status: 0, signal: null, stdout, stderr });
  assert.equal(result.outcome, "auth_required");
  assert.equal(result.fatal.category, "authentication_required");
});

test("classifySessionOutcome reports auth_required for a genuine CLI-emitted stream-json result event, even embedded in a larger transcript", () => {
  // The CLI's own final "result" event is the other trusted source -- this
  // models a real auth failure surfacing structurally rather than via stderr.
  const stdout = [
    '{"type":"system","subtype":"init","cwd":"/repo"}',
    '{"type":"assistant","message":{"content":[{"type":"text","text":"Starting work..."}]}}',
    '{"type":"result","subtype":"error","is_error":true,"result":"disabled Claude subscription access for Claude Code"}',
  ].join("\n");
  const result = classifySessionOutcome({ status: 0, signal: null, stdout, stderr: "" });
  assert.equal(result.outcome, "auth_required");
  assert.equal(result.fatal.category, "authentication_required");
});

test("RUNNER-FALSE-AUTH-001: a README/doc quote of the phrase arriving as ordinary tool_result content on stdout does NOT produce auth_required -- the exact live false positive", () => {
  // Models the real AGENT-VERIFY defect: a Read tool call returns file
  // content (here, a README excerpt) that quotes the historical incident
  // phrase verbatim. That content is wrapped in a type:"user" event's
  // tool_result -- untrusted, and must never be scanned.
  const readmeExcerpt = "A real defect motivated this fail-closed guard: a child Claude process can print \"Your organization has disabled Claude subscription access for Claude Code...\" and still exit 0.";
  const stdout = [
    '{"type":"system","subtype":"init","cwd":"/repo"}',
    JSON.stringify({
      type: "user",
      message: { role: "user", content: [{ tool_use_id: "toolu_1", type: "tool_result", content: readmeExcerpt, is_error: false }] },
    }),
    '{"type":"assistant","message":{"content":[{"type":"text","text":"Documented, moving on."}]}}',
    '{"type":"result","subtype":"success","is_error":false,"result":"done"}',
  ].join("\n");
  const result = classifySessionOutcome({ status: 0, signal: null, stdout, stderr: "" });
  assert.notEqual(result.outcome, "auth_required");
  assert.equal(result.outcome, "exited_clean");
});

test("RUNNER-FALSE-AUTH-001: an ordinary successful session with unrelated tool_result content still resolves to done via decideNextAction", () => {
  const readmeExcerpt = "A real defect motivated this fail-closed guard: \"disabled Claude subscription access\" and still exit 0.";
  const stdout = [
    JSON.stringify({ type: "user", message: { role: "user", content: [{ tool_use_id: "toolu_1", type: "tool_result", content: readmeExcerpt, is_error: false }] } }),
    '{"type":"result","subtype":"success","is_error":false,"result":"done"}',
  ].join("\n");
  const outcome = classifySessionOutcome({ status: 0, signal: null, stdout, stderr: "" });
  const result = decideNextAction({ ...BASE_DECISION_INPUT, sessionOutcome: outcome, taskStatus: "done", workingTreeClean: true, finalSyncOk: { ok: true }, processExitedZero: true });
  assert.equal(result.action, "done");
});

test("parseStreamJsonLines skips non-JSON/blank lines and keeps only valid JSON objects", () => {
  const stdout = '{"type":"system"}\n\nnot json at all\n{"type":"result","ok":true}\n';
  const events = parseStreamJsonLines(stdout);
  assert.deepEqual(events.map((e) => e.type), ["system", "result"]);
});

test("trustedFatalScanText includes stderr, raw non-JSON stdout lines, and only system/result stdout events -- excluding user/assistant", () => {
  const stdout = [
    '{"type":"user","message":{"content":[{"type":"tool_result","content":"secret-marker-in-tool-output"}]}}',
    '{"type":"assistant","message":{"content":[{"type":"text","text":"secret-marker-in-assistant-text"}]}}',
    '{"type":"system","subtype":"init"}',
    '{"type":"result","result":"secret-marker-in-result"}',
    "secret-marker-in-raw-unwrapped-line", // not valid JSON -- how the real historical defect surfaced
  ].join("\n");
  const scanned = trustedFatalScanText(stdout, "secret-marker-in-stderr");
  assert.ok(!scanned.includes("secret-marker-in-tool-output"));
  assert.ok(!scanned.includes("secret-marker-in-assistant-text"));
  assert.ok(scanned.includes("secret-marker-in-result"));
  assert.ok(scanned.includes("secret-marker-in-stderr"));
  assert.ok(scanned.includes("secret-marker-in-raw-unwrapped-line"));
});

test("classifySessionOutcome reports auth_required for a raw, unwrapped plain-text stdout line (the exact historically-observed shape, see fake_claude.js's auth_disabled_exit_zero)", () => {
  const stdout = "Your organization has disabled Claude subscription access for Claude Code. Use an Anthropic API key instead, or ask your admin to enable access\n";
  const result = classifySessionOutcome({ status: 0, signal: null, stdout, stderr: "" });
  assert.equal(result.outcome, "auth_required");
  assert.equal(result.fatal.category, "authentication_required");
});

test("RUNNER-FALSE-AUTH-001: rate-limit detection is unaffected, including alongside unrelated tool_result content quoting the auth phrase", () => {
  const readmeExcerpt = "History: \"disabled Claude subscription access\" was a real past incident.";
  const stdout = [
    JSON.stringify({ type: "user", message: { role: "user", content: [{ tool_use_id: "toolu_1", type: "tool_result", content: readmeExcerpt }] } }),
    '{"type":"rate_limit_event","rate_limit_info":{"status":"rejected","resetsAt":9999999999,"rateLimitType":"five_hour"}}',
  ].join("\n");
  const result = classifySessionOutcome({ status: 1, signal: null, stdout, stderr: "" });
  assert.equal(result.outcome, "rate_limited");
});

test("decideNextAction: the exact live defect -- subscription-disabled message with exit 0 and self-reported done must NOT be 'done'", () => {
  const outcome = classifySessionOutcome({
    status: 0,
    signal: null,
    stdout: '{"type":"result","subtype":"success","is_error":false,"result":"done"}',
    // Real signal via stderr (the CLI's own diagnostic channel) -- see
    // RUNNER-FALSE-AUTH-001: this must NOT be findable via ordinary
    // tool_result/assistant stdout content, only via a trusted source.
    stderr: "Your organization has disabled Claude subscription access for Claude Code. Use an Anthropic API key instead, or ask your admin to enable access",
  });
  const result = decideNextAction({
    ...BASE_DECISION_INPUT,
    sessionOutcome: outcome,
    taskStatus: "done", // the task file itself deceptively (or confusedly) claims done
    workingTreeClean: true,
    finalSyncOk: { ok: true },
    processExitedZero: true,
  });
  assert.notEqual(result.action, "done");
  assert.equal(result.action, "auth_required");
  assert.equal(result.fatal.category, "authentication_required");
});

test("decideNextAction: a non-auth fatal pattern (e.g. permission denied) also never becomes 'done', even with a clean exit", () => {
  const outcome = classifySessionOutcome({ status: 0, signal: null, stdout: "", stderr: "Error: Permission denied writing to /etc/" });
  const result = decideNextAction({
    ...BASE_DECISION_INPUT,
    sessionOutcome: outcome,
    taskStatus: "done",
    workingTreeClean: true,
    finalSyncOk: { ok: true },
    processExitedZero: true,
  });
  assert.equal(result.action, "fail");
  assert.match(result.reason, /permission_denied/);
});

test("classifySessionOutcome still detects a rate limit when no fatal pattern is present", () => {
  const stdout = '{"type":"rate_limit_event","rate_limit_info":{"status":"rejected","resetsAt":9999999999,"rateLimitType":"five_hour"}}\n';
  const result = classifySessionOutcome({ status: 1, signal: null, stdout, stderr: "" });
  assert.equal(result.outcome, "rate_limited");
});
