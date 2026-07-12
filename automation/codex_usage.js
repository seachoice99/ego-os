"use strict";

/**
 * Codex (ChatGPT) rate-limit snapshot, via the OFFICIAL `codex app-server`
 * JSON-RPC protocol -- never OAuth/credential files, never an
 * undocumented HTTP endpoint, never browser automation.
 *
 * Verified against the real upstream doc (openai/codex,
 * codex-rs/app-server/README.md, fetched live -- not recalled from
 * training data) before writing any of this:
 *   - Transport: stdio, newline-delimited JSON-RPC 2.0, `"jsonrpc":"2.0"`
 *     omitted on the wire (matches the doc's own examples exactly).
 *   - Handshake: `initialize` (id 0) then an `initialized` notification
 *     must precede any other call on the connection.
 *   - `account/rateLimits/read` really exists and really returns
 *     `{ rateLimits: { primary, secondary, rateLimitReachedType },
 *        rateLimitResetCredits: { availableCount, credits } }`,
 *     where `primary`/`secondary` are each `{ usedPercent,
 *     windowDurationMins, resetsAt }` with `resetsAt` a UNIX-SECONDS
 *     timestamp (not an ISO string) -- confirmed from the doc's own
 *     worked example, not assumed.
 *   - There is no dollar "credit balance" field anywhere in this
 *     response. The only credit-shaped data the real API returns is
 *     `rateLimitResetCredits` (a count of EARNED rate-limit resets, a
 *     distinct concept from a monetary balance) -- this module reports
 *     that real field under `reset_credits` rather than inventing a
 *     `credits.balance` shape that doesn't exist in the real protocol.
 *   - `plan_type` isn't part of the rate-limits response either; it comes
 *     from `account/read`'s `account.planType`, so this module calls both.
 */

const cp = require("child_process");
const { killProcessTree } = require("./process_tree.js");

const CODEX_BINARY = process.env.EGO_OS_CODEX_APP_SERVER_PATH || "codex";
const DEFAULT_TIMEOUT_MS = 10000;
const LOW_THRESHOLD_PERCENT = 15;

// --- pure: JSON-RPC message construction -----------------------------------

function buildRequest(method, id, params) {
  const msg = { method, id };
  if (params !== undefined) msg.params = params;
  return JSON.stringify(msg) + "\n";
}

function buildNotification(method, params) {
  const msg = { method };
  if (params !== undefined) msg.params = params;
  return JSON.stringify(msg) + "\n";
}

// --- pure: response shape -> normalized snapshot ---------------------------

function toWindow(raw) {
  if (!raw || typeof raw !== "object") return null;
  const usedPercent = typeof raw.usedPercent === "number" ? raw.usedPercent : null;
  const remainingPercent = usedPercent === null ? null : Math.max(0, Math.min(100, 100 - usedPercent));
  const windowDurationMinutes = typeof raw.windowDurationMins === "number" ? raw.windowDurationMins : null;
  const resetsAt = typeof raw.resetsAt === "number" ? new Date(raw.resetsAt * 1000).toISOString() : null;
  return {
    used_percent: usedPercent,
    remaining_percent: remainingPercent,
    window_duration_minutes: windowDurationMinutes,
    resets_at: resetsAt,
  };
}

// A response with no measurable window at all (both primary/secondary
// null/absent) is still a *successful, valid* read -- "available" is the
// honest default, distinct from "unknown" (reserved for a failed/invalid
// read per the rules below).
function classifyStatus({ primary, secondary, rateLimitReachedType }) {
  if (rateLimitReachedType) return "exhausted";
  const remaining = [primary, secondary]
    .filter(Boolean)
    .map((w) => w.remaining_percent)
    .filter((v) => typeof v === "number");
  if (!remaining.length) return "available";
  const min = Math.min(...remaining);
  if (min <= 0) return "exhausted";
  if (min <= LOW_THRESHOLD_PERCENT) return "low";
  return "available";
}

function unknownSnapshot(reason) {
  return {
    status: "unknown",
    checked_at: new Date().toISOString(),
    plan_type: null,
    primary: null,
    secondary: null,
    reset_credits: null,
    rate_limit_reached_type: null,
    error: String(reason || "unknown error").slice(0, 300),
  };
}

// rawResult is the exact `result` object from a real account/rateLimits/read
// response (per codex-rs/app-server/README.md) -- shape never guessed.
function normalizeRateLimitsResult(rawResult, { planType = null, checkedAt } = {}) {
  if (!rawResult || typeof rawResult !== "object" || !rawResult.rateLimits) {
    return unknownSnapshot("malformed account/rateLimits/read response (missing rateLimits)");
  }
  const rl = rawResult.rateLimits;
  const primary = toWindow(rl.primary);
  const secondary = toWindow(rl.secondary);
  const rateLimitReachedType = rl.rateLimitReachedType || null;
  const resetCreditsRaw = rawResult.rateLimitResetCredits || null;
  const resetCredits = resetCreditsRaw
    ? {
        available_count: typeof resetCreditsRaw.availableCount === "number" ? resetCreditsRaw.availableCount : null,
        credits: Array.isArray(resetCreditsRaw.credits) ? resetCreditsRaw.credits : null,
      }
    : null;
  return {
    status: classifyStatus({ primary, secondary, rateLimitReachedType }),
    checked_at: checkedAt || new Date().toISOString(),
    plan_type: planType,
    primary,
    secondary,
    reset_credits: resetCredits,
    rate_limit_reached_type: rateLimitReachedType,
    error: null,
  };
}

// --- pure: console report -------------------------------------------------

function fmtWindow(label, w) {
  if (!w || typeof w.remaining_percent !== "number") return `${label}: нет данных`;
  const resets = w.resets_at ? new Date(w.resets_at).toLocaleString("ru-RU") : "неизвестно";
  return `${label}: ${w.remaining_percent}% remaining, resets ${resets}`;
}

function formatConsoleReport(taskId, snapshot) {
  const lines = [
    `CODEX USAGE AFTER ${taskId}`,
    `Status: ${snapshot.status}`,
    fmtWindow("5h window", snapshot.primary),
    fmtWindow("Weekly window", snapshot.secondary),
    `Credits: ${snapshot.reset_credits && typeof snapshot.reset_credits.available_count === "number"
      ? `${snapshot.reset_credits.available_count} earned reset(s) available`
      : "unavailable"}`,
    `Checked: ${snapshot.checked_at}`,
  ];
  if (snapshot.error) lines.push(`Error: ${snapshot.error}`);
  return lines.join("\n");
}

// --- impure: talk to a real `codex app-server` child process --------------
//
// initialize -> initialized -> account/read -> account/rateLimits/read,
// correlating responses by numeric id only. Every exit path (success,
// protocol error, timeout, spawn failure) resolves to a normalized
// snapshot -- this function never rejects/throws -- and every exit path
// tears the child process down via the same Windows-safe tree-kill used
// elsewhere in this codebase (process_tree.js), never left running.
function fetchCodexUsageSnapshot({ timeoutMs = DEFAULT_TIMEOUT_MS, binaryPath = CODEX_BINARY } = {}) {
  return new Promise((resolve) => {
    let settled = false;
    let buffer = "";
    let planType = null;
    let child = null;

    const finish = (snapshot) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (child && child.pid) killProcessTree(child.pid);
      resolve(snapshot);
    };

    const timer = setTimeout(
      () => finish(unknownSnapshot(`codex app-server did not respond within ${timeoutMs}ms`)),
      timeoutMs,
    );

    try {
      child = cp.spawn(binaryPath, ["app-server"], { windowsHide: true, shell: true });
    } catch (error) {
      finish(unknownSnapshot(`failed to spawn codex app-server: ${error.message}`));
      return;
    }

    child.on("error", (error) => finish(unknownSnapshot(`codex app-server process error: ${error.message}`)));

    if (child.stdout) {
      child.stdout.on("data", (chunk) => {
        buffer += chunk.toString();
        let idx;
        while ((idx = buffer.indexOf("\n")) >= 0) {
          const line = buffer.slice(0, idx).trim();
          buffer = buffer.slice(idx + 1);
          if (!line || line[0] !== "{") continue;
          let msg;
          try {
            msg = JSON.parse(line);
          } catch {
            continue; // a stray non-JSON stdout line (e.g. a log) must never crash this
          }
          if (msg.id === 1) {
            // account/read response (success or error -- planType is
            // enrichment only, never required to proceed to the read that
            // actually matters).
            planType = (msg.result && msg.result.account && msg.result.account.planType) || null;
            if (child.stdin) child.stdin.write(buildRequest("account/rateLimits/read", 2));
          } else if (msg.id === 2) {
            if (msg.error) {
              finish(unknownSnapshot(`account/rateLimits/read error: ${(msg.error && msg.error.message) || "unknown"}`));
            } else {
              finish(normalizeRateLimitsResult(msg.result, { planType }));
            }
          } else if (msg.id === 0 && msg.error) {
            finish(unknownSnapshot(`initialize error: ${(msg.error && msg.error.message) || "unknown"}`));
          }
        }
      });
    }

    if (child.stdin) {
      child.stdin.write(buildRequest("initialize", 0, {
        clientInfo: { name: "ego_os_runner", title: "Ego OS Runner", version: "1.0.0" },
      }));
      child.stdin.write(buildNotification("initialized"));
      child.stdin.write(buildRequest("account/read", 1, { refreshToken: false }));
    }
  });
}

module.exports = {
  CODEX_BINARY, DEFAULT_TIMEOUT_MS, LOW_THRESHOLD_PERCENT,
  buildRequest, buildNotification,
  toWindow, classifyStatus, unknownSnapshot, normalizeRateLimitsResult,
  formatConsoleReport,
  fetchCodexUsageSnapshot,
};
