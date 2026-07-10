# Changelog

All notable changes to Ego OS are recorded here, newest first. See `IMPLEMENTATION_ROADMAP.md` for the forward-looking plan this changelog reports against.

## [Unreleased] — v0.4.0 — "Delivery Company"

### Added

- **File Intake** — an optional multipart `attachment` field on task submission (`.zip` of slide images or a `.pdf` deck), saved to `ego_os/uploads/<task_id>/` before the lifecycle runs.
- **Presentation Website Generation** — `build_presentation_site(site_name, captions, accent)`, a new tool gated on Designer's new `build_presentation_sites` permission. Extracts slide images from a task's uploaded `.zip`, or renders each page of an uploaded `.pdf` via PyMuPDF, resizes each with Pillow, generates a self-contained dark-theme scroll deck (thumbnail nav, deck counter, no build step, per `architecture/007_PRESENTATION_WEBSITE_FORMAT.md`'s fixed visual contract) and publishes it to `PRESENTATIONS_DIR`, served at `/p/<site_name>/`. One deterministic tool call, not a multi-step agent loop — no change to the existing one-tool-call-per-turn execution model. Verified with a real 20-page PDF.
- **Designer activated as a fifth specialist** — added to `EXECUTION_CAPABILITY` (`presentation_design`); `designer.yaml` bumped to v1.1.
- A new "website" artifact type rendered on the task page as a live link, alongside the existing text/document/spreadsheet types.

### Fixed

- On a QA `REVISE` cycle, a tool-using specialist's pre-revision artifacts were kept alongside the revised ones instead of being replaced, showing duplicate artifact cards for the same file. Found live while verifying Presentation Website generation; also affects Document/Spreadsheet Generation revisions.

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
