# Windows Runner Agent -- End-to-End Verification

Status: **WINDOWS_AGENT_VERIFIED**

This document is the evidence trail for one specific claim: the Windows
Runner Agent architecture (VPS coordinates, the Owner's Windows machine
executes) actually works, not just on paper but as a task that ran through
it. Task `AGENT-VERIFY` is that proof -- see "Live proof" below.

## 1. The VPS (`automation/control_server.js`) only coordinates -- it never runs Claude

Claude Code was confirmed unable to run on the production VPS. That path was
abandoned; `control_server.js` does not execute any task itself. It exposes a
small `/api/agent/*` surface so a remote machine can claim and report on work
instead:

- `POST /api/agent/register` -- a new agent obtains (or re-confirms) its `agent_id`.
- `POST /api/agent/heartbeat` -- liveness/status ping while idle or running.
- `POST /api/agent/claim` -- atomically claims the next `ready` task from the queue.
- `POST /api/agent/report-state` -- reports lifecycle events (e.g. `task_claimed`).
- `POST /api/agent/report-checkpoint` -- reports progress within a running task.
- `POST /api/agent/report-result` -- reports the final outcome (`done`/`failed`/`blocked`).
- `POST /api/agent/request-deploy` -- asks the VPS side to perform the deploy step for
  a task whose `release` is not `no_deploy` (the agent itself never touches
  production directly).

Every one of these routes is authenticated by its own **machine token**
(`Authorization: Bearer <token>`, generated with `crypto.randomBytes(32)`,
stored at `EGO_OS_AGENT_TOKEN_FILE`, mode `0600`, compared with
`crypto.timingSafeEqual`, and never logged in full -- only its last four
characters). This is deliberately a separate credential from **Owner Basic
Auth** (`OWNER_USERNAME`/`OWNER_PASSWORD`), which authenticates the human
Owner in a browser, not a machine polling in a loop. Mixing the two would let
a compromised agent token impersonate the Owner (or vice versa); keeping them
separate means either can be rotated or revoked independently.

## 2. The Windows Agent (`automation/windows_agent.js`) executes locally

The agent runs as a **Task Scheduler background task** on the Owner's own
Windows machine, under the Owner's own already-authenticated Claude Code CLI
session -- it never accepts an inbound connection and never opens a local
port. Its only network activity is outbound HTTPS `POST`s to
`EGO_OS_AGENT_SERVER_URL` (defaults to `https://os.fiveseven.ru`), each
carrying the `Bearer` machine token described above and a strictly
increasing `seq` counter (seeded from the wall clock) so the server can
reject replayed requests.

Two loops run concurrently:

- `heartbeatLoop()` -- periodic `heartbeat` calls reporting the agent's
  current status.
- `claimLoop()` -- polls `claim` on an interval; when a task is handed back,
  it runs `claude_task_runner.js`'s own `execute()` **unmodified** -- every
  stage/commit/push/pause/emergency-stop/fatal-classification rule that
  already exists for the local queue keeps working exactly as before. The
  Windows Agent adds no new task-execution logic of its own; it only sources
  the task from the VPS instead of a local queue directory, and reports back
  over HTTPS in addition to the local task YAML.

Any `pause`, `stop_after_stage`, or `emergency_stop` command issued from the
control dashboard is mirrored by the agent (`mirrorPendingCommand()`) into
the **exact same local `commands.json` file** that
`claude_task_runner.js`'s `execute()`/`runClaude()` already poll on their
own. No parallel command channel or duplicate state machine was introduced --
the existing fail-closed pause/stop/emergency-stop semantics documented in
`automation/README.md` apply unchanged, regardless of whether the command
originated from a local operator or a remote VPS poll.

## 3. Live proof: this task's own execution

Task `AGENT-VERIFY` (`tasks/queue/AGENT-VERIFY.yaml`) was claimed by a
Windows Runner Agent instance (`agent_id: 77379baa-6f06-48ec-80ab-83279f7d09df`,
claimed at `2026-07-12T15:47:53.362Z`) over this exact `/api/agent/claim`
flow, and is being executed by Claude Code running locally on the Owner's
Windows machine -- the file you are reading right now, and the commit that
carries it, are that proof. If this document exists in the repository with
this marker present, and the accompanying commit was pushed to
`origin/main`, the full loop (VPS coordination -> outbound HTTPS claim ->
local execution -> local git commit/push) has been exercised end to end.

## Scope of this task

Per the `AGENT-VERIFY` task definition, this is a documentation-only change:
only this file and the task's own YAML (`tasks/queue/AGENT-VERIFY.yaml`) are
touched. No file under `ego_os/`, `tests/`, or any other file under
`automation/` is modified. `release` is `no_deploy` -- no deploy is
attempted and production `/opt/ego-os` is never touched by this task.

**Marker:** WINDOWS_AGENT_VERIFIED
