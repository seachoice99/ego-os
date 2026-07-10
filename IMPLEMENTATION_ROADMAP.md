# Ego OS — Implementation Roadmap

This is the primary implementation plan for Ego OS. It sequences work that is already specified in `architecture/`, `docs/000_VISION_2.md`, and the ADRs into build order — it does not introduce new architecture. The roadmap is organized around **what the company becomes capable of doing**, not which employees happen to implement a capability at a given time — employees are replaceable competence containers (ADR-0002) and may change; the capabilities a version unlocks are the durable milestones.

**Change control:** this document is updated *before* a change in direction, not after. If implementation surfaces something the architecture or this roadmap didn't anticipate, the response is to revise this document (and flag it for an architecture review if the finding is architectural rather than sequencing) before building the new direction — not to build ad hoc and document it retroactively.

**Status legend:** ✅ done · 🔜 next · ⏳ planned, not yet started

**Released versions:** see `CHANGELOG.md` for the full change history and `RELEASE_NOTES_v0.2.md` for v0.2's detailed capabilities/bugs/limitations/metrics.

---

## ✅ v0.1 — Working Company

**Objective:** prove the whole Task Lifecycle works end to end as a company, not a chatbot.

**Delivered:** the company (all registered employees) exists and is visible with `idle` status before any task is submitted. The Owner submits a request through a combined Command Interface/Dashboard page. Orchestrator, Writer, and QA run the full documented Task Lifecycle (Intake → Planning → Staffing → Execution → QA → Delivery → Memory Update) against one real model provider behind the capability-based `model_provider` boundary. Orchestrator genuinely chooses between specialists by required capability instead of a fixed rule. QA is a real gate — a `REVISE` verdict triggers one corrected attempt before delivery. Tasks belong to a Project; a specialist's prompt includes prior memory from the same project. Every task produces a Report with token/cost accounting and a Memory entry.

**Dependencies:** none (foundation).

---

## ✅ v0.2 — Useful Company

**Objective:** the company can take on a meaningfully wide variety of real work, not just text drafting and review.

**Capabilities added:**

- ✅ **Tool Framework** — the general mechanism by which an employee can be granted a specific external capability without ever holding its credentials directly. This turns the Boundaries principle already stated in `architecture/005` (credentials resolved at the infrastructure layer, never held by an employee) from a promise into working code, and is the prerequisite every capability below is built on. Implemented as a name-checked tool registry (`ego_os/tools.py`) gated on each employee's existing `permissions` list from its YAML definition; a specialist's single execution turn may request exactly one tool call before producing its final artifact.
- ✅ **Repository Access** — read and modify files within this repository under the Tool Framework's boundary. The first concrete tool built on top of the framework. Verified end to end: the Coder employee (the only current role with `read_repository`/`write_repository` permissions) genuinely read a real file and reported its actual contents, and separately created a new file on disk with exact requested content — both via a live task, not a simulated one. Permission enforcement and path-traversal/`.env`/`.git` denial were verified directly against the framework.
- ✅ **Web Research** — real web search/retrieval, closing the gap between `researcher.yaml`'s existing `use_web` permission and what's actually possible today (synthesis from training knowledge only). Implemented as a `web_search` tool (Tavily) added to the existing Tool Framework registry, gated on `use_web`, with no framework changes. Verified end to end: Researcher genuinely called `web_search` (visible as a `tool_use` timeline step) rather than answering from training knowledge, and cited real URLs returned by the live search. A date-awareness gap surfaced during verification (the model misjudged which real, current results were "future" because it had no notion of today's actual date) and has since been fixed: every specialist and QA prompt now states the real current date, re-verified with a corrected, accurate result.
- ✅ **Document Generation** — a task can produce a real structured document artifact, not just plain text returned inline in a report. Implemented as a `create_document` tool added to the existing Tool Framework registry, gated on Writer's existing `create_documents` permission, producing real `.md`, `.docx` (via `python-docx`), and `.pdf` (via `fpdf2`) files under `ego_os/generated/<task_id>/`, listed as downloadable artifacts on the task page (`GET /tasks/{id}/artifacts/{filename}`). The framework gained one small, justified extension: a tool can declare `needs_context` (here, `task_id`) so the lifecycle can supply values an LLM's `TOOL_REQUEST` can't reasonably know itself — no change to the existing permission-check shape. Verified end to end for all three formats with real tasks: a real `.md` file, a real Word 2007+ `.docx` (confirmed via `python-docx` readback), and a real `.pdf` (confirmed via `file` and byte inspection), each downloaded and checked for correct content. Two real bugs were found and fixed during verification: `fpdf2`'s `multi_cell` left the cursor at the right margin between calls, crashing the second heading/paragraph on every multi-line document; and the PDF core font can't render em-dashes/curly quotes/bullets that LLM output routinely produces, which has since been added as a small sanitization step.
- ✅ **Spreadsheet Generation / Editing** — a task can produce or edit tabular/structured data. This is also where cost and finance reporting becomes a real generated artifact rather than a single number on the dashboard. Implemented as a `create_spreadsheet` tool added to the existing Tool Framework registry, gated on CFO's existing `create_finance_reports` permission (CFO is now wired into staffing as a fourth specialist, alongside Writer/Researcher/Coder). Produces real `.xlsx` files (via `openpyxl`) with a bold header row and auto-sized columns, stored and served through the same generated-artifacts mechanism Document Generation already built — no new download route needed. "Editing" is covered the same way `create_document` covers it: calling the tool again with the same filename overwrites it. Verified end to end: CFO genuinely called the tool with real typed data (numbers as numbers, not strings), and the downloaded `.xlsx` was confirmed via `openpyxl` readback to have the exact requested rows, bold header, and correct cell types. Permission gating, format validation, and path-traversal denial confirmed directly. Production verification surfaced a real bug: a multi-line file-content argument with trailing text after the JSON's closing brace broke the strict single-line JSON parser used for `TOOL_REQUEST`, silently failing the tool call while QA (unable to see tool execution) still passed the result. Fixed by parsing with `json.JSONDecoder().raw_decode()` against a regex-located marker instead of requiring the whole reply line to be exactly one JSON value; re-verified against the exact failure shape and against a real production task producing a genuine downloadable `.xlsx`.
- ✅ **Structured Artifacts** — once Document Generation and Spreadsheet Generation both exist as concrete cases, generalize the common shape: a task's output can be a durable, typed artifact, not only a text blob in a report. Deliberately built after the two concrete cases exist, not guessed at beforehand. Implemented by giving every artifact an explicit `type` (`text`, `document`, `spreadsheet`) instead of two separate mechanisms: the main text result was previously a special-cased "Result" section, and generated files were a separate ad hoc list with their type guessed from the filename extension. Now a tool's registry entry declares its `produces_artifact` type directly (`ego_os/tools.py`), the main text result is wrapped into the same typed shape at render time, and `task.html` renders every artifact through one unified loop. Verified end to end: a text-only task, a Document Generation task, and a Spreadsheet Generation task all render correctly through the unified path with no regression.
- ✅ **Multi-Project Operations** — the Owner can create and name more than one Project and assign tasks to the right one. Implemented as a Projects section on the dashboard (name + optional vision, list + create form) and a project selector on the task submission form; tasks and their reports now show which project they belong to. No new architecture -- `tasks.project_id` and project-scoped memory (`get_recent_memory`) already existed from Phase 1, this capability just exposes real project creation and per-task assignment through the UI instead of everything defaulting to the single "General" project. Verified end to end with two real named projects (Project Alpha, Project Beta): a task assigned to Project Beta did not see research memory from Project Alpha (no cross-contamination), while a second task assigned to Project Alpha correctly built on the first task's memory in the same project.

**Exit criteria:** each capability above has at least one real, verified task exercising it end to end; two concurrent projects run with no cross-contamination of memory context.

**Dependencies:** v0.1.

**Deferred:** tools reaching outside this repository (GitHub against other repos, Slack, email, Figma, browser); real image/video generation; automatic employee creation; Command/Dashboard surface split; mobile; an Approvals surface.

---

## ✅ v0.3 — Operational Company

**Objective:** the company runs with real operating discipline — a recorded mandate, visible handling of capability gaps, deeper operational visibility, and a product surface matching the two-surface architecture.

**Capabilities added:**

- ✅ **Recorded Mandate** — mission, starting capital, and risk policy exist as a real, versioned, Owner-approved artifact, matching the Stage 1 (Formation) exit condition in `architecture/006`, instead of being assumed in code. Implemented as a `mandate` table (versioned: each submission inserts a new version rather than overwriting) and a form on the Command page; the Owner authoring and submitting mission + starting capital + risk policy together *is* the Stage 1 approval act. Verified end to end: an initial mandate (v1) and a revised one (v2) were both submitted and both preserved.
- ✅ **Capability Gap Handling** — when no existing employee can be matched to a request, the company surfaces an Employee Creation Proposal (matching `tasks/templates/EMPLOYEE_CREATION.md`'s shape) instead of silently defaulting. Implemented by extending Orchestrator's staffing prompt to allow a `NO_MATCH: <reason>` reply, distinct from an ambiguous-but-answerable one; a genuine gap drafts a full proposal via a second LLM call, records it in a new `employee_proposals` table with `pending` status, and pauses the task at `awaiting_approval` instead of running execution/QA/delivery. The Command page lists pending proposals with full detail and Approve/Reject actions; approving or rejecting resolves the task to `gap_approved`/`gap_rejected`. Automatic employee creation itself remains deferred — approval records the decision, it does not provision a working employee. Verified end to end with two real gap-triggering requests (visual brand design, video ad production — both genuinely unstaffed today): correct `NO_MATCH` detection, a coherent drafted proposal (e.g. "Brand Designer, Creative Services"), one approved and one rejected, both resolving to the correct terminal task status. Cost of gap-handling LLM calls is included in total spend even though no report is produced.
- ✅ **Operations Visibility** — the dashboard grows toward the fuller surfaces already described in `ui/000_UI_CONCEPT.md`: company/roster view, per-employee history, and memory browsing directly rather than only seeing it silently injected into prompts. Implemented as `GET /employees/{id}` (mission, capabilities, permissions, full task history derived from `reports.employees_involved`) and `GET /projects/{id}/memory` (full memory entry list per project, not just the 5 most recent injected into a prompt). Verified end to end against real data from this session's history.
- ✅ **Command/Dashboard Split** — the combined page separates into a Strategy/Command Interface (submit, clarify, approve) and a distinct Operations Dashboard (observe), with routes clean enough that a future thin or mobile client could be built against them without server-rendered-page assumptions leaking in. `GET /` is now Command (mandate, projects, pending proposals, task submission — every POST-handling action lives here); `GET /dashboard` is observe-only (roster, tasks, cost, links into employee history and project memory). `home.html` was retired in favor of `command.html` + `dashboard.html`.

**Exit criteria:** a genuine capability gap produces an Owner-actionable proposal instead of a silent default — met; the mandate is a real record the Owner can view — met; the Owner can approve something through the Command surface and observe the outcome through the Dashboard surface as two distinct interactions — met (proposal approval happens on Command, its resolved status is then visible on Dashboard's task list).

**Dependencies:** v0.2.

**Deferred:** unattended/automatic employee creation; Gate Control's Stage 3+ rules; an actual native or responsive mobile client (this version only ensures the surface split doesn't block one later).

---

## 🔜 v0.5 — Self-Managing Company

**Objective:** the company recognizes and manages its own valuable output, and can test monetization under bounded oversight.

**Capabilities added:**

- **Digital Asset Awareness** — a task output judged worth keeping is recorded as a Digital Asset with an explicit thesis, matching the Conception/Creation/Internal Validation steps of the Digital Asset Lifecycle in `architecture/006`. Internal only; no monetization yet.
- **Controlled Monetization Readiness** — Gate Control's Stage 3 rules, the Capital Ledger, the Decision Engine, and the Experiment Engine, all already specified in `architecture/006`, get built once — and only once — a real Digital Asset with a monetization thesis exists to test them against.

**Exit criteria:** at least one Digital Asset is tracked independent of the task that produced it; Controlled Monetization exit criteria are defined only once a real candidate asset exists, not scoped against a hypothetical now.

**Dependencies:** v0.3.

**Deferred:** monetization scaling and retirement steps of the Digital Asset Lifecycle; everything past Stage 3.

---

## ⏳ v1.0 — Autonomous Digital Company

**Objective:** the full vision in `docs/000_VISION_2.md` and `architecture/006` realized — Operating Company (Stage 4) and Capital Allocation (Stage 5).

**Dependencies:** v0.5. Governed directly by `architecture/006` until v0.5 produces concrete outcomes to sequence against — not detailed further here to avoid scoping against a hypothetical.

---

## Specified but not yet scheduled

Capability inputs that are fully written down but have not yet been assigned a version. They exist so a future roadmap revision has real specification to sequence against, per the change-control rule at the top of this document — not because the company can do them today.

- **Presentation Website deliverable** (`architecture/007_PRESENTATION_WEBSITE_FORMAT.md`) — a scroll-based, dark-theme "presentation as website" format (with a linked PDF export) distilled from a real completed client engagement. Requires capabilities Ego OS does not yet have: pixel-level image manipulation, static HTML/CSS/JS editing without a build step, remote file sync with verification, and structured-document-to-PDF generation with reproduced link positions. Not scoped into a version yet — needs an explicit decision on which employee (new or existing) owns it and how far outside the current sandboxed-repository tool model (`ego_os/tools.py`) it needs to reach.
