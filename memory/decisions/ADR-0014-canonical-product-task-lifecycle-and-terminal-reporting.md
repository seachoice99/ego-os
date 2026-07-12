# ADR-0014: Canonical ProductTask lifecycle, QA as a real gate, and mandatory terminal reporting

## Status

Accepted by Owner on 2026-07-13, as part of the 2026-07-13 architecture-correction pass. Resolves `architecture/018_ARCHITECTURE_CONTRADICTION_AUDIT_2026-07.md`'s C-03, C-04, C-05, C-06, and (contract-only) C-07 and C-14.

This ADR does not reverse ADR-0001, ADR-0002, or ADR-0003 — it makes their existing commitments (chat is not the product surface; employees are versioned competence containers; cost accounting is core) enforceable by a single, named state machine instead of leaving `tasks.status` an unvalidated free-text column any code path can set to anything.

## Context

Three real gaps exist between what `architecture/002_TASK_LIFECYCLE.md`/`architecture/003_REPORTING_AND_LOGS.md` say and what `ego_os/lifecycle.py`/`ego_os/store.py` actually do, found during discovery:

1. **QA is not actually a gate.** `architecture/002`'s QA step is silent on failure consequence. The real code (`ego_os/lifecycle.py`) allows exactly one REVISE-triggered redo, then delivers regardless of what the *second* QA call says — a second `REVISE` is silently treated as good enough. There is no `needs_owner_review` status anywhere in the codebase.
2. **Not every terminal state produces a Report**, even though `architecture/003` says "every task must produce a report" unconditionally. The capability-gap path (`awaiting_approval`), both proposal-decision paths (`gap_approved`/`gap_rejected`), and any exception raised mid-execution (e.g. a Skill resolution failure) currently end with no Report at all.
3. **No persisted Plan exists.** `architecture/001_CORE_ENTITIES.md` defines `Task.plan`, but `tasks` has no `plan` column and no sibling plan table — nothing is persisted before execution begins beyond the raw `request_text`.
4. **`tasks.status` has no enforcement.** `store.update_task_status(task_id, status)` accepts any string unconditionally. There is no equivalent of `digital_assets`' `_ASSET_TRANSITIONS` map for `tasks.status` — an invalid transition is not just unvalidated, it is not even a concept the code can check.

## Decision

### Lifecycle vocabulary (minimum states, per the Owner's list)

`intake → waiting_for_clarification → planning → staffing → awaiting_approval → execution → qa → revision → needs_owner_review → delivered | failed | cancelled`

Additional statuses already in real use (`gap_approved`, `gap_rejected`) are kept for backward compatibility — see "Terminal state shape" below for how they relate to the new terminal vocabulary rather than multiplying further.

### Terminal state shape: shared terminal marker + structured reason, not one status per failure mode

Per the Owner's explicit preference ("Предпочтительно хранить общий terminal state и structured reason... Но backward compatibility должна сохраняться"): rather than minting a new distinct `tasks.status` string for every one of `gap_rejected`/`budget_exhausted`/`permission_denied`, this ADR defines a single additive `terminal_reason` field (structured: `{category, detail}`, category drawn from a fixed enum including `qa_failed`, `capability_gap_rejected`, `budget_exhausted`, `permission_denied`, `tool_failure`, `provider_failure`, `owner_cancelled`) attached to whichever of `delivered`/`failed`/`cancelled`/`needs_owner_review`/`gap_rejected` the task actually reached. `gap_approved`/`gap_rejected` remain real, distinct `tasks.status` values (already shipped, already read by `ego_os/main.py:506-508`) — this ADR does not rename or remove them, it only adds the structured-reason field alongside every terminal status, old and new.

### QA gate (binding on `ego_os/lifecycle.py`)

- `PASS` (first or second call) → Delivery.
- First `REVISE` → exactly one automatic corrected re-run (unchanged from today).
- Second `REVISE` → `needs_owner_review` (new terminal-shaped status; `terminal_reason.category = "qa_failed"`). This is shown to the Owner as a **draft**, never described as delivered or successfully completed.
- A malformed QA verdict (neither `PASS` nor `REVISE: ...`) fails closed to `needs_owner_review` with `terminal_reason.category = "qa_failed"` and a note that the verdict was malformed — never silently treated as `PASS`.
- A tool failure during execution or QA must surface as its own `terminal_reason.category` (`tool_failure`) — never masked by a model producing text that looks like success.
- From `needs_owner_review`, the Owner may: accept the draft (→ `delivered`, with the Owner's acceptance recorded as the approval that authorized it, distinct from an automatic `PASS`), allow exactly one more attempt (→ back to `revision`), or close the task (→ `cancelled`, with `terminal_reason.category = "owner_cancelled"`).
- Delivery is never reachable without either a `PASS` verdict or this explicit Owner acceptance — there is no third path to `delivered`.

### Terminal reporting (binding on `ego_os/lifecycle.py`, `ego_os/main.py`, `ego_os/store.py`)

A Report is created for **every** terminal ProductTask state: `delivered`, `failed`, `cancelled`, `needs_owner_review`, `gap_rejected`, and any future terminal reached via `terminal_reason`. `gap_approved` is not itself terminal (per the Owner's Decision 7, it leads to a provisioning task and a replan) and does not require a Report at the moment it's reached — the eventual re-planned task's own terminal state does.

Report is a versioned contract (`schema_version` field) built as an **immutable projection over `ExecutionEvent`** (the append-only operational source) — never an independent second record of the same facts. Where `reports.timeline` already exists as a column, it is documented as a cached projection of `execution_events`, not an independent source of truth (resolves C-14).

### `status` vs. `run_state` — two different questions, both kept

`tasks.status` (lifecycle: what stage of the Task Lifecycle is this in, semantically) and `tasks.run_state` (scheduling: is the background worker currently doing anything with this row) remain **separate columns answering separate questions**, per the existing `ego_os/worker.py` design — this ADR does not merge them. Their allowed combinations are documented in `architecture/002_TASK_LIFECYCLE.md`'s transition table (e.g. `status="needs_owner_review"` always pairs with `run_state="completed"`, never `"running"`; `status` reaching any terminal value must coincide with `run_state` leaving `"running"`).

### Enforcement: a single transition function

`ego_os/store.py` gains a single transition-checking function (analogous to `digital_assets`' existing `transition_asset`/`_ASSET_TRANSITIONS`) that every `status` change must go through; a call that names an invalid `(current_status, new_status)` pair raises, rather than writing an unvalidated string. Direct, unchecked `update_task_status()` calls are replaced or wrapped so an invalid transition is structurally impossible, not just discouraged by convention.

### Clarification Check (contract now, runtime as capacity allows this pass)

`waiting_for_clarification` is added to the lifecycle vocabulary and backed by a persisted `Clarification` record (question asked + Owner's structured answer), per the Owner's Decision 8 (only a genuinely critical question triggers this state; anything safely resolvable by reasonable assumption does not). This ADR fixes the *contract*; whether the full ask-and-resume runtime mechanism lands in the same implementation pass as the QA-gate rework is a capacity question tracked in this pass's own final report, not a re-litigation of this decision.

### Persisted Plan

A `ProductTaskPlan` record (see also ADR-0015 for the ProductTask/AutomationTask naming this uses) is persisted before `execution` begins, containing at minimum: interpreted objective, expected deliverables, selected Employee(s), required capabilities, allowed Tools, estimated cost, task budget, risks, assumptions, QA acceptance criteria, required approvals, and planned subtasks/dependencies if any are needed. Execution must not begin without one, except for tasks explicitly flagged as safe and trivial (a narrow, named exception, not a default).

## Consequences

- `ego_os/lifecycle.py` requires real changes: a `needs_owner_review` branch after the second QA call, malformed-verdict handling, Report generation on every terminal path (not only the success path), and persisting a Plan before execution.
- `ego_os/store.py` requires additive schema changes: a status-transition-checking function, a `terminal_reason` field on `tasks`/`reports`, a `product_task_plans` table, a `clarifications` table. All additive (`CREATE TABLE IF NOT EXISTS` / `_ensure_column`), matching this repository's existing migration discipline — no destructive rename, no dropped column.
- Existing tests that assume the old (gap-permissive) QA behavior may need updating; new tests are required for every branch listed above (see this pass's test plan).
- `architecture/002_TASK_LIFECYCLE.md` is rewritten to carry the full transition table this ADR describes, replacing its current silence on QA-failure consequence.
