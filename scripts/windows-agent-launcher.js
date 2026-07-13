#!/usr/bin/env node
"use strict";

/**
 * Single-process Scheduled Task entrypoint for the Windows Runner Agent.
 * It replaces the fragile hidden PowerShell -> node process chain: load the
 * already ACL-protected credential file, tee diagnostics to a local log, and
 * invoke windows_agent.js in this same Node process.
 */

const fs = require("fs");
const os = require("os");
const path = require("path");
const util = require("util");

const ROOT = path.resolve(__dirname, "..");
const LOCAL = process.env.LOCALAPPDATA || os.homedir();
const CONTROL_DIR = path.join(LOCAL, "EgoOS", "claude-runner", "control");
const LOG_DIR = path.join(LOCAL, "EgoOS", "claude-runner", "logs");
const CREDENTIAL_FILE = path.join(CONTROL_DIR, "agent_token.env");
const ALLOWED_ENV_KEYS = new Set(["EGO_OS_AGENT_TOKEN", "EGO_OS_AGENT_SERVER_URL"]);

function parseAgentEnvironment(text) {
  const parsed = {};
  for (const rawLine of String(text || "").split(/\r?\n/)) {
    const index = rawLine.indexOf("=");
    if (index <= 0) continue;
    const key = rawLine.slice(0, index).trim();
    if (!ALLOWED_ENV_KEYS.has(key)) continue;
    parsed[key] = rawLine.slice(index + 1).trim();
  }
  return parsed;
}

function loadAgentEnvironment(file = CREDENTIAL_FILE) {
  const values = parseAgentEnvironment(fs.readFileSync(file, "utf8"));
  if (!values.EGO_OS_AGENT_TOKEN) throw new Error(`Agent token missing from ${file}`);
  for (const [key, value] of Object.entries(values)) process.env[key] = value;
  return Object.keys(values);
}

function installFileLogger(logDir = LOG_DIR) {
  fs.mkdirSync(logDir, { recursive: true });
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const logFile = path.join(logDir, `windows-agent-${stamp}.log`);
  const append = (level, args) => {
    const message = util.format(...args);
    fs.appendFileSync(logFile, `${new Date().toISOString()} ${level} ${message}\n`, "utf8");
  };
  console.log = (...args) => append("INFO", args);
  console.error = (...args) => append("ERROR", args);
  return logFile;
}

async function launch() {
  process.chdir(ROOT);
  loadAgentEnvironment();
  const logFile = installFileLogger();
  console.log(`Direct Node launcher starting; log=${logFile}`);
  const agent = require("../automation/windows_agent.js");
  const code = await agent.main();
  console.error(`WINDOWS_AGENT_PROCESS_EXIT code=${code || 0}`);
  return code || 0;
}

module.exports = { parseAgentEnvironment, loadAgentEnvironment, installFileLogger, launch };

if (require.main === module) {
  launch()
    .then((code) => { process.exitCode = code; })
    .catch((error) => {
      try {
        fs.mkdirSync(LOG_DIR, { recursive: true });
        fs.appendFileSync(path.join(LOG_DIR, "windows-agent-launch-fatal.log"), `${new Date().toISOString()} ${error.stack || error}\n`, "utf8");
      } catch { /* the original error is still reported below */ }
      process.stderr.write(`FATAL Windows agent launcher: ${error.stack || error}\n`);
      process.exitCode = 1;
    });
}
