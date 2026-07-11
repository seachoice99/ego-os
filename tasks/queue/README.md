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

Risks `destructive_data`, `irreversible_migration`, `payments`, `secrets`, and `external_infrastructure` require `owner_approved: true`. The prompt is trusted execution input: never copy unreviewed community prompts into this queue.
