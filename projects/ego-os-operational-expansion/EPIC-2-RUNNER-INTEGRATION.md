# Epic 2: Runner Integration

## Owner brief

Lets you see what the autonomous runner is doing — current task, which executor (Claude today, Codex once it exists), whatever real usage numbers are available — from inside Ego OS itself, without rebuilding RUNNER-CONTROL-UI or opening it to the internet. If you actually need to click Pause or Emergency Stop, you're sent to the existing local dashboard (`npm run runner-ui`) — Ego OS never issues that command itself. This keeps a genuinely dangerous capability (process control) exactly where it already lives and has been reviewed, instead of quietly growing a second door into it.

**Product impact:** visibility without new attack surface. No behavior of RUNNER-CONTROL-UI changes.

## Governing documents

- `memory/decisions/ADR-0009-runner-status-integration-is-local-and-read-only.md`
- `architecture/015_RUNNER_OPERATIONS_INTEGRATION.md` (full threat model)

## Risks

- **Scope creep toward a proxy.** The most tempting shortcut — "just forward the POST through Ego OS, it's simpler" — is exactly the risk this epic's ADR forbids. RCI-05 exists specifically to catch a future accidental reintroduction of this.
- **False sense of production visibility.** Because the Ops route degrades gracefully to "not available" on the VPS, someone could mistake silence for "runner is idle" rather than "wrong machine." RCI-03's explicit docstring and UI copy mitigate this, but it's a real, recurring confusion risk worth watching after ship.
- **Field drift.** `executor`/`preferred_model`/`fallback_executor` exist before Codex does. If Codex integration stalls, these fields could rot into dead schema. RCI-02's fail-closed rule limits the damage (an unimplemented executor errors loudly) but doesn't prevent the fields from going stale in documentation.

## Dependencies

- Builds on RUNNER-CONTROL-UI (already shipped) — reuses its files/API, never modifies `automation/control_server.js`'s own logic (RCI-02's file list intentionally excludes `runner_control.js`/`control_server.js`/`web/`).
- No dependency on Epic 1, 3, or 4.

## Acceptance criteria (epic-level)

1. `git grep -n "4756"` inside `ego_os/` shows only `GET`-context references (or none), never a `POST`/`PUT`/`DELETE`.
2. `/ops/runner` requires Owner auth and never 500s on a missing/malformed runner state file.
3. A task with an unrecognized `executor` value is refused before any process spawns — proven by an integration test, not just a unit test.
4. No usage number is ever displayed without a real, cited data source.

## Execution order

`RCI-01 → RCI-02 → RCI-03 → RCI-04 → RCI-05`

## Owner gates

None of RCI-01..05 carry an `OWNER_ONLY` risk (`destructive_data`/`irreversible_migration`/`payments`/`secrets`/`external_infrastructure`/`external_publication`) — this epic only reads local files and adds an Owner-authenticated route, matching Ego OS's existing auth model exactly. No task in this epic requires `owner_approved: true` beyond the ordinary review any new route deserves before its first deploy.

## Tasks

`RCI-01.yaml` · `RCI-02.yaml` · `RCI-03.yaml` · `RCI-04.yaml` · `RCI-05.yaml` — all `status: blocked`, none executed as part of this planning session.
