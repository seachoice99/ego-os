"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("path");
const {
  toWindow, classifyStatus, unknownSnapshot, normalizeRateLimitsResult,
  formatConsoleReport, fetchCodexUsageSnapshot,
} = require("./codex_usage.js");

const FAKE_CODEX = path.join(__dirname, "test_fixtures",
  process.platform === "win32" ? "fake_codex_app_server.cmd" : "fake_codex_app_server.js");

function withScenario(scenario, fn) {
  const prev = process.env.EGO_OS_FAKE_CODEX_SCENARIO;
  process.env.EGO_OS_FAKE_CODEX_SCENARIO = scenario;
  return fn().finally(() => {
    if (prev === undefined) delete process.env.EGO_OS_FAKE_CODEX_SCENARIO;
    else process.env.EGO_OS_FAKE_CODEX_SCENARIO = prev;
  });
}

// --- 1/2/3: real response shape -> normalized (pure) -----------------------

test("normalizeRateLimitsResult: full response with primary/secondary/reset_credits", () => {
  const raw = {
    rateLimits: {
      primary: { usedPercent: 25, windowDurationMins: 300, resetsAt: 1730947200 },
      secondary: { usedPercent: 59, windowDurationMins: 10080, resetsAt: 1731552000 },
      rateLimitReachedType: null,
    },
    rateLimitResetCredits: { availableCount: 2, credits: [{ id: "x" }] },
  };
  const s = normalizeRateLimitsResult(raw, { planType: "pro", checkedAt: "2026-07-12T19:10:00.000Z" });
  assert.equal(s.status, "available");
  assert.equal(s.plan_type, "pro");
  assert.equal(s.primary.remaining_percent, 75);
  assert.equal(s.secondary.remaining_percent, 41);
  assert.equal(s.primary.resets_at, new Date(1730947200 * 1000).toISOString());
  assert.equal(s.reset_credits.available_count, 2);
  assert.deepEqual(s.reset_credits.credits, [{ id: "x" }]);
  assert.equal(s.error, null);
});

test("normalizeRateLimitsResult: only primary present (secondary/reset_credits absent) never crashes", () => {
  const raw = { rateLimits: { primary: { usedPercent: 10, windowDurationMins: 300, resetsAt: 1730947200 }, secondary: null, rateLimitReachedType: null } };
  const s = normalizeRateLimitsResult(raw, {});
  assert.equal(s.secondary, null);
  assert.equal(s.reset_credits, null);
  assert.equal(s.primary.remaining_percent, 90);
  assert.equal(s.status, "available");
});

test("toWindow: usedPercent correctly becomes remaining_percent, clamped to [0,100]", () => {
  assert.equal(toWindow({ usedPercent: 0 }).remaining_percent, 100);
  assert.equal(toWindow({ usedPercent: 100 }).remaining_percent, 0);
  assert.equal(toWindow({ usedPercent: 30 }).remaining_percent, 70);
  assert.equal(toWindow({ usedPercent: 150 }).remaining_percent, 0, "over 100% used clamps to 0 remaining, never negative");
  assert.equal(toWindow(null), null);
  assert.equal(toWindow({}).remaining_percent, null, "missing usedPercent never fabricates a number");
});

// --- 4/5: classification (pure) --------------------------------------------

test("classifyStatus: available/low/exhausted thresholds", () => {
  assert.equal(classifyStatus({ primary: { remaining_percent: 50 }, secondary: null, rateLimitReachedType: null }), "available");
  assert.equal(classifyStatus({ primary: { remaining_percent: 15 }, secondary: null, rateLimitReachedType: null }), "low", "exactly at the 15% threshold counts as low");
  assert.equal(classifyStatus({ primary: { remaining_percent: 16 }, secondary: null, rateLimitReachedType: null }), "available");
  assert.equal(classifyStatus({ primary: { remaining_percent: 0 }, secondary: null, rateLimitReachedType: null }), "exhausted");
  assert.equal(classifyStatus({ primary: { remaining_percent: 80 }, secondary: { remaining_percent: 5 }, rateLimitReachedType: null }), "low", "the MINIMUM of both windows governs, not just primary");
});

test("classifyStatus: a set rateLimitReachedType always means exhausted, even with healthy percentages", () => {
  assert.equal(classifyStatus({ primary: { remaining_percent: 90 }, secondary: { remaining_percent: 90 }, rateLimitReachedType: "primary" }), "exhausted");
});

test("classifyStatus: no measurable window at all is 'available', not 'unknown' -- a valid empty read is not a failed read", () => {
  assert.equal(classifyStatus({ primary: null, secondary: null, rateLimitReachedType: null }), "available");
});

// --- 6: invalid/malformed response (pure) ----------------------------------

test("normalizeRateLimitsResult: malformed/missing rateLimits produces an honest 'unknown', never a crash", () => {
  assert.equal(normalizeRateLimitsResult(null).status, "unknown");
  assert.equal(normalizeRateLimitsResult({}).status, "unknown");
  assert.equal(normalizeRateLimitsResult({ rateLimits: null }).status, "unknown");
  assert.ok(normalizeRateLimitsResult(undefined).error);
});

test("unknownSnapshot never includes anything beyond a short message", () => {
  const s = unknownSnapshot("x".repeat(5000));
  assert.equal(s.status, "unknown");
  assert.ok(s.error.length <= 300);
});

// --- integration: real fetchCodexUsageSnapshot() against the fake fixture -

test("fetchCodexUsageSnapshot: full_response end to end via the fake codex app-server", async () => {
  await withScenario("full_response", async () => {
    const snapshot = await fetchCodexUsageSnapshot({ binaryPath: FAKE_CODEX, timeoutMs: 5000 });
    assert.equal(snapshot.status, "available");
    assert.equal(snapshot.plan_type, "pro");
    assert.equal(snapshot.primary.remaining_percent, 75);
    assert.equal(snapshot.secondary.remaining_percent, 41);
    assert.equal(snapshot.reset_credits.available_count, 2);
    assert.equal(snapshot.error, null);
  });
});

test("fetchCodexUsageSnapshot: exhausted scenario classifies correctly end to end", async () => {
  await withScenario("exhausted", async () => {
    const snapshot = await fetchCodexUsageSnapshot({ binaryPath: FAKE_CODEX, timeoutMs: 5000 });
    assert.equal(snapshot.status, "exhausted");
    assert.equal(snapshot.rate_limit_reached_type, "primary");
  });
});

test("fetchCodexUsageSnapshot: a JSON-RPC error on account/rateLimits/read yields 'unknown', not a crash", async () => {
  await withScenario("error_on_ratelimits", async () => {
    const snapshot = await fetchCodexUsageSnapshot({ binaryPath: FAKE_CODEX, timeoutMs: 5000 });
    assert.equal(snapshot.status, "unknown");
    assert.ok(snapshot.error);
  });
});

test("fetchCodexUsageSnapshot: a stray non-JSON stdout line is skipped without corrupting the real response", async () => {
  await withScenario("noisy_then_valid", async () => {
    const snapshot = await fetchCodexUsageSnapshot({ binaryPath: FAKE_CODEX, timeoutMs: 5000 });
    assert.equal(snapshot.status, "available");
    assert.equal(snapshot.primary.remaining_percent, 75);
  });
});

// --- 7: codex not present ---------------------------------------------------

test("fetchCodexUsageSnapshot: a nonexistent codex binary yields 'unknown', never throws", async () => {
  const snapshot = await fetchCodexUsageSnapshot({ binaryPath: "ego-os-definitely-not-a-real-binary-xyz", timeoutMs: 5000 });
  assert.equal(snapshot.status, "unknown");
  assert.ok(snapshot.error);
});

// --- 8: timeout + guaranteed process termination ---------------------------

test("fetchCodexUsageSnapshot: a hanging codex app-server times out as 'unknown' and its process is actually killed", async () => {
  await withScenario("hang", async () => {
    const before = Date.now();
    const snapshot = await fetchCodexUsageSnapshot({ binaryPath: FAKE_CODEX, timeoutMs: 800 });
    const elapsed = Date.now() - before;
    assert.equal(snapshot.status, "unknown");
    assert.match(snapshot.error, /did not respond/);
    assert.ok(elapsed < 5000, "must not wait anywhere near the default 10s timeout when a short one was requested");
  });
});

// --- console report shape ---------------------------------------------------

test("formatConsoleReport renders the expected human-readable lines", () => {
  const snapshot = normalizeRateLimitsResult({
    rateLimits: { primary: { usedPercent: 28, windowDurationMins: 300, resetsAt: 1730947200 }, secondary: { usedPercent: 59, windowDurationMins: 10080, resetsAt: 1731552000 }, rateLimitReachedType: null },
    rateLimitResetCredits: null,
  }, { checkedAt: "2026-07-12T19:10:00.000Z" });
  const report = formatConsoleReport("DA-03", snapshot);
  assert.match(report, /CODEX USAGE AFTER DA-03/);
  assert.match(report, /Status: available/);
  assert.match(report, /5h window: 72% remaining/);
  assert.match(report, /Weekly window: 41% remaining/);
  assert.match(report, /Credits: unavailable/);
});
