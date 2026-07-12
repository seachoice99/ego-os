# Changelog

All notable changes to Ego OS are recorded here, newest first. See `IMPLEMENTATION_ROADMAP.md` for the forward-looking plan this changelog reports against.

## [Unreleased] — Local runner control panel (RUNNER-CONTROL-UI)

### Added

- **`automation/runner_control.js`** — pure logic for the runner-level state machine (`stopped/starting/idle/running/pause_requested/paused/stop_requested/waiting_for_limit/waiting_for_owner/authentication_required/failed/completed`, distinct from any one task's own status), command validity rules (`commandAllowedInState`), append-only event-entry construction, task-action rules (`taskActionAllowed`: hold/unhold/skip/retry each valid only from specific statuses), queue-reorder validation (`validateReorder`: only `ready` tasks, never ahead of an undone `depends_on`), a minimal queue-table shape (`summarizeTask`, never leaks the full prompt), and log-content secret masking (`maskSecrets`).
- **Fail-closed fatal-pattern classification** (`session_manager.classifyFatalOutput`, wired into `classifySessionOutcome`/`decideNextAction` with top priority, before rate-limit detection and unconditionally before `"done"`): fixes a real, reported defect where a child Claude process printed *"Your organization has disabled Claude subscription access..."* and still exited `0` having already self-reported `status: "done"`. Authentication/subscription failures now move a task to `waiting_for_auth` — unlike `waiting_for_limit`, never auto-retried (no timer resolves an auth failure); other recognized fatal categories (`permission_denied`, `model_unavailable`, `network_failure`) still unconditionally block `"done"`.
- **Pause/resume/stop-after-stage/emergency-stop, wired into `claude_task_runner.js`** via a file-based control protocol (`%LOCALAPPDATA%\EgoOS\claude-runner\control\`): pause/stop-after-stage are honored only at genuine safe points (between tasks, between stages — never mid-`runClaude()`), parking a task at `"checkpointing"` (resumes exactly like `waiting_for_limit`); emergency-stop is the one command polled *during* a live session and does tree-kill it, marking the task `"interrupted"` with `result.requires_recovery_check: true` — never deletes files, never resets/checks out Git.
- **`automation/control_server.js`** — a dependency-free HTTP server (Node's built-in `http`), bound to `127.0.0.1` exclusively (plus a defense-in-depth remote-address check), reusing the engine's own task-loading/process-management/state logic rather than duplicating it. Routes for status/tasks/events/logs (secret-masked, tail-limited) and for issuing runner/task commands; task ids and log paths validated against traversal, request bodies capped at 64KB with a real `413` (not a raw connection reset), dangerous actions require `{confirm: true}`, exactly one control server per workspace via its own lock file.
- **`automation/web/`** — a plain HTML/CSS/JS dashboard (no framework): dark theme, Russian UI, color-coded status pills, polling-based auto-refresh (no page reload), an offline banner that never shows stale data as current, and a confirmation modal for dangerous actions.
- **`npm run runner-ui`** (new root `package.json`, zero dependencies) launches the control server; `npm run runner` launches the engine directly, matching the existing `node automation/claude_task_runner.js --watch` invocation.
- **New task statuses**: `checkpointing`, `waiting_for_auth`, `interrupted`, `held`, `skipped` — none reachable from an ordinary `ready → in_progress → done` run without an explicit human action (via the dashboard) or a real fatal condition.

### Verified

- 51 new Node tests (108 total, up from 57): `runner_control.test.js` (28, pure logic — state transitions, command gating, reorder/action validation, secret masking), `control_server.test.js` (13, a real HTTP server on an ephemeral port with real `fetch()` requests — loopback-only binding, path traversal rejected on task ids and log filenames, a real `413` on an oversized body, confirmation enforced on dangerous actions, reorder actually changes `nextTask()`'s pick, a second `start()` refused while the first holds the lock), plus new `claude_task_runner.test.js` cases proving a pause command written mid-session does not interrupt the running stage (it still ends via its own timeout) while an emergency-stop command does interrupt it immediately with no orphaned process, and the exact live auth-failure-with-exit-0 defect no longer produces `"done"`.
- Manually verified live against the real repository (not just the isolated test fixture): `npm run runner-ui` started for real, `netstat` confirmed listening on `127.0.0.1` only, `GET /api/tasks` correctly reflected the real queue (`DA-03/04/05` ready, `TOKEN-EFFICIENCY-VERIFY` `waiting_for_limit`), dashboard HTML/CSS/JS served with correct content types, a real path-traversal probe returned `404`. No task file was modified during this read-only verification (`git status` clean afterward). A force-killed control server correctly left a stale lock file (`Stop-Process -Force` bypasses Node's signal handlers) which the next `start()` correctly detects as dead and reclaims — an expected, already-handled class of issue, matching the runner engine's own lock file behavior.

## [Unreleased] — Autonomous task runner: token/usage-limit-efficient staged execution (TOKEN-EFFICIENCY-001)

### Added

- **`automation/session_manager.js`** — pure decision logic for staged execution, extending the `release_sync.js` pattern: `decideNextAction()` is the single, fully-tested function the runner's stage loop dispatches through (done / blocked / continue to a fresh stage / wait for a rate limit / fail); `validateHandoff()` enforces a fixed 7-field shape and a 1500-word cap; `detectRateLimit()` recognizes the CLI's own structured `rate_limit_event` (a `status` other than `"allowed"`) plus plain-text fallback phrases as a legitimate, expected pause, never a code defect; `planStages()` turns an optional `checkpoints` YAML field into an explicit stage plan; `claudeInvocationArgs()` centralizes the exact, fixed argv passed to `claude` (never `--continue`/`--resume`, unit-tested to prove it).
- **Staged execution in `claude_task_runner.js`** — a large task is no longer one unbounded session. Explicit `checkpoints` (if declared) fix the stage plan; otherwise the runner adapts at runtime, only splitting into a fresh session if a stage actually exhausts its `max_duration_minutes` (default: the CLI's `--timeout-minutes`), up to `max_auto_stages` (default 4) before failing rather than looping forever. `context_strategy: "single"` opts a task out entirely, reproducing the exact pre-existing single-session behavior. Every stage is a brand-new `claude -p` process; the next stage's prompt carries forward only the task's own YAML, current Git state, and the previous stage's handoff file (written to `%LOCALAPPDATA%\EgoOS\claude-runner\handoffs\<task_id>.json`, outside Git) — never the prior conversation or a full diff. New optional `model` field passes through as `--model <id>`; `token_budget` is recorded/logged, not causally enforced (no reliable native mechanism to meter a running session's usage from outside it exists).
- **`waiting_for_limit` task status** — a real Claude usage/rate limit (detected structurally, not guessed) parks the task with a `result.retry_after` timestamp instead of failing it; `nextTask()` will not pick it back up before that time, and no paid usage-credit workaround is enabled.
- **Observability**: every stage appends to `result.sessions[]` — model, duration, prompt size (chars + approximate tokens, also logged to the console at stage start), handoff size, outcome, and its log path. No secrets ever included.
- **A real Windows process-management fix, found while testing this feature**: `spawnSync`'s own built-in `timeout` kills the *direct* child (`cmd.exe`) the instant it fires -- by the time the runner's own cleanup code got control back, that PID was already gone, so a genuine timeout could still orphan the underlying `claude.exe` (a variant of the original DA-01 orphan defect, via a different race). `runClaude()` now uses async `cp.spawn` with its own `setTimeout`, so the kill happens on a still-live process tree. Separately, `taskkill /F /T /PID X` itself proved to be an unreliable heuristic beyond a shallow tree (it killed `cmd.exe` but left grandchildren running) -- replaced with `killProcessTree()`, which walks the real process tree via WMI (`Get-CimInstance Win32_Process`) and kills every descendant explicitly.
- 56 total Node tests (`node --test`, up from 14): `session_manager.test.js` (35, pure logic) and `claude_task_runner.test.js` (11, integration-style against a real-but-fake mock `claude` executable — `automation/test_fixtures/fake_claude.js` — never a real Claude Code process), including a global sweep proving zero fake sessions or their descendants survive the whole test run.

### Compatibility

Every existing task YAML (`SR-*`, `RUNNER-*`, `DA-*`) requires no new field and runs exactly as before when it completes within its original timeout; a task that times out now gets a handoff-based continuation instead of an immediate hard failure, which is strictly an improvement, not a behavior change task authors need to account for.

## [Unreleased] — Owner Asset Inbox: list, detail, accept, reject (DA-02)

### Added

- **`GET /assets`** (`ego_os/templates/assets.html`) — read-only list of every Digital Asset, grouped into Candidates awaiting decision, Accepted, Internally Validated, and Rejected/Archived (visually separated). Each row shows title, type, resolved project name, a link to the source Task, status, created date, and a value-thesis excerpt.
- **`GET /assets/{id}`** (`ego_os/templates/asset_detail.html`) — detail page rendering the Asset's full provenance (source Task link, source Report reference, artifact links through the *existing* `/tasks/{task_id}/artifacts/{filename}` route — no new download path, no file copy), employee versions, skills used, value thesis, monetization thesis (structured fields per `architecture/013_DIGITAL_ASSET_MODEL.md` Section 9, or "not yet validated"), and the full append-only `digital_asset_events` history. Unknown id → 404.
- **`POST /assets/{id}/accept` / `POST /assets/{id}/reject`** — the only mechanism for an Owner decision on a Candidate, calling DA-01's `store.transition_asset(..., actor="owner")` with no bypass and no provenance edit. A transition the lifecycle map disallows (already `accepted`, already `internally_validated`, or a repeated/double-submitted accept) raises `store.DigitalAssetError`, reported here as a clear `400` — never a raw `500`, never a silent duplicate event. Rejecting never deletes the Asset (ADR-0007 decision 7); accepting a previously-rejected Candidate succeeds only as a fresh, distinct `owner_accepted` event, per DA-01's own transition rules. Neither route performs any external action — pure DB state change plus a redirect.
- **Asset Inbox navigation link** on the Command page (`command.html`, decisions surface) near the pending-proposals section, plus a lighter link on the Dashboard (`dashboard.html`, observation surface) — the existing Command/Dashboard split is unchanged.
- All Asset-derived fields render through Jinja2's default autoescaping (no `| safe` anywhere), matching SR-04's `skill_detail.html` precedent.

### Verified

- 17 new tests (`tests/test_asset_inbox.py`, 147 total with the existing suite): Owner-auth-required (401) and CSRF-required (403) on the new routes, list/detail rendering against a real Candidate created via `store.create_asset_candidate`, list grouping by status, unknown-id 404, accept/reject logging the correct owner-actor event, accepting an already-accepted or already-`internally_validated` Asset returning a clear `400` without a duplicate event, double-submitting accept producing exactly one `owner_accepted` event, accepting a rejected Candidate as a fresh distinct decision (the original rejection event untouched), provenance left unchanged by accept, HTML-in-title/summary/evidence escaped not executed, provenance artifact links resolving through the existing download route with no new path, and all pre-existing routes (`/`, `/dashboard`, `/skills`, `/employees/{id}`) unaffected.

## [Unreleased] — Digital Asset domain model: additive persistence, provenance, append-only events (DA-01)

### Added

- **`digital_assets` / `digital_asset_events` tables** (`ego_os/store.py`) — new, additive `CREATE TABLE IF NOT EXISTS` blocks (exactly like `skill_audit_events`); no existing `tasks`/`reports`/`memory`/`execution_events`/`employees`/`skill_audit_events` schema changed. A Digital Asset Candidate and an Accepted Digital Asset are the same `digital_assets` row at different points in one lifecycle (ADR-0007 decision 1) — `status` is a derived convenience field; `digital_asset_events` is the append-only source of truth for every transition, matching `architecture/013_DIGITAL_ASSET_MODEL.md`.
- **`store.create_asset_candidate` / `get_asset` / `get_assets` / `get_asset_by_source_task` / `get_asset_events` / `log_asset_event` / `transition_asset`** — `transition_asset` is the single enforcement point for every status change, validated against an explicit allowed-transition map before writing anything: `candidate → accepted|rejected` and `rejected → accepted` require actor `owner`; `accepted → internally_validated` requires a `validation_status='passed'` and a non-empty `monetization_thesis` recorded in the same call; `candidate → internally_validated` directly is rejected; `any status → archived` is implemented for model completeness (architecture/013 Section 6) restricted to `system`/`owner` actors. No function deletes a `digital_assets` or `digital_asset_events` row (ADR-0007 decision 7); provenance is written once at Candidate creation and never mutated afterward.
- **`tools.verify_artifact_reference(task_id, filename)`** — validates a generated artifact actually exists at its safe, task-scoped path (the same path-traversal-safety pattern as `main.py`'s `download_artifact` route) before it can be referenced in a Digital Asset's `provenance`; never copies the file, rejects a traversal attempt or a missing file.

### Verified

- 25 new tests (`tests/test_digital_assets.py`, 130 total with the existing suite): additive migration against an old DB copy, idempotent re-init, Candidate creation logging exactly one `candidate_created` event, every disallowed transition (direct `candidate → internally_validated`, `accepted → internally_validated` missing `validation_status` or `monetization_thesis`, an unmapped transition), `rejected → accepted` only via a new distinct `owner_accepted` event (the original `owner_rejected` event untouched), actor restrictions on Owner-decision and archive events, event_type/validation_status consistency, provenance immutability, missing source Task/Project rejection, an old-shaped Report still reading correctly, append-only event growth, no hard-delete code path, and artifact-reference path-traversal rejection. Persistence only — no HTTP route (DA-02), no `lifecycle.py`/`worker.py` change (DA-03).

## [Unreleased] — Autonomous task runner: fix production drift after a task's final metadata commit

### Fixed

- **Production could silently end up one commit behind `origin/main`.** An `automatic`-release task deploys its implementation commit, then records deploy/health-check evidence and pushes that as a *separate* final metadata commit -- which was never itself deployed. Found live after `RUNNER-001`. Manually reconciled production to `origin/main` this time (fast-forward only, no restart, since the only diff was `tasks/queue/RUNNER-001.yaml`); `RUNNER-001`'s own history was not rewritten.

### Added

- **`automation/release_sync.js`** -- pure decision logic (no I/O) for the runner's final-sync protocol: `planFinalSync()` decides whether a task's final metadata commit can be fast-forwarded onto production without a restart (only if the diff is exclusively the task's own YAML / permitted release metadata), requires the normal restart/health-check cycle if application code, `requirements*`, templates, static, config, or a migration changed, and stops the task (`failed`/`blocked`, never a silent skip) if production or origin diverged out of band, or a non-task-prefixed commit is interleaved. `verifyFinalSyncEvidence()` is a hard runner-side guard: an `automatic`-release task can no longer end `status: "done"` unless its own recorded `result.final_sync` proves local/origin/production HEAD actually converged -- not just trusted from Claude's self-report.
- The runner's generated prompt (`makePrompt` in `claude_task_runner.js`) now spells out this exact reconciliation procedure as rules 9-10 for every future `automatic`-release task.
- 14 unit tests (`automation/release_sync.test.js`, run via `node --test`): metadata-only diff fast-forwards without restart; application-code/`requirements*`/template/migration diffs require a restart; production or origin divergence stops the task; a foreign interleaved commit stops the task; final-head equality is checked; a task cannot claim `done` with missing or mismatched `result.final_sync` evidence.

## [Unreleased] — Skills audit trail: fix read-triggered "validated" events

### Fixed

- **`GET /skills` no longer logs a `validated` audit event on every page view.** A read-only UI was mutating the audit trail just by being looked at — viewing the page any number of times now appends nothing. `GET /skills/{id}/{version}` was already read-only in this respect and is now covered by a test proving it.
- **`validated` is now logged only on genuine operational validation**: when `ego_os/lifecycle.py` actually resolves an Employee's Skill reference for a real task (loads the manifest, checks its digest) — once per skill per task, reused (not re-logged) across a QA revision.
- **`store.get_last_skill_check()`** now considers only `validated` events, so "last check" on the Skills UI reflects the last real validation, not an attach/detach/resolution_failure event or a page view.
- No existing production audit rows were deleted or rewritten; this only changes what triggers a *new* row going forward.
- 2 new tests (list/detail page viewed twice appends nothing) and 1 new test (a real task resolution logs exactly one `validated` event, and `get_last_skill_check` reflects it); 1 existing test updated to generate real audit events instead of relying on the removed page-view logging.

## [Unreleased] — Skills UI and audit (SR-04)

### Added

- **`GET /skills`** — read-only list of every Skill in the Registry: id, name, version, trust state, lifecycle state, origin type, license, digest status, which Employees use it, requirements, permissions required, and last check timestamp. A malformed manifest surfaces its error inline instead of breaking the page.
- **`GET /skills/{skill_id}/{version}`** — read-only manifest detail page: status, requirements, Employees using this exact version, and the full audit trail for this Skill. A revoked Skill stays visible here (via `skills.get_manifest_for_display`, which does not fail closed) but remains unresolvable for execution — `get_exact_version`/`resolve_compatible_version` still fail closed exactly as before.
- **`skill_audit_events` table** (`ego_os/store.py`) — a new, append-only SQLite table, deliberately kept separate from the immutable Skill package on disk. Records `discovered/created/validated/attached/detached/deprecated/revoked/resolution_failure` events, each with only operational facts (skill id/version, event type, a short detail string) — never a raw prompt, credential, or hidden chain-of-thought. Viewing the list page logs a `validated` event per Skill; `employees.sync_from_registry()` now diffs each Employee's Skill references and logs `attached`/`detached` on real changes; a fail-closed Skill resolution failure (`ego_os/lifecycle.py`) logs `resolution_failure`.
- Both routes rely on the app-wide Owner Basic Auth + CSRF dependency already applied to every route — no new auth wiring needed. Jinja2's default autoescaping (no `| safe` used anywhere on manifest content) keeps manifest fields HTML-safe even if a Skill's `name`/`description` contained markup.

### Verified

- 10 new tests: list page, detail page, auth required (401 unauthenticated on both routes), HTML escaping of manifest content, unknown skill 404, revoked skill visible-but-unresolvable, audit events append on each list-page view, attach/detach events logged via `sync_from_registry`, audit trail never contains the Owner password, Employee-usage mapping shown on both pages, and existing routes (`/`, `/dashboard`, `/employees/{id}`) unaffected.

## [Unreleased] — First internal Skill: structured_reporting (SR-03)

### Added

- **`skills/registry/structured_reporting/1.0.0/`** — the first real internal Skill: a shared report-assembly procedure (goal, actions taken, evidence, changed files/artifacts, tests/checks, risks, cost, open questions, final status), `trust: approved`, `lifecycle: active`, `origin: internal`. Contains no Persona/role text, no credentials, no specific model, no Tool implementation, no extra permissions, no production data.
- **Attached to Coder and Researcher** (both bumped to v1.1) — the first employees to reference a real Skill.
- **Skill instruction injection** (`ego_os/lifecycle.py`) — a resolved Skill's entrypoint content is now included in the specialist's prompt, positioned *after* the Persona framing ("You are the {title}... Mission: ...") and never before it, so a Skill shapes *how* work is reported without ever displacing *who* the specialist is or its own role-specific reporting rules (Coder's "list changed files"/"report tests run", Researcher's "cite sources"/"highlight uncertainty" both still apply, verified directly against real report content).

### Verified

- A real (non-mocked) local Coder task produced a report following the skill's exact 9-section structure, with real tool-read evidence and correct `skills_used` traceability.
- 7 new golden tests against the real, committed skill package (not a synthetic fixture): structure preserved for both employees, Persona ordering in the actual prompt, permissions unwidened, fail-closed on a missing skill, and old task history unaffected.

## [Unreleased] — Employee Skill references (SR-02)

### Added

- **Employee `skills` field** — an optional, backward-compatible list of `{id, version}` Skill references on Employee YAML. An Employee without it (every pre-SR-02 Employee) behaves exactly as before.
- **Fail-closed resolution before any model call** — a missing, revoked, or digest-tampered Skill reference raises before the specialist's model is ever invoked; the task fails with a clean message via the existing v0.4.1 worker error path (`run_state='failed'`, `error_message`), not a crash.
- **Skill/execution traceability** — `execution_events` gains `skill_id`/`skill_version`/`skill_digest`; `reports` gains `skills_used` (the exact skills actually used, id+version+digest). A historical report keeps its original Skill version even after the Employee is later re-pointed at a newer one.
- **No permission widening** — a Skill's declared `requirements.permissions` never appears in the Employee's own granted permissions; effective authority is still exactly the Employee's own `permissions` field.

### Changed

- Additive, idempotent DB migration: `employees.skills`, `execution_events.skill_id`/`skill_version`/`skill_digest`, `reports.skills_used` — all new columns, all backfilled safely for pre-existing rows.

10 new tests (85 total): employee without skills, employee YAML `skills` field loaded via `sync_from_registry`, a real task resolving and tracing a valid skill, two employees sharing one skill, missing/revoked/tampered skill all blocking before the model call, permissions not widened, historical report version preserved after a newer Skill version is registered, and the schema migration itself against a throwaway pre-SR-02 database copy.

## [Unreleased] — Skills Registry (SR-01)

### Added

- **Skill Registry foundation** (`ego_os/skills.py`, `skills/registry/`) — filesystem-based, no new database, no new runtime dependency. Reads and validates Skill manifests per `architecture/011_SKILL_MANIFEST_SPECIFICATION.md`: required-field presence, lower_snake_case id, Semantic Version (`MAJOR.MINOR.PATCH`, a small hand-rolled subset rather than a third-party semver library), `trust.state`/`lifecycle.state` enum validation, entrypoint path-traversal/absolute-path rejection, and a real SHA-256 digest check against the entrypoint file's actual content (not just field presence). Deterministic listing, exact-version lookup, and compatible-version-range resolution (`>=`/`<=`/`==`/`>`/`<`, comma-separated). Fails closed (a clean, typed error — never a stack trace) for any revoked version, even one an exact lookup would otherwise resolve. The Registry only reads and validates — it never executes Skill content and never grants a permission; Skill `requirements` remain requirements, not grants.
- 32 new tests (75 total with the existing v0.4.1 suite): valid manifest, malformed YAML, missing field, invalid id, invalid version, digest mismatch (both a bad-format field and a real content/digest mismatch), path traversal, missing entrypoint file, duplicate id+version across the tree, a manifest whose identity disagrees with its own storage location, revoked-skill fail-closed (exact and range lookup), deterministic listing, listing surviving one bad manifest without breaking the rest, exact/compatible/incompatible version resolution.

## [Unreleased] — v0.4.1 — "Trustworthy Delivery Company"

### Added

- **Owner access control** — every route requires HTTP Basic Auth (`OWNER_USERNAME`/`OWNER_PASSWORD`, fails closed if unconfigured), applied as a global FastAPI dependency (`ego_os/auth.py`). Published presentation sites under `/p/` are served directly by nginx, outside this app, and stay public on purpose.
- **CSRF-equivalent protection** — an Origin/Referer host check on every state-changing request, chosen over a session/token scheme since Basic Auth has no session to carry a synchronizer token in.
- **Safe file intake** — upload validation (extension allowlist + real magic-byte signature check + a streamed size cap, `MAX_UPLOAD_BYTES`) now happens *before* a task row is created, staged into a temp directory first, so a rejected upload leaves no orphaned task.
- **ZIP/PDF hardening** — entry-count cap (`_MAX_ZIP_ENTRIES`) and a running-total-uncompressed-size cap (`_MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES`, checked while streaming bytes out of the archive, never trusting its declared size) against zip bombs; explicit rejection of any traversal/absolute-path zip entry; a PDF page-count cap (`_MAX_PDF_PAGES`); corrupted zip/PDF handled as a clean `ToolError` instead of crashing; any failure cleans up only this tool's own scratch directories.
- **Background worker** (`ego_os/worker.py`) — an in-process `queue.Queue` + one thread, started at app startup. `POST /tasks` now only validates and enqueues; the Task Lifecycle itself runs on the worker instead of blocking the HTTP request.
- **Task run states** — a new `tasks.run_state` column (`queued`/`running`/`completed`/`failed`/`cancelled`), kept separate from the existing fine-grained `status` column. `tasks.error_message` surfaces a worker failure to the Owner on the task page instead of losing it.
- **Startup crash recovery** — a task left `running` from before a restart is marked `failed` with a clear reason; a task still `queued` (never actually started) is safely requeued.
- **Execution events** (`execution_events` table, `store.log_execution_event`/`get_execution_events`) — written incrementally as the lifecycle proceeds, unlike `reports.timeline` (unchanged, still written once at the end for backward-compatible rendering). Each event: step, employee id/version, capability, model, tool name, a JSON-safe tool-args summary, tokens, cost, status, duration, timestamp.
- **Employee version traceability** — `reports.employee_versions` records which version of each employee actually performed the work, captured at execution time; `store.get_roster_summary` now also returns `version`. A later YAML bump no longer silently changes what an already-delivered report says performed the work.
- **Automated test suite** (`tests/`, pytest + FastAPI `TestClient`) — the project's first. Isolated temp DB/uploads/generated per test, `model_provider.complete` replaced by a scripted fake — no test calls a real API or touches the real local/production DB. Covers auth, CSRF, upload validation, zip-slip/zip-bomb/PDF-page-limit rejection with cleanup, task state transitions, worker crash recovery, idempotent processing, tool permission enforcement, QA PASS/REVISE, capability gap handling, project memory isolation, employee-version preservation, duplicate-report prevention, and the `run_state`/`employee_versions` schema migrations (against a throwaway pre-v0.4.1 database copy).
- **Backup script** (`scripts/backup.sh`) — SQLite's own `.backup` plus a tarball of generated artifacts, with retention; proposed as a systemd timer in `DEPLOYMENT.md`, not yet installed on production.

### Changed

- `README.md`/`CLAUDE.md` no longer describe this as a specification-only repository; both document the real runtime, dev/test commands, and how the test suite is isolated. `DEPLOYMENT.md` documents the new runtime components (auth env vars, background worker, backup/restore) without any production server change having been made.
- Task page (`task.html`) shows a "Processing"/"Failed" state with an auto-refresh meta tag while `run_state` is `queued`/`running`, since a task no longer completes synchronously by the time the post-submit redirect lands.

### Fixed

- A zip entry's traversal path (`../../evil.png`) was silently flattened to its basename and **accepted as a legitimate slide** by the prior zip-slip guard, instead of being rejected outright — found while writing this release's own regression test.

## [v0.4.0] — "Delivery Company"

### Added

- **File Intake** — an optional multipart `attachment` field on task submission (`.zip` of slide images or a `.pdf` deck), saved to `ego_os/uploads/<task_id>/` before the lifecycle runs.
- **Presentation Website Generation** — `build_presentation_site(site_name, captions, accent)`, a new tool gated on Designer's new `build_presentation_sites` permission. Extracts slide images from a task's uploaded `.zip`, or renders each page of an uploaded `.pdf` via PyMuPDF, resizes each with Pillow, generates a self-contained dark-theme scroll deck (thumbnail nav, deck counter, no build step, per `architecture/007_PRESENTATION_WEBSITE_FORMAT.md`'s fixed visual contract) and publishes it to `PRESENTATIONS_DIR`, served at `/p/<site_name>/`. One deterministic tool call, not a multi-step agent loop — no change to the existing one-tool-call-per-turn execution model. Verified with a real 20-page PDF.
- **Designer activated as a fifth specialist** — added to `EXECUTION_CAPABILITY` (`presentation_design`); `designer.yaml` bumped to v1.1.
- A new "website" artifact type rendered on the task page as a live link, alongside the existing text/document/spreadsheet types.

### Fixed

- On a QA `REVISE` cycle, a tool-using specialist's pre-revision artifacts were kept alongside the revised ones instead of being replaced, showing duplicate artifact cards for the same file. Found live while verifying Presentation Website generation; also affects Document/Spreadsheet Generation revisions.
- The task-submission form's loading state disabled the request textarea synchronously in the `submit` handler; since a browser builds the form's entry list *after* that handler runs, the disabled field's value was silently dropped, so `request_text` never reached the server on a real browser submission (curl-based testing never exercised the page's JS, so this went unnoticed through v0.1-v0.4 until reported live). Fixed by using `readOnly` instead of `disabled`.
- Dropping a file directly onto the request textarea (a natural expectation) did nothing, since a plain `<textarea>` has no file-drop handling — the file silently went nowhere while looking, to the Owner, like it had been attached. Added real drag-and-drop support that routes a dropped file into the actual file input.
- nginx's default `client_max_body_size` (1MB) silently rejected any realistically-sized presentation deck with a 413 before it ever reached the app -- reproduced live with a 47.8MB test PDF. Raised to 100m on the `os.fiveseven.ru` site.
- nginx's default `proxy_read_timeout`/`proxy_send_timeout` (60s) killed the client connection on a heavy deck (many pages, PDF rendering, multiple LLM calls) before the app finished -- the task still completed and delivered server-side past 60s, but the Owner's browser just saw a dead request. Reproduced live (task completed at ~96s after the connection had already dropped). Raised both to 300s.
- A specialist with `build_presentation_sites` had no way to know whether a file was actually attached to its task and sometimes guessed wrong, telling the Owner to attach a PDF without ever attempting the tool even when a real file was present. Fixed by stating the actual fact (attached or not, and the filename) directly in the specialist's prompt instead of leaving it to guess from the request's wording.
- A generic request without an explicit "As Designer..." framing (e.g. "сделай сайт из этого pdf") triggered Capability Gap Handling instead of matching the already-capable Designer -- reproduced live, drafted a redundant "PDF-to-Web Conversion Specialist" proposal. `designer.yaml`'s mission/capabilities weren't concrete enough for the Orchestrator's staffing model to reliably connect a plain "PDF/website" request to Designer. Made the roster line explicit (mentions PDF/zip and "no other role can do this" directly, added a `pdf_to_website_conversion` capability); re-verified against 8 phrasings including the exact one that failed, all matched Designer.

### Added (generated presentation site template)

- **PDF link recovery** — a source `.pdf`'s real link annotations are recovered per page (exact URL and position, derived from the PDF's own rects) and restored as clickable hotspots on the corresponding slide, positioned as a percentage of the page so they survive any resize.
- **Video pop-up** — a recovered link to a known video host (YouTube, VK) opens in a shared in-page modal instead of navigating away from the deck, per `architecture/007`'s video contract; any other link opens in a new tab like a normal link.

### Changed (generated presentation site template)

- The thumbnail nav rail had no real up/down paging -- only click-a-thumbnail or scroll. Added actual `Prev`/`Next` buttons plus keyboard support (arrow keys, Page Up/Down, Space).
- The thumbnail rail was a fixed narrow 110px regardless of screen size or slide count, leaving a large empty gap below a short deck. Now a responsive `clamp(140px, 15vw, 220px)` width with thumbnails evenly distributed to fill the available height.
- Slide numbers on each thumbnail were a small, low-contrast bottom-right badge, easy to miss. Now a larger, high-contrast badge in the top-left corner, highlighted in the deck's accent color on the active slide.

## [v0.3.0] — "Operational Company" (untagged)

All four planned v0.3 capabilities shipped, verified end to end.

### Added

- **Recorded Mandate** — a versioned `mandate` table plus a Command-page form; submitting mission + starting capital + risk policy together is the Owner's Stage 1 Formation approval. Each submission is a new version, never an overwrite.
- **Capability Gap Handling** — Orchestrator's staffing prompt can now reply `NO_MATCH: <reason>` instead of being forced into an existing specialist. A genuine gap drafts a full Employee Creation Proposal (matching `tasks/templates/EMPLOYEE_CREATION.md`), records it with `pending` status, and pauses the task at `awaiting_approval` instead of silently defaulting. New Command-page Approve/Reject actions resolve the task to `gap_approved`/`gap_rejected`. Automatic employee provisioning itself remains deferred.
- **Operations Visibility** — `GET /employees/{id}` (mission, capabilities, permissions, full task history) and `GET /projects/{id}/memory` (full memory browsing, not just the 5 most recent entries silently injected into a prompt).
- **Command/Dashboard Split** — `GET /` is now the Strategy/Command Interface (mandate, projects, pending proposals, task submission); `GET /dashboard` is the observe-only Operations Dashboard (roster, tasks, cost). `home.html` retired in favor of `command.html` + `dashboard.html`.

### Changed

- `store.get_total_cost()` now also sums cost recorded against capability-gap proposals, not just completed-task reports, so total spend stays accurate even when a task doesn't finish the full lifecycle.

## [v0.2.0] — 2026-07-08 — "Useful Company"

All seven planned v0.2 capabilities shipped, verified end to end (locally and in production), and deployed.

### Added — capabilities

- **Tool Framework** (`ego_os/tools.py`) — the general mechanism by which an employee is granted a specific external capability without ever holding a credential directly: a name-checked tool registry gated on each employee's existing `permissions`. Prerequisite for everything below.
- **Repository Access** — `read_repository_file` / `write_repository_file`, gated on Coder's `read_repository`/`write_repository` permissions, scoped to the repo root with path-traversal and `.env`/`.git` denial.
- **Web Research** — `web_search` via the Tavily API, gated on Researcher's `use_web` permission.
- **Document Generation** — `create_document`, gated on Writer's `create_documents` permission. Produces real `.md`, `.docx` (`python-docx`), and `.pdf` (`fpdf2`) files.
- **Spreadsheet Generation / Editing** — `create_spreadsheet`, gated on CFO's `create_finance_reports` permission (CFO wired into staffing as a fourth specialist). Produces real `.xlsx` files (`openpyxl`) with a bold header row and auto-sized columns.
- **Structured Artifacts** — every artifact (the main text result and any generated file) now carries an explicit `type` (`text`/`document`/`spreadsheet`) and renders through one unified path in `task.html`, instead of a special-cased "Result" section plus a separate ad hoc file list.
- **Multi-Project Operations** — real Project creation (name + optional vision) and a project selector on task submission; tasks and reports show which project they belong to.

### Added — infrastructure

- First production deployment: Ubuntu 24.04 VPS, dedicated `egoos` system user, systemd unit, nginx + Let's Encrypt (`os.fiveseven.ru`), documented in `DEPLOYMENT.md`.
- Submit-button loading state (disabled button, spinner, top progress bar) and professional Markdown-to-HTML rendering for task results (tables, headings, code blocks, blockquotes) — shipped just before the v0.2 capability work began.

### Fixed

- Specialists and QA had no notion of the real current date, causing misjudgment of live web-search results as "future" — every prompt now states today's date.
- `fpdf2`'s `multi_cell` defaulted to leaving the cursor at the right margin between calls, crashing any second heading/paragraph in a generated PDF — fixed by passing `new_x="LMARGIN", new_y="NEXT"`.
- The PDF core font can't render em-dashes, curly quotes, or bullet characters that LLM output routinely contains — added a Latin-1 sanitization step.
- `TOOL_REQUEST` parsing required the entire remainder of a single line to be exactly one JSON value; a reply with a multi-line "content" argument or trailing text after the JSON broke it with "Extra data", silently failing the tool call while QA passed the result anyway. Replaced with a regex-located marker + `json.JSONDecoder().raw_decode()`, found and fixed during live production verification.

### Changed

- `store.get_tasks()` / `get_task()` now join in the project name.
- A tool's registry entry can declare `needs_context` (e.g. `task_id`) so the lifecycle can supply values an LLM's `TOOL_REQUEST` can't reasonably know itself, and `produces_artifact` now carries the artifact's type rather than a bare boolean.

## [v0.1.0] — "Working Company"

- Full documented Task Lifecycle (Intake → Planning → Staffing → Execution → QA → Delivery → Memory Update) running against a real model provider (OpenRouter) behind a capability-based `model_provider` boundary.
- Real staffing: Orchestrator genuinely chooses between Writer and Researcher by required capability.
- QA as a real gate: one corrected revision attempt on `REVISE`.
- Projects and cross-task memory reuse within a project.
- Every task produces a Report with token/cost accounting.
- Company (all registered employees) exists with `idle` status before any task is submitted.
