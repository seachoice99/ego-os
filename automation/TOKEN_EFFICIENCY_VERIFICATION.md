# TOKEN-EFFICIENCY-001: real-runner verification

This note records that TOKEN-EFFICIENCY-001's staged-execution machinery has been exercised by a real Claude Code session (this task, `TOKEN-EFFICIENCY-VERIFY`, run through `automation/claude_task_runner.js` against the actual `claude` CLI) — not just the fake-executable integration tests in `automation/claude_task_runner.test.js`.

## What TOKEN-EFFICIENCY-001 changed

Before TOKEN-EFFICIENCY-001, a task ran as one unbounded `claude -p` session from start to finish. TOKEN-EFFICIENCY-001 (`automation/session_manager.js`, wired into `automation/claude_task_runner.js`) replaced that with **staged execution**: a task is split across one or more fresh `claude -p` processes (stages), each bounded by `max_duration_minutes`, with `--continue`/`--resume` never used anywhere. Instead, a stage that runs out of time hands off to the next stage through a small, structured **handoff file** (`%LOCALAPPDATA%\EgoOS\claude-runner\handoffs\<task_id>.json`, outside Git) — a fixed seven-field JSON object (`summary`, `commit`, `changed_files`, `checks`, `remaining`, `risks`, `next_step`) validated by `validateHandoff()` against a 1500-word cap. The next stage's prompt is built only from the task's own YAML, current Git state, and that handoff — never the prior session's transcript or a full diff. If a real usage/rate limit is hit (detected structurally via the CLI's `rate_limit_event`, not guessed), the task parks as `waiting_for_limit` with a `result.retry_after` timestamp rather than failing or retrying immediately. Separately, while testing this feature, a genuine Windows process-tree defect was found and fixed: `taskkill /F /T /PID` proved unreliable beyond a shallow tree, so `killProcessTree()` now walks the real process tree via WMI (`Get-CimInstance Win32_Process`) and kills every descendant explicitly, and `runClaude()` switched to async `cp.spawn` with its own `setTimeout` so the kill fires against a still-live process tree.

## Why: measured real usage, not a hypothetical

The problem was measured from this repository's own runner logs before the fix was designed: `RUNNER-002`, a trivial documentation task, used 46 turns and 3.1M cache-read tokens in a single session; `DA-02`, a real feature task, used 86 turns and 9.3M cache-read tokens; `DA-03` burned 55 turns and 4.2M cache-read tokens *without finishing*. This is turn-over-turn context accumulation within one long session — starting prompts were already lean — and staged execution with fresh sessions plus a small handoff is the fix.

## This verification

This document itself is the proof: it was produced by `TOKEN-EFFICIENCY-VERIFY`, a task run for real through the runner and a real Claude Code session (not the mock `fake_claude.js` executable used by the automated test suite), following the exact staged-execution and handoff protocol described above and in `automation/README.md`'s "TOKEN-EFFICIENCY-001: staged execution" section.

TOKEN_EFFICIENCY_VERIFIED
