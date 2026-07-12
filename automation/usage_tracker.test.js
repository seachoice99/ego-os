"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { extractSessionUsage, emptyTracker, recordSession } = require("./usage_tracker.js");

const REAL_RESULT_LINE = JSON.stringify({
  type: "result",
  subtype: "success",
  is_error: false,
  num_turns: 4,
  total_cost_usd: 0.0891722,
  usage: { input_tokens: 2, output_tokens: 573, cache_read_input_tokens: 20984, cache_creation_input_tokens: 12282 },
  modelUsage: { "claude-sonnet-5": { inputTokens: 2, outputTokens: 573, costUSD: 0.0885 } },
});

test("extractSessionUsage finds the final result line in stream-json NDJSON output", () => {
  const raw = [
    JSON.stringify({ type: "system", subtype: "init" }),
    JSON.stringify({ type: "assistant", message: { content: [] } }),
    REAL_RESULT_LINE,
    "",
  ].join("\n");
  const usage = extractSessionUsage(raw);
  assert.equal(usage.total_cost_usd, 0.0891722);
  assert.equal(usage.input_tokens, 2);
  assert.equal(usage.output_tokens, 573);
  assert.equal(usage.cache_read_input_tokens, 20984);
  assert.equal(usage.cache_creation_input_tokens, 12282);
  assert.equal(usage.is_error, false);
  assert.deepEqual(usage.model_usage, { "claude-sonnet-5": { inputTokens: 2, outputTokens: 573, costUSD: 0.0885 } });
});

test("extractSessionUsage uses the LAST result line when several are present", () => {
  const first = JSON.stringify({ type: "result", total_cost_usd: 0.01, usage: {} });
  const raw = [first, REAL_RESULT_LINE].join("\n");
  assert.equal(extractSessionUsage(raw).total_cost_usd, 0.0891722);
});

test("extractSessionUsage returns null when no result event is present (e.g. killed session)", () => {
  const raw = [JSON.stringify({ type: "system", subtype: "init" }), "garbage stderr text\n"].join("\n");
  assert.equal(extractSessionUsage(raw), null);
});

test("extractSessionUsage never throws on malformed/empty input", () => {
  assert.equal(extractSessionUsage(""), null);
  assert.equal(extractSessionUsage(undefined), null);
  assert.equal(extractSessionUsage("{not json"), null);
});

test("recordSession accumulates totals per executor without mutating the input", () => {
  const t0 = emptyTracker();
  const usage1 = extractSessionUsage(REAL_RESULT_LINE);
  const t1 = recordSession(t0, "claude", "MED-01", usage1);
  assert.equal(t0.claude.total_sessions, 0, "input tracker must not be mutated");
  assert.equal(t1.claude.total_sessions, 1);
  assert.ok(Math.abs(t1.claude.total_cost_usd - 0.0891722) < 1e-9);
  assert.equal(t1.claude.last_session.task_id, "MED-01");
  assert.equal(t1.claude.last_session.had_usage_data, true);

  const t2 = recordSession(t1, "claude", "MED-02", usage1);
  assert.equal(t2.claude.total_sessions, 2);
  assert.ok(Math.abs(t2.claude.total_cost_usd - 0.0891722 * 2) < 1e-6);
});

test("recordSession keeps claude and codex totals independent", () => {
  const usage1 = extractSessionUsage(REAL_RESULT_LINE);
  let t = recordSession(emptyTracker(), "claude", "MED-01", usage1);
  t = recordSession(t, "codex", "MED-02", usage1);
  assert.equal(t.claude.total_sessions, 1);
  assert.equal(t.codex.total_sessions, 1);
});

test("recordSession still counts a session with no extractable usage, without fabricating cost", () => {
  const t = recordSession(emptyTracker(), "claude", "X-01", null);
  assert.equal(t.claude.total_sessions, 1);
  assert.equal(t.claude.total_cost_usd, 0);
  assert.equal(t.claude.last_session.had_usage_data, false);
});
