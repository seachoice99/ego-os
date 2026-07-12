# System Architecture

Canonical, as of the 2026-07-13 architecture-correction pass (`ADR-0013` through `ADR-0017`, `architecture/018_ARCHITECTURE_CONTRADICTION_AUDIT_2026-07.md`). Replaces this document's earlier placeholder statement that "a dedicated Runtime architecture is not yet defined" — that stopped being true once `ego_os/` shipped as a real, running application; this document now describes what actually runs, alongside what is still only designed.

Per `architecture/018` C-16, and the source-of-truth hierarchy this pass establishes (see below): this document is normative architecture, ranking below Accepted ADRs and above runtime code/tests as evidence of *intent* — but where code and this document conflict on a **shipped** behavior, the contradiction gets resolved via a new ADR (per that hierarchy), not by silently trusting whichever is more convenient to read.

## Source-of-truth hierarchy (highest to lowest)

1. The most recently Accepted ADR (`memory/decisions/ADR-NNNN-*.md`) touching a given topic.
2. Normative architecture (`architecture/*.md`, this document included).
3. Machine-readable schemas and contracts (SQLite schema in `ego_os/store.py`, task-queue schema in `tasks/queue/README.md`, Skill manifest schema in `architecture/011`).
4. Runtime code and tests, as evidence that a design was actually implemented (not as the design's author).
5. `IMPLEMENTATION_ROADMAP.md` and `CHANGELOG.md`, as status/history record.
6. `product_bible/`, as product goal and principle (not implementation detail).
7. `docs/`, as historical/legacy material only.

Code never silently overrides an Accepted ADR. If code and an Accepted ADR conflict, either the code is brought back in line with the ADR, or a new Accepted ADR is written that explicitly supersedes the old one — this document, and every architecture doc under it, follows that same rule.

## Three layers

**Definitions** are versioned specifications that stay stable regardless of what executes them: `Company`, `Department`, `Project`, `Employee`, `Persona`, `Skill`, `Policy`, `Mandate`.

**Runtime Records** are the operational facts produced by executing a Definition: `ProductTask`, `ProductTaskPlan`, `Clarification`, `Subtask`, `Assignment`, `ExecutionEvent`, `Report`, `Memory`, `EmployeeProposal`, `EmployeeProvisioningTask`, `DigitalAsset`, `DigitalAssetEvent`, `BudgetLedgerEvent`, `ApprovalDecision`.

**Infrastructure** is replaceable resources a Definition is executed against: `Model Provider`, `Model Adapter`, `Tool`, `Skills Registry`, `Background Worker`, `Automation Queue`, `AutomationTask`, `Executor`, `Runner Agent`, `Control Server`.

Business/product entities (Definitions, Runtime Records) never depend on a specific AI vendor — models are Infrastructure, selected by required capability per `models/MODEL_SELECTION_POLICY.md`, never hardcoded by vendor/model ID outside an infrastructure adapter/config (see `architecture/001_CORE_ENTITIES.md`'s Infrastructure table and `ADR-0016`).

## Entity tables

Each entity below is documented in full, with authoritative owner, identity, versioning, persistence, lifecycle, relations, authorization boundary, and implementation status, in `architecture/001_CORE_ENTITIES.md`. This document covers only the layer grouping and cross-cutting rules; per-entity detail lives in `001` so it is never duplicated (and never drifts) between the two files.

## Runtime flow (as actually implemented today, `ego_os/lifecycle.py`)

1. Owner submits a request (`POST /tasks`, `ego_os/main.py`) → a **ProductTask** row is created (`intake`).
2. The **Orchestrator** Employee interprets the request, checks whether a **Clarification** is genuinely required (`ADR-0014`; full runtime for this step is tracked as partial — see `architecture/001`'s status column), and persists a **ProductTaskPlan** before staffing.
3. The Orchestrator estimates required capabilities and selects one Employee whose `required_capabilities` matches (today: exactly one specialist per ProductTask — multi-Employee/Subtask/Assignment execution is a supported *contract*, not yet the runtime; see `architecture/001` and `ADR-0014`).
4. A missing capability produces an **EmployeeProposal**; Owner approval creates an **EmployeeProvisioningTask** (an **AutomationTask**, since it edits repository files) and, once provisioning completes, the original ProductTask is replanned (`ADR-0015`, Decision 7).
5. The selected Employee executes via `ego_os/model_provider.py` (an **Infrastructure** boundary over an OpenRouter-compatible **Model Provider**), logging **ExecutionEvent**s and consulting the **Skills Registry** for any referenced Skill (never executing Skill content as code — `ego_os/skills.py`).
6. Before any paid call, a **BudgetLedgerEvent** reservation is checked and recorded (`ADR-0016`) against the current global operating budget.
7. **QA** reviews the draft; `ADR-0014` governs the gate (PASS/REVISE/needs_owner_review).
8. On any terminal outcome, a **Report** is created (a projection over `ExecutionEvent`s, `ADR-0014`) and, if delivered, a **Memory** entry is stored.

Separately, and never overlapping the above: the **Automation Queue** (`tasks/queue/*.yaml`) is driven by `automation/claude_task_runner.js` (the **Executor**/**Runner Agent**), coordinated by the **Control Server** (`automation/control_server.js`), to autonomously change this repository itself (`ADR-0006`, `ADR-0012`, `ADR-0013`) — this is the **AutomationTask** lifecycle, formally separate from the ProductTask lifecycle above (`ADR-0015`).

## Owner Interface Principle

The Owner interacts with a single executive operating layer (the Orchestrator, and Ego OS's own web UI) — never with individual Employees directly. Employees perform work internally and surface results only through Reports, task outputs, and the operating layer's own communication back to the Owner.

## Hard rule

Business/product entities must not depend on specific AI vendors. Claude, GPT, Gemini, Veo, Runway, Flux and other providers are replaceable Infrastructure, selected by capability (`models/MODEL_SELECTION_POLICY.md`, `ADR-0016`'s fail-closed selection rules).
