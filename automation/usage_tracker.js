"use strict";

/**
 * Pure logic for the casual dashboard's "limits" tracker. No I/O here --
 * claude_task_runner.js owns the actual tracker file's path/read/write,
 * exactly like session_manager.js stays pure while claude_task_runner.js
 * owns LOG_DIR/HANDOFF_DIR etc.
 *
 * Why this exists instead of shelling out to a "/usage"-style command:
 * verified live that `claude -p "/usage"` is NOT a local command in
 * non-interactive mode -- it is sent to the model as ordinary text, which
 * spent real cost ($0.09, 2 turns) and produced nothing usable. What IS
 * free and already flowing through this codebase: every ordinary
 * `claude -p --output-format stream-json` session already ends with one
 * `{"type":"result", "total_cost_usd":..., "usage":{...}, "modelUsage":{...}}`
 * line -- the exact same stdout buffer claude_task_runner.js already
 * captures for rate-limit/fatal-pattern detection. This module just reads
 * that line a second time, for a different purpose, at zero extra cost.
 */

// Scans from the end of the output backwards -- the CLI may emit several
// `type: "result"` intermediate events in one session (per iteration of a
// multi-turn run); the LAST one reflects the session's final, cumulative
// totals, not a partial mid-session snapshot.
function extractSessionUsage(rawOutput) {
  const lines = String(rawOutput || "").split("\n");
  for (let i = lines.length - 1; i >= 0; i -= 1) {
    const line = lines[i].trim();
    if (!line || line[0] !== "{") continue;
    let parsed;
    try {
      parsed = JSON.parse(line);
    } catch {
      continue;
    }
    if (parsed && parsed.type === "result") {
      const usage = parsed.usage || {};
      return {
        total_cost_usd: typeof parsed.total_cost_usd === "number" ? parsed.total_cost_usd : null,
        num_turns: typeof parsed.num_turns === "number" ? parsed.num_turns : null,
        input_tokens: typeof usage.input_tokens === "number" ? usage.input_tokens : null,
        output_tokens: typeof usage.output_tokens === "number" ? usage.output_tokens : null,
        cache_read_input_tokens: typeof usage.cache_read_input_tokens === "number" ? usage.cache_read_input_tokens : null,
        cache_creation_input_tokens: typeof usage.cache_creation_input_tokens === "number" ? usage.cache_creation_input_tokens : null,
        model_usage: parsed.modelUsage || null,
        is_error: Boolean(parsed.is_error),
      };
    }
  }
  return null; // no final result event found -- e.g. a killed/timed-out session; never guessed
}

function emptyExecutorUsage() {
  return {
    total_sessions: 0,
    total_cost_usd: 0,
    total_input_tokens: 0,
    total_output_tokens: 0,
    total_cache_read_tokens: 0,
    total_cache_creation_tokens: 0,
    last_session: null,
  };
}

function emptyTracker() {
  return { claude: emptyExecutorUsage(), codex: emptyExecutorUsage() };
}

// Returns a NEW tracker object (never mutates the input) with one
// executor's running totals advanced by one session's real, observed
// usage. A session with no extractable usage (extractSessionUsage
// returned null -- e.g. the process was killed before printing a final
// result line) still counts toward total_sessions, since a real attempt
// happened, but contributes zero to the cost/token totals rather than a
// guessed number.
function recordSession(trackerState, executor, taskId, sessionUsage) {
  const key = executor === "codex" ? "codex" : "claude";
  const base = (trackerState && trackerState[key]) || emptyExecutorUsage();
  const usage = sessionUsage || {};
  const next = {
    total_sessions: base.total_sessions + 1,
    total_cost_usd: base.total_cost_usd + (usage.total_cost_usd || 0),
    total_input_tokens: base.total_input_tokens + (usage.input_tokens || 0),
    total_output_tokens: base.total_output_tokens + (usage.output_tokens || 0),
    total_cache_read_tokens: base.total_cache_read_tokens + (usage.cache_read_input_tokens || 0),
    total_cache_creation_tokens: base.total_cache_creation_tokens + (usage.cache_creation_input_tokens || 0),
    last_session: {
      task_id: taskId || null,
      recorded_at: new Date().toISOString(),
      total_cost_usd: usage.total_cost_usd ?? null,
      input_tokens: usage.input_tokens ?? null,
      output_tokens: usage.output_tokens ?? null,
      cache_read_input_tokens: usage.cache_read_input_tokens ?? null,
      cache_creation_input_tokens: usage.cache_creation_input_tokens ?? null,
      model_usage: usage.model_usage || null,
      had_usage_data: Boolean(sessionUsage),
    },
  };
  return { ...emptyTracker(), ...trackerState, [key]: next };
}

module.exports = { extractSessionUsage, emptyExecutorUsage, emptyTracker, recordSession };
