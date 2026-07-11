# Runner Final-Sync Protocol History

## What happened with RUNNER-001

RUNNER-001 was the first end-to-end validation of the autonomous runner pipeline: create a file, run tests, commit, push, deploy, and health-check production. The implementation commit was deployed and verified correctly (service active, 401/200 checks passed). But the task's own closing step — a metadata-only commit updating `tasks/queue/RUNNER-001.yaml` to `status: done` with the recorded evidence — was made and pushed to `origin/main` *after* the deployment step, and was never itself deployed. The result: `origin/main` moved one commit ahead of what was actually running in production, even though the task file claimed full success. Nothing detected this drift, because the runner's success criteria only checked that the implementation commit had been deployed, not that the repository's final HEAD matched production's HEAD.

## How `automation/release_sync.js` fixes it

`planFinalSync` and `verifyFinalSyncEvidence` turn "deploy the final metadata commit too" from an easily-skipped manual step into a checked protocol. Before the final metadata commit is reconciled onto production, the plan function verifies that production's current HEAD still equals the deployed implementation commit and that the local HEAD still equals `origin/main` — if either has drifted out of band, or if a commit belonging to another task has landed in between, it returns `stop_diverged` and the task must stop rather than force a sync. When the change set between the implementation commit and the candidate final HEAD is exclusively release-metadata (the task's own queue YAML, nothing under `ego_os/`, no dependency or migration files), `classifyChangedPaths` allows a fast-forward-only `git pull --ff-only` on production with **no service restart**, since no application code changed. Any application-code, dependency, or migration path in that diff instead forces the normal restart-and-health-check deploy cycle. After the sync attempt, `verifyFinalSyncEvidence` requires `result.final_sync` to record identical `local_head`, `origin_head`, and `production_head` values before a task is allowed to claim `status: done` — so a task can no longer self-report success while production silently lags behind origin.

## Validation via RUNNER-002

This task (RUNNER-002) exists to exercise that fixed protocol for real: deploy an implementation commit with a normal restart cycle, then push a second, separate metadata-only commit containing only this task's own YAML update, and reconcile it onto production via a fast-forward-only pull with no restart. If the recorded `result.final_sync` heads all match, the fix is confirmed working end to end.

RUNNER_PROTOCOL_FIX_VALIDATED
