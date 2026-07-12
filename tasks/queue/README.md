# Autonomous task queue

Each executable task is one `.yaml` file containing JSON syntax (JSON is valid YAML). This keeps the first runner dependency-free. The runner selects the highest-priority `ready` task and never runs two tasks at once.

```text
ready → in_progress → testing → deploying → done
                          ↓         ↘ failed
                   waiting_for_limit ↗ (resumes as a fresh stage once retry_after passes)
ready → blocked
```

Priority order is P0, P1, P2, P3. Dependencies must be resolved before a task is marked `ready`; the first version intentionally does not infer dependency completion.

`release: automatic` authorizes commit, push to `main`, deploy, and health check. `release: no_deploy` forbids deploy.

**TOKEN-EFFICIENCY-001** (see `automation/README.md`): a large task no longer has to run as one unbounded session. Optional fields `checkpoints`, `max_duration_minutes`, `max_auto_stages`, `context_strategy`, `model`, `token_budget` control staged execution across fresh, independent sessions handed off via a small structured file — omitting all of them reproduces the original single-session behavior exactly. `waiting_for_limit` is a legitimate, expected pause (a real Claude usage/rate limit, not a code defect) with a recorded `result.retry_after`; the runner will not pick the task back up before that time.

**RUNNER-CONTROL-UI** (see `automation/README.md`'s own section): a task may also reach `checkpointing` (paused between stages by a human's Pause/Stop-after-stage command via `npm run runner-ui`'s dashboard — resumes automatically, exactly like `waiting_for_limit`), `waiting_for_auth` (an auth/subscription failure was detected in the session's own output — unlike `waiting_for_limit`, this is **never** auto-retried; a human must fix access and explicitly retry it), `interrupted` (an emergency stop cut a session short mid-flight — no files deleted, no Git reset, but requires a recovery check before it runs again), `held` (a human paused a `ready` task without running it), or `skipped` (a human explicitly skipped it, with a recorded reason). None of these states are reachable from an ordinary `ready → in_progress → done` run without an explicit human action or a real fatal condition.

Risks `destructive_data`, `irreversible_migration`, `payments`, `secrets`, and `external_infrastructure` require `owner_approved: true`. The prompt is trusted execution input: never copy unreviewed community prompts into this queue.

**EGO OS OPERATIONAL EXPANSION** (`ERE-*`, `RCI-*`, `UOP-*`, `CCTV-*` — see `projects/ego-os-operational-expansion/PROJECT.md`): each task additionally carries `depends_on` (an informational list of task ids that should complete first) and `estimated_minutes`. Neither is enforced automatically by the runner today — `nextTask()` does not check `depends_on` when picking a `ready` task (only `runner_control.validateReorder()`, used by the control server's reorder API, checks it, and only among already-`ready` tasks). Whoever promotes a `blocked` task to `ready` is responsible for checking its `depends_on` first. All 23 tasks in this initiative start `status: "blocked"` and were not executed as part of the planning session that created them.

**MULTI-EXECUTOR DISPATCH** (`MED-*` — see `memory/decisions/ADR-0012-multi-executor-task-dispatch.md` and `architecture/017_MULTI_EXECUTOR_DISPATCH.md`): adds `executor: claude|codex|auto|openrouter_free` (extending `RCI-01`/`RCI-02`'s schema), plus `model_tier` (`free|standard|strong`) and `review_executor` (an executor that must independently review before `done`). `codex` and `openrouter_free` are valid schema values with **no valid runtime path** until `MED-02`/`MED-03` ship respectively — `execute()` fails closed exactly as it already does for any unimplemented executor, never silently running the task as Claude or silently ignoring the field. Dispatch is always sequential — one child CLI process at a time, even once both Claude and Codex participate — so no cross-executor file/git-push race is possible by construction; "multi-executor" describes which binary a task uses, never two simultaneous writers to the same checkout. `MED-01` (a read-only Codex CLI recon task) has no dependency and may run immediately; the rest (`MED-02`..`MED-07`) start `status: "blocked"`.

**`display_summary`** (optional, any task): a short, casual, plain-language one-liner shown by the dashboard's grouped card view instead of the technical `title` (e.g. "Проверяем, что вообще умеет Codex, ничего не ломая" instead of "Multi-Executor Dispatch: Codex CLI recon (read-only)"). Falls back to `title` when absent — old tasks need no change. Which casual "project" card a task groups under (`automation/project_groups.js`) is derived from its id prefix, not a task field — adding a new initiative means adding one row to that lookup table, never touching every task file it owns.
