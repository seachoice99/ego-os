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
