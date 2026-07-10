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
