# Claude Task Runner

The runner selects one `ready` task, starts Claude Code non-interactively, and authorizes task-scoped implementation, tests, commit, push to `main`, Ego OS deploy, and health verification. It stops on the first failure. A local lock prevents two runners from claiming work simultaneously.

Owner approval remains mandatory for destructive data operations, irreversible migrations, payments, secrets, external publication, and infrastructure outside Ego OS. Code rollback cannot reverse those effects.

## Prerequisites

- clean local `main`, identical to `origin/main`;
- Claude Code CLI installed and authenticated;
- GitHub credentials available to Git;
- deployment key at `~/.ssh/ego_os_deploy`;
- Node.js (already installed with Claude Code).

## Commands

```powershell
# Preview next task
node automation\claude_task_runner.js --dry-run

# Run one task
node automation\claude_task_runner.js

# Continue polling until the queue is empty or a task fails
node automation\claude_task_runner.js --watch
```

Logs stay outside Git under `%LOCALAPPDATA%\EgoOS\claude-runner\logs`. The runner uses Claude Code unattended permissions. Only trusted prompts may enter the queue.

On failure, inspect the task YAML, external log, `git status`, origin, tests, and production. Clean or complete failed work before restarting. Never remove `%LOCALAPPDATA%\ego-os-claude-runner.lock` while a runner is active.

## Final-sync protocol (`release_sync.js`)

An automatic-release task deploys its implementation commit, then records deploy/health-check evidence in its own task YAML and pushes that as a *separate* final metadata commit. Left alone, that final commit is never itself deployed -- found live after `RUNNER-001`, where production silently ended up one commit behind `origin/main` despite the task reporting "done". `automation/release_sync.js` is the pure decision logic (no I/O) the runner's prompt now requires Claude to follow before it may claim `done`:

1. Confirm production HEAD equals the just-deployed implementation commit; confirm local HEAD equals `origin/main`. Either mismatch means something changed out of band -- stop, don't sync.
2. Confirm every commit between the implementation commit and `origin/main` HEAD is this task's own (`<task.id>: ...` prefix) -- a foreign commit interleaved mid-run also stops the task rather than being fast-forwarded over.
3. Classify the changed paths in that range: if it's exclusively the task's own YAML (or another explicitly permitted release-metadata path), `git pull --ff-only` production with **no restart**. If it touches `ego_os/`, `requirements*`, templates, static, config, or a migration, the normal deploy/restart/health-check cycle is required instead -- never skipped.
4. Only `git pull --ff-only` is used for this reconciliation, never `git reset` or a force push.
5. The result is recorded as `result.final_sync = {local_head, origin_head, production_head, restart_performed}`. The runner itself (not just Claude's self-report) refuses to accept `status: "done"` on an `automatic`-release task unless `release_sync.verifyFinalSyncEvidence()` confirms all three heads actually match -- a task cannot silently end "done" with production left behind.

Run its unit tests with `node --test` (from the repo root) or `node --test automation/release_sync.test.js` directly -- no npm dependency required, matching the runner's own dependency-free design.

## `blocked` as a legitimate, non-failure terminal state

A task can legitimately conclude it must stop for a real Owner decision it has no authority to make itself (e.g. accepting a real Digital Asset Candidate — ADR-0007 never lets an automatic process accept its own nomination). `tasks/queue/README.md`'s state diagram already documents `ready → blocked`. If Claude finishes cleanly (process exit 0, clean working tree) and sets the task's own `status` to `"blocked"`, the runner treats that as success (`return true`, process exit 0) — it does **not** overwrite the status to `"failed"`. This is distinct from the pre-flight `owner_approved` gate at the top of `execute()`, which still treats an unapproved `OWNER_ONLY` risk as a queueing mistake and returns `false`/exit 1, unchanged.

## TOKEN-EFFICIENCY-001: staged execution (`session_manager.js`)

**Problem, measured from this repository's own runner logs, not guessed:** a single unbounded `claude -p` session for one task grows turn over turn. `RUNNER-002`, a trivial documentation task, used 46 turns and 3.1M cache-read tokens; `DA-02`, a real feature, used 86 turns and 9.3M cache-read tokens; `DA-03` burned 55 turns and 4.2M cache-read tokens *without finishing*. Starting prompts were already lean (6-9KB, reference `CLAUDE.md`/`AI_ONBOARDING.md` rather than embedding them) — the growth is turn-over-turn context accumulation within one long session, not the initial prompt. The fix is bounding how long any single session runs and handing off to a **fresh** session via a small, structured file instead of replaying the conversation.

### Session isolation

Every stage is a brand-new `claude -p` process — `--continue`/`--resume` are never passed anywhere in this codebase (`session_manager.claudeInvocationArgs` is the one place argv is built, and it is unit-tested to prove this). A stage that runs out of time is not resumed in place; a fresh process starts with a small prompt built from the task YAML, current Git state, and the previous stage's handoff file — never the old process's conversation.

### Optional YAML fields (existing tasks work unchanged without any of these)

- `checkpoints: [{title, prompt, model?}, ...]` — an explicit, task-author-declared stage plan. Each checkpoint becomes its own fresh session with its own focused `PROMPT` section. If omitted, the runner falls back to **adaptive** staging: it never pre-emptively splits a task, only if a stage actually exhausts its budget.
- `max_duration_minutes` — per-stage wall-clock budget (overrides the CLI's `--timeout-minutes` for this task only).
- `max_auto_stages` — caps how many adaptive (non-`checkpoints`) stages a task may use before it is treated as failed (default 4, `session_manager.DEFAULT_MAX_AUTO_STAGES`). Never unbounded — a task that keeps timing out fails after this many attempts rather than looping forever.
- `context_strategy: "single"` — explicit opt-out of all auto-staging: a timeout is a hard failure, exactly like the pre-TOKEN-EFFICIENCY-001 runner. Use for a task that must never be split (rare).
- `model` — passed through as `--model <id>`. No automatic "pick a cheaper model for this task" classifier is implemented — that would be guessing at something this runner cannot reliably verify. Task authors set it explicitly; the recommended split (not enforced) is a smaller/cheaper model for reading logs, checking status, and mechanical documentation edits, and a stronger model for architecture, non-trivial code, and final review.
- `token_budget` — recorded and surfaced in `result.sessions[].prompt_approx_tokens`/logs for the Owner's own comparison; not causally enforced mid-session (no reliable native mechanism to meter a running session's token usage from outside it exists today — this is deliberately honest about that limit rather than pretending to enforce something it cannot).

### Handoff protocol

Every stage — whether it finishes the task or merely runs out of time — is instructed to write a handoff file to a fixed, runner-provided path (`%LOCALAPPDATA%\EgoOS\claude-runner\handoffs\<task_id>.json`, **outside** the Git repo — it never needs a commit) as a single JSON object:

```json
{
  "summary": "what this stage did, one or two sentences",
  "commit": "short commit hash this stage made, or null",
  "changed_files": ["..."],
  "checks": "what was run and its result, briefly",
  "remaining": "what is NOT done yet, or 'nothing -- task complete'",
  "risks": "anything the next stage or Owner should know",
  "next_step": "the single next concrete action"
}
```

`session_manager.validateHandoff()` enforces the shape (all seven fields required) and a 1500-word cap (`HANDOFF_WORD_LIMIT`) before the runner will trust it — an invalid or oversized handoff after a timeout is treated as "no usable handoff", which fails the task rather than guessing. The next stage's prompt embeds this handoff verbatim (`buildHandoffBlock`) alongside the task's own YAML and current Git state (`buildGitStateBlock`) — never the prior session's transcript or a full diff.

### Rate limits

The CLI's own `stream-json` output already emits a `rate_limit_event` line with a `rate_limit_info.status` field; a status other than `"allowed"` (or a recognizable plain-text phrase such as "usage limit reached") is treated by `session_manager.detectRateLimit()` as a real, expected condition — never a code defect, never retried immediately. The task moves to `status: "waiting_for_limit"` with a `result.retry_after` timestamp (from the event's own `resetsAt` when present, otherwise a conservative five-hour wait matching the observed `five_hour` window). `nextTask()` skips a `waiting_for_limit` task until its `retry_after` has actually passed, then resumes it as a fresh stage using its last saved handoff — no usage-limit workaround, no paid overage credits enabled.

### Observability

Every stage appends one entry to `result.sessions[]`: `stage`, `model`, `started_at`, `duration_ms`, `prompt_chars`/`prompt_approx_tokens` (logged to the console at stage start too), `handoff_words`, `outcome` (`exited_clean` / `exited_error` / `timed_out_or_killed` / `rate_limited`), and its own log file path. Nothing here ever includes `.env` contents, credentials, or raw hidden reasoning.

### A real, Windows-specific process-tree lesson

`taskkill /F /T /PID X` is a documented-unreliable heuristic beyond a shallow process tree — proven live while testing this feature: it correctly killed the direct child (`cmd.exe`) but left a grandchild several process-layers deep (`cmd.exe -> claude.cmd -> claude.exe`, or in tests `cmd.exe -> node -> node`) still running. `killProcessTree()` instead walks the real process tree via WMI (`Get-CimInstance Win32_Process`, using its own `ParentProcessId`) and kills every descendant explicitly. It also does not rely on `spawnSync`'s own built-in `timeout` kill (which fires *before* our code gets control back, by which point the top-level PID is already gone and there's nothing left for a subsequent tree-kill to walk from) — `runClaude()` uses async `cp.spawn` with its own `setTimeout`, so the kill happens on a still-live tree, not a race against Node's own default behavior.

Run the full suite with `node --test` (from the repo root); `claude_task_runner.test.js` spawns a real (but fake/mock) executable (`automation/test_fixtures/fake_claude.js`) through the real runner wiring — never a real Claude Code process — including a global sweep at the end of the file proving zero fake sessions or their descendants survive.

## RUNNER-CONTROL-UI: a fail-closed local control panel

**Problem this exists to fix:** running the queue meant reading logs and killing processes by hand in PowerShell, with no visibility into what the runner is currently doing, and no way to safely pause it mid-task. A real defect motivated the "fail-closed" half of this feature: a child Claude process can print *"Your organization has disabled Claude subscription access for Claude Code..."* and still exit `0`, having already written `status: "done"` to its own task file — exit code and self-report alone were never enough evidence of success.

### Runner-level state machine (`automation/runner_control.js`)

A pure, fully-unit-tested state machine (`stopped → starting → {running, idle} → pause_requested → paused`, plus `stop_requested`, `waiting_for_limit`, `waiting_for_owner`, `authentication_required`, `failed`, `completed`) tracks what the *whole runner* is doing, separate from any one task's own status. Every transition is appended to `%LOCALAPPDATA%\EgoOS\claude-runner\control\events.ndjson` (timestamp, event, previous/new state, reason, task id) and mirrored into `runner_state.json` — both readable with no live connection to the running engine.

### Fail-closed fatal-pattern classification (`session_manager.classifyFatalOutput`)

Checked with the *highest* priority of any signal in `classifySessionOutcome` — before rate-limit detection, and unconditionally before `"done"` can ever be returned. `authentication_required` patterns (subscription/API-key failures) move a task to a new `waiting_for_auth` status, which — unlike `waiting_for_limit` — is **never** auto-retried by `nextTask()`, since an auth failure doesn't self-heal on a timer; it requires an explicit human retry. Other recognized fatal categories (`permission_denied`, `model_unavailable`, `network_failure`) still unconditionally block `"done"`, falling through to `"failed"` with the specific reason recorded.

### Pause / resume / stop-after-stage / emergency-stop semantics

`pause` and `stop_after_stage` are honored **only** at genuinely safe points — between tasks (top of `main()`'s loop) and between stages (top of `execute()`'s stage loop) — never mid-`runClaude()`. A paused task lands at task status `"checkpointing"` with its `sessions[]` intact and resumes via the exact same mechanism `waiting_for_limit` already uses. `emergency_stop` is the one command polled *during* a live session (`runClaude()`'s own interval, separate from its timeout timer); it does tree-kill the process, but never deletes files or resets/checks out anything — the task lands at `"interrupted"` with `result.requires_recovery_check: true`, and `nextTask()` never auto-selects an interrupted task.

### Local control server (`automation/control_server.js`) and dashboard (`automation/web/`)

A dependency-free HTTP server (Node's built-in `http` only) bound to `127.0.0.1` exclusively, with defense in depth rejecting any request whose socket address isn't loopback. It never re-implements the engine's own logic — task loading, process management, and state rules are all required from `claude_task_runner.js`/`runner_control.js`; commands are issued by writing to the same file-based control protocol the engine already polls. Routes: `GET /api/status|tasks|tasks/:id|events|logs`, `POST /api/runner/{start,pause,resume,stop-after-stage,emergency-stop}`, `POST /api/tasks/:id/{hold,unhold,retry,skip}`, `POST /api/tasks/reorder`. Task ids and log filenames are validated and containment-checked against path traversal; request bodies are capped at 64KB and rejected with a real `413` (not a raw connection reset — `req.destroy()` on an oversized body was found live to kill the socket before the `413` could be flushed, and is deliberately not called); `emergency-stop`/`skip`/`retry` require an explicit `{confirm: true}` body; exactly one control server per workspace via its own lock file (`ego-os-control-server.lock`, next to the runner's own).

The dashboard itself is plain HTML/CSS/JS — no framework — dark theme, Russian UI, color-coded status pills, auto-refresh via polling (no page reload), and an offline banner that never lets stale data read as current if the control server becomes unreachable.

**Launch:** `npm run runner-ui` (starts only the control server; use its own "Старт" button, or `npm run runner` directly, to start the runner engine). Both are plain `node` invocations — no build step, no Docker.

## Casual grouped queue view + Claude/Codex usage tracker

**Problem this exists to fix:** a large initiative (e.g. the 7 `MED-*` multi-executor tasks, or the 23-task operational-expansion project) used to occupy 8-9 rows in one flat, technically-worded table — distracting for day-to-day glancing, when what's actually wanted is "is this whole initiative moving, and which one should I prioritize next."

- **Casual project cards** (`automation/project_groups.js`): a pure, id-prefix-based lookup (never a new required task field) groups tasks into a named, casually-described card — e.g. all `MED-*` tasks collapse into "Клод + Кодекс работают вместе". Each card is collapsed by default, shows a plain-language summary and a "done/total" count, and flags itself only when a task inside genuinely needs the Owner's attention (`blocked`/`waiting_for_auth`/`failed`/`interrupted`). Expanding a card (state kept in `localStorage`) reveals the same technical table (id/title/status/actions) the dashboard always had.
- **`display_summary`** (optional per-task field, `tasks/queue/README.md`): a casual one-liner shown instead of the technical `title`; falls back to `title` when absent.
- **Drag-and-drop priority**, both for a whole card (global priority between initiatives) and for rows inside an expanded card (local order within one initiative) — both reuse the existing `POST /api/tasks/reorder` endpoint unchanged (`runner_control.validateReorder` already restricts this to `ready` tasks and already-satisfied `depends_on`); no new backend reorder logic was added. A drag always resubmits the FULL flattened ready-task order from what's currently on screen, never a narrow per-group slice — a partial submission would let two cards independently reuse the same small `queue_order` numbers and silently scramble a previously-established global order. Priority tier (P0-P3) still wins over `queue_order` — dragging only decides order within the same tier.
- **Claude/Codex usage tracker** (`automation/usage_tracker.js`, `GET /api/usage`): verified live that `claude -p "/usage"` is NOT a local command in non-interactive mode — it is sent to the model as ordinary text and spent real cost ($0.09, 2 turns, no result) for nothing. What already exists for free: every ordinary session's own final `{"type":"result", "total_cost_usd":..., "usage":{...}, "modelUsage":{...}}` stream-json line, already captured for rate-limit/fatal-pattern detection. `recordSessionUsage()` parses that same buffer once per finished session (successful or not) and accumulates per-executor totals in `usage_tracker.json` — never a separate command, never a poll-time cost. Codex's session-cost fields stay honestly empty until `MED-02` ships a real Codex path.

## Codex (ChatGPT) rate-limit snapshot (`automation/codex_usage.js`)

**Data source:** the official `codex app-server` JSON-RPC 2.0 protocol (stdio, newline-delimited JSON, `"jsonrpc":"2.0"` omitted on the wire, per `codex-rs/app-server/README.md` — fetched and verified live before writing any of this, never guessed). One short-lived child process per snapshot: `initialize` → `initialized` → `account/read` (for `plan_type`) → `account/rateLimits/read` (for the real `rateLimits`/`rateLimitResetCredits` payload), then the process is always torn down via the same Windows-safe `killProcessTree()` used elsewhere in this codebase (extracted into `automation/process_tree.js` so both `claude_task_runner.js` and `codex_usage.js` can share it without a circular require). Never touches OAuth tokens, credential files, or any undocumented HTTP endpoint.

**A real correction of the initially-assumed shape:** the response has no monetary "credit balance" field at all — `rateLimitResetCredits` is a count of *earned rate-limit resets* (a distinct, non-monetary concept), reported here as `reset_credits`, not invented as `credits.balance`. `resetsAt` is Unix seconds, converted to ISO-8601 here rather than assumed to already be a string.

**When it fires:** once per finished session that actually ran through Codex (`resolvedExecutor === "codex"` in `claude_task_runner.js`'s `execute()`) — done, blocked, failed, waiting_for_limit/auth, interrupted, and stage-continuation all count, since a real child process ran either way. Never during `--dry-run` (structurally impossible: `execute()` itself is never called on that path). **Today this is permanently inert** — no real Codex dispatch exists yet (`MED-02` is still `blocked`), so `resolvedExecutor` is unconditionally `"claude"`; the hook is wired and tested (via `EGO_OS_RUNNER_FORCE_EXECUTOR`, a test-only override) but has nothing to fire on until `MED-02` ships.

**Output:** a console report (`CODEX USAGE AFTER <task-id>`, 5h/weekly window remaining %, resets, credits) plus one JSONL line per snapshot in `%LOCALAPPDATA%\EgoOS\claude-runner\codex-usage.jsonl` — deliberately outside the git-tracked repo, never touching the final-sync protocol or working-tree cleanliness. A failed/timed-out read (10s cap) is logged with `status: "unknown"` and a short, secret-free error string; it never changes the task's own outcome or stops the queue. `GET /api/usage` also folds the latest snapshot into `usage.codex.rate_limits` so the dashboard's casual "Лимиты" panel shows real Codex data the moment one exists, independent of whether any Codex session has ever run.
