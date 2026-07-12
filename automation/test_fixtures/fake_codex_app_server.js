#!/usr/bin/env node
"use strict";

/**
 * A mock/fake stand-in for `codex app-server`'s stdio JSON-RPC transport,
 * used ONLY by codex_usage.test.js / claude_task_runner.test.js. Never a
 * real Codex process. Speaks exactly the subset of the real protocol this
 * codebase's client (automation/codex_usage.js) actually calls:
 * initialize (id 0) -> account/read (id 1) -> account/rateLimits/read
 * (id 2), newline-delimited JSON, no "jsonrpc" key on the wire (matching
 * the real app-server's own README).
 *
 * Controlled via EGO_OS_FAKE_CODEX_SCENARIO:
 *   full_response   -- primary+secondary+resetCredits+planType, all healthy
 *   primary_only     -- only primary present, no secondary/resetCredits
 *   exhausted        -- rateLimitReachedType set
 *   low              -- primary.usedPercent high enough to classify "low"
 *   noisy_then_valid -- emits one garbage non-JSON line before each real
 *                       reply, proving the client skips it without crashing
 *   error_on_ratelimits -- account/rateLimits/read replies with a JSON-RPC error
 *   hang             -- never replies to anything (client must time out)
 */

const scenario = process.env.EGO_OS_FAKE_CODEX_SCENARIO || "full_response";

function write(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

if (scenario === "hang") {
  setInterval(() => {}, 1000); // never responds -- the client's own timeout must fire and kill this
} else {
  let buffer = "";
  process.stdin.on("data", (chunk) => {
    buffer += chunk.toString();
    let idx;
    while ((idx = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, idx).trim();
      buffer = buffer.slice(idx + 1);
      if (!line) continue;
      let msg;
      try { msg = JSON.parse(line); } catch { continue; }
      handle(msg);
    }
  });
}

function handle(msg) {
  if (scenario === "noisy_then_valid") process.stdout.write("not json, just a stray log line\n");

  if (msg.method === "initialize") {
    write({ id: msg.id, result: { userAgent: "fake-codex/0.0.0", codexHome: "/fake/codex/home" } });
    return;
  }
  if (msg.method === "initialized") return; // notification, no response
  if (msg.method === "account/read") {
    const planType = scenario === "full_response" || scenario === "primary_only" || scenario === "low" ? "pro" : null;
    write({ id: msg.id, result: { account: { type: "chatgpt", email: "test@example.com", planType } } });
    return;
  }
  if (msg.method === "account/rateLimits/read") {
    if (scenario === "error_on_ratelimits") {
      write({ id: msg.id, error: { code: -32000, message: "not authenticated" } });
      return;
    }
    if (scenario === "primary_only") {
      write({ id: msg.id, result: { rateLimits: { primary: { usedPercent: 10, windowDurationMins: 300, resetsAt: 1730947200 }, secondary: null, rateLimitReachedType: null } } });
      return;
    }
    if (scenario === "exhausted") {
      write({ id: msg.id, result: { rateLimits: { primary: { usedPercent: 100, windowDurationMins: 300, resetsAt: 1730947200 }, secondary: null, rateLimitReachedType: "primary" } } });
      return;
    }
    if (scenario === "low") {
      write({ id: msg.id, result: { rateLimits: { primary: { usedPercent: 90, windowDurationMins: 300, resetsAt: 1730947200 }, secondary: { usedPercent: 20, windowDurationMins: 10080, resetsAt: 1731552000 }, rateLimitReachedType: null } } });
      return;
    }
    // full_response / noisy_then_valid
    write({
      id: msg.id,
      result: {
        rateLimits: {
          primary: { usedPercent: 25, windowDurationMins: 300, resetsAt: 1730947200 },
          secondary: { usedPercent: 59, windowDurationMins: 10080, resetsAt: 1731552000 },
          rateLimitReachedType: null,
        },
        rateLimitResetCredits: { availableCount: 2, credits: [{ id: "RateLimitResetCredit_1", resetType: "codexRateLimits", status: "available" }] },
      },
    });
  }
}
