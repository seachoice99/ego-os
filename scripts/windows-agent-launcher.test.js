"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { parseAgentEnvironment } = require("./windows-agent-launcher.js");

test("parseAgentEnvironment accepts only the two runner keys and preserves '=' inside values", () => {
  assert.deepEqual(parseAgentEnvironment([
    "EGO_OS_AGENT_TOKEN=abc=def",
    "EGO_OS_AGENT_SERVER_URL=https://os.fiveseven.ru",
    "UNRELATED_SECRET=must-not-be-loaded",
    "malformed",
  ].join("\n")), {
    EGO_OS_AGENT_TOKEN: "abc=def",
    EGO_OS_AGENT_SERVER_URL: "https://os.fiveseven.ru",
  });
});
