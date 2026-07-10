# Autonomous task queue

Each executable task is one `.yaml` file containing JSON syntax (JSON is valid YAML). This keeps the first runner dependency-free. The runner selects the highest-priority `ready` task and never runs two tasks at once.

```text
ready → in_progress → testing → deploying → done
                                  ↘ failed
ready → blocked
```

Priority order is P0, P1, P2, P3. Dependencies must be resolved before a task is marked `ready`; the first version intentionally does not infer dependency completion.

`release: automatic` authorizes commit, push to `main`, deploy, and health check. `release: no_deploy` forbids deploy.

Risks `destructive_data`, `irreversible_migration`, `payments`, `secrets`, and `external_infrastructure` require `owner_approved: true`. The prompt is trusted execution input: never copy unreviewed community prompts into this queue.
