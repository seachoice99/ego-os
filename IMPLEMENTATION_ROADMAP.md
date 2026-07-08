# Ego OS — Implementation Roadmap

This is the primary implementation plan for Ego OS. It sequences work that is already specified in `architecture/`, `docs/000_VISION_2.md`, and the ADRs into build order — it does not introduce new architecture. The roadmap is organized around **what the company becomes capable of doing**, not which employees happen to implement a capability at a given time — employees are replaceable competence containers (ADR-0002) and may change; the capabilities a version unlocks are the durable milestones.

**Change control:** this document is updated *before* a change in direction, not after. If implementation surfaces something the architecture or this roadmap didn't anticipate, the response is to revise this document (and flag it for an architecture review if the finding is architectural rather than sequencing) before building the new direction — not to build ad hoc and document it retroactively.

**Status legend:** ✅ done · 🔜 next · ⏳ planned, not yet started

---

## ✅ v0.1 — Working Company

**Objective:** prove the whole Task Lifecycle works end to end as a company, not a chatbot.

**Delivered:** the company (all registered employees) exists and is visible with `idle` status before any task is submitted. The Owner submits a request through a combined Command Interface/Dashboard page. Orchestrator, Writer, and QA run the full documented Task Lifecycle (Intake → Planning → Staffing → Execution → QA → Delivery → Memory Update) against one real model provider behind the capability-based `model_provider` boundary. Orchestrator genuinely chooses between specialists by required capability instead of a fixed rule. QA is a real gate — a `REVISE` verdict triggers one corrected attempt before delivery. Tasks belong to a Project; a specialist's prompt includes prior memory from the same project. Every task produces a Report with token/cost accounting and a Memory entry.

**Dependencies:** none (foundation).

---

## 🔜 v0.2 — Useful Company

**Objective:** the company can take on a meaningfully wide variety of real work, not just text drafting and review.

**Capabilities added:**

- **Tool Framework** — the general mechanism by which an employee can be granted a specific external capability without ever holding its credentials directly. This turns the Boundaries principle already stated in `architecture/005` (credentials resolved at the infrastructure layer, never held by an employee) from a promise into working code, and is the prerequisite every capability below is built on.
- **Repository Access** — read and modify files within this repository under the Tool Framework's boundary. The first concrete tool built on top of the framework.
- **Web Research** — real web search/retrieval, closing the gap between `researcher.yaml`'s existing `use_web` permission and what's actually possible today (synthesis from training knowledge only).
- **Document Generation** — a task can produce a real structured document artifact, not just plain text returned inline in a report.
- **Spreadsheet Generation / Editing** — a task can produce or edit tabular/structured data. This is also where cost and finance reporting becomes a real generated artifact rather than a single number on the dashboard.
- **Structured Artifacts** — once Document Generation and Spreadsheet Generation both exist as concrete cases, generalize the common shape: a task's output can be a durable, typed artifact, not only a text blob in a report. Deliberately built after the two concrete cases exist, not guessed at beforehand.
- **Multi-Project Operations** — the Owner can create and name more than one Project and assign tasks to the right one.

**Exit criteria:** each capability above has at least one real, verified task exercising it end to end; two concurrent projects run with no cross-contamination of memory context.

**Dependencies:** v0.1.

**Deferred:** tools reaching outside this repository (GitHub against other repos, Slack, email, Figma, browser); real image/video generation; automatic employee creation; Command/Dashboard surface split; mobile; an Approvals surface.

---

## ⏳ v0.3 — Operational Company

**Objective:** the company runs with real operating discipline — a recorded mandate, visible handling of capability gaps, deeper operational visibility, and a product surface matching the two-surface architecture.

**Capabilities added:**

- **Recorded Mandate** — mission, starting capital, and risk policy exist as a real, versioned, Owner-approved artifact, matching the Stage 1 (Formation) exit condition in `architecture/006`, instead of being assumed in code.
- **Capability Gap Handling** — when no existing employee can be matched to a request, the company surfaces an Employee Creation Proposal (the template already exists at `tasks/templates/EMPLOYEE_CREATION.md`) instead of silently defaulting. This is the first point Gate Control needs to exist in code at all — trivially, since Stage 1/2 rules are "internal only, nothing external" — and the first shape of an Approval Request: a pending-decision state, not a new subsystem.
- **Operations Visibility** — the dashboard grows toward the fuller surfaces already described in `ui/000_UI_CONCEPT.md`: company/roster view, per-employee history, and memory browsing directly rather than only seeing it silently injected into prompts.
- **Command/Dashboard Split** — the combined page separates into a Strategy/Command Interface (submit, clarify, approve) and a distinct Operations Dashboard (observe), with routes clean enough that a future thin or mobile client could be built against them without server-rendered-page assumptions leaking in.

**Exit criteria:** a genuine capability gap produces an Owner-actionable proposal instead of a silent default; the mandate is a real record the Owner can view; the Owner can approve something through the Command surface and observe the outcome through the Dashboard surface as two distinct interactions.

**Dependencies:** v0.2.

**Deferred:** unattended/automatic employee creation; Gate Control's Stage 3+ rules; an actual native or responsive mobile client (this version only ensures the surface split doesn't block one later).

---

## ⏳ v0.5 — Self-Managing Company

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
