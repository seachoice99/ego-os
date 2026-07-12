"use strict";

const cp = require("child_process");

/**
 * Extracted from claude_task_runner.js unchanged (TOKEN-EFFICIENCY-001)
 * into its own module so a second, independent caller -- codex_usage.js's
 * `codex app-server` timeout/cleanup path -- can reuse the same
 * hard-learned Windows tree-kill logic without a circular require back
 * into claude_task_runner.js (which itself requires this module).
 *
 * `taskkill /F /T /PID X` is a documented-unreliable heuristic on Windows
 * for anything beyond a shallow tree -- proven live by this module's own
 * tests: it reliably killed the direct child (cmd.exe) but left a
 * grandchild several process-layers deep (cmd.exe -> claude.cmd ->
 * claude.exe, or in tests cmd.exe -> node -> node) still running. Walk the
 * real process tree ourselves (via WMI's Win32_Process on Windows, via
 * `ps -eo pid,ppid` on Linux/macOS -- same ParentProcessId-based algorithm
 * either way) and kill every descendant explicitly, rather than trusting a
 * single-pass heuristic to cascade correctly.
 */
function listProcessParents() {
  if (process.platform === "win32") {
    const query = cp.spawnSync("powershell", [
      "-NoProfile", "-Command",
      "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId | ConvertTo-Json -Compress",
    ], { encoding: "utf8", windowsHide: true });
    try {
      const parsed = JSON.parse(query.stdout || "[]");
      const list = Array.isArray(parsed) ? parsed : [parsed];
      return list.map((p) => ({ pid: p.ProcessId, ppid: p.ParentProcessId }));
    } catch {
      return [];
    }
  }
  const query = cp.spawnSync("ps", ["-eo", "pid,ppid"], { encoding: "utf8" });
  if (query.status !== 0 || !query.stdout) return [];
  return query.stdout
    .split("\n")
    .slice(1) // header row
    .map((line) => line.trim().split(/\s+/).map(Number))
    .filter(([pid, ppid]) => Number.isFinite(pid) && Number.isFinite(ppid))
    .map(([pid, ppid]) => ({ pid, ppid }));
}

function killProcessTree(pid) {
  if (!pid) return;
  const processes = listProcessParents();
  const byParent = new Map();
  for (const p of processes) {
    if (p.ppid == null) continue;
    const list = byParent.get(p.ppid) || [];
    list.push(p.pid);
    byParent.set(p.ppid, list);
  }
  const toKill = [];
  const stack = [Number(pid)];
  const seen = new Set();
  while (stack.length) {
    const current = stack.pop();
    if (seen.has(current)) continue;
    seen.add(current);
    toKill.push(current);
    for (const child of byParent.get(current) || []) stack.push(child);
  }
  for (const targetPid of toKill) {
    if (process.platform === "win32") {
      cp.spawnSync("taskkill", ["/F", "/PID", String(targetPid)], { windowsHide: true });
    } else {
      try {
        process.kill(targetPid, "SIGKILL");
      } catch {
        /* already gone -- not an error */
      }
    }
  }
}

module.exports = { listProcessParents, killProcessTree };
