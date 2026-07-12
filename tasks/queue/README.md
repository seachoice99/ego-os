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
