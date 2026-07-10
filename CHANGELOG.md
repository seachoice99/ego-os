# Changelog

All notable changes to Ego OS are recorded here, newest first. See `IMPLEMENTATION_ROADMAP.md` for the forward-looking plan this changelog reports against.

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
