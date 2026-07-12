# ProductTask Lifecycle

Canonical, per `ADR-0014`. Governs **ProductTask** only (`ego_os/store.py`'s `tasks` table) — the separate **AutomationTask** lifecycle (`tasks/queue/*.yaml`) is documented in `tasks/queue/README.md` and is a different bounded context (`ADR-0015`).

## Two separate questions: `status` and `run_state`

A ProductTask row answers two independent questions, in two separate columns, never merged:

- **`status`** — what stage of the Task Lifecycle is this ProductTask in, semantically? Governed by the transition table below.
- **`run_state`** (`ego_os/worker.py`) — is the background worker thread currently doing anything with this row, mechanically? One of `queued`, `running`, `completed`, `failed`, `cancelled`.

### Allowed combinations

| `status` | Allowed `run_state` | Notes |
|---|---|---|
| `intake`, `waiting_for_clarification`, `planning`, `staffing`, `execution`, `qa`, `revision` | `running` (while the worker thread is actively inside `lifecycle.run()`), or `queued` (not yet picked up) | Never `completed`/`failed` while `status` is non-terminal and the worker hasn't actually stopped touching the row |
| `awaiting_approval` | `completed` | `lifecycle.run()` returns cleanly after this — it is a scheduling-complete, lifecycle-non-terminal state (Owner action is what advances it next) |
| `gap_approved` | `completed` (until an EmployeeProvisioningTask replans it, at which point a fresh worker run begins and `run_state` returns to `queued`) | |
| `gap_rejected`, `delivered`, `needs_owner_review`, `failed`, `cancelled` | `completed` (or `failed`, only if the exception that produced `failed` happened *after* `status` already reached one of these — see `ego_os/worker.py`'s `except Exception` clause, which does not itself inspect `status`) | These are lifecycle-terminal; `run_state` should be `completed` in the ordinary case |

## State transition table

| From | Actor | Precondition | Event | To | Terminal? | Report required? | Memory allowed? | Approval required? |
|---|---|---|---|---|---|---|---|---|
| (new) | Owner | — | task submitted | `intake` | no | no | no | none |
| `intake` | Orchestrator | a critical, result/budget/rights/risk-changing fact is missing (Owner Decision 8's bar — not asked for anything safely assumable) | `clarification_needed` | `waiting_for_clarification` | no | no | no | none |
| `waiting_for_clarification` | Owner | Owner answers the persisted Clarification | `clarification_answered` | `planning` | no | no | no | Owner's structured answer |
| `intake` | Orchestrator | no clarification needed | `intake_complete` | `planning` | no | no | no | none |
| `planning` | Orchestrator | a ProductTaskPlan is persisted (interpreted objective, deliverables, capabilities, tools, cost/budget estimate, risks, assumptions, QA criteria — `ADR-0014`) | `plan_created` | `staffing` | no | no | no | none |
| `staffing` | Orchestrator | a matching Employee exists | `staffed` | `execution` | no | no | no | none |
| `staffing` | Orchestrator | no Employee matches the required capability | `gap_detected` | `awaiting_approval` | no | no | no | none yet (an EmployeeProposal is drafted; Owner decides next) |
| `awaiting_approval` | Owner | reviews the EmployeeProposal | `proposal_approved` | `gap_approved` | no | no | no | Owner |
| `awaiting_approval` | Owner | reviews the EmployeeProposal | `proposal_rejected` | `gap_rejected` | **yes** | **yes** | no | Owner |
| `gap_approved` | system | the resulting EmployeeProvisioningTask (an AutomationTask) completes | `provisioning_complete` | `planning` (replanned) | no | no | no | none (already approved) |
| `execution` | Employee | a draft is produced | `draft_ready` | `qa` | no | no | no | none |
| `qa` | QA | verdict is `PASS` (first or second call) | `qa_pass` | `delivered` | **yes** | **yes** | **yes** | none (automatic) |
| `qa` | QA | verdict is `REVISE`, and this is the **first** QA call for this ProductTask | `qa_revise_first` | `revision` | no | no | no | none |
| `revision` | Employee | a corrected draft is produced | `revision_ready` | `qa` | no | no | no | none |
| `qa` | QA | verdict is `REVISE` on the **second** QA call, or the verdict is malformed (neither `PASS` nor a well-formed `REVISE: ...`) | `qa_revise_second` / `qa_malformed` | `needs_owner_review` | **yes** (draft-shaped terminal — shown to Owner as a draft, never described as delivered) | **yes** | no | none yet (Owner decides next) |
| `needs_owner_review` | Owner | accepts the draft as-is | `owner_accepts_draft` | `delivered` | **yes** | **yes** (superseding/updated) | **yes** | Owner |
| `needs_owner_review` | Owner | allows exactly one further attempt | `owner_requests_retry` | `revision` | no | no | no | Owner |
| `needs_owner_review` | Owner | closes the task without delivery | `owner_closes_task` | `cancelled` | **yes** | **yes** | no | Owner |
| any of `intake`/`planning`/`staffing`/`execution`/`qa`/`revision` | system | an unrecoverable exception, tool failure, model/provider failure, budget exhaustion, or permission denial occurs | `execution_error` | `failed` | **yes** | **yes** | no | none (the Owner may start a new ProductTask; this one does not auto-retry) |

`terminal_reason` (an additive field on `tasks`/`reports`, `ADR-0014`) records a structured `{category, detail}` alongside every terminal `status` above — `category` is one of `qa_failed`, `capability_gap_rejected`, `budget_exhausted`, `permission_denied`, `tool_failure`, `provider_failure`, `owner_cancelled`, or `none` (successful, unremarkable delivery). This is deliberately a shared terminal shape plus a structured reason rather than one new `tasks.status` string per failure mode, while `gap_approved`/`gap_rejected` are kept as their own real status values for backward compatibility (existing code already reads them, `ego_os/main.py:506-508`).

## Enforcement

Every transition above must go through a single, named transition-checking function in `ego_os/store.py` (the `tasks.status` analogue of `digital_assets`' existing `transition_asset`/`_ASSET_TRANSITIONS`). A call naming a `(current_status, new_status)` pair not in this table raises rather than silently writing an unvalidated string — the same discipline `digital_assets.status` already had and `tasks.status` did not.

## Steps not yet reflected in a `status` value

- **Subtasks, dependencies, handoffs, checkpoints, and multi-Employee Assignment** are supported at the *contract* level (`architecture/001_CORE_ENTITIES.md`'s Runtime Records) but do not yet have their own lifecycle states — today's `execution` status covers a single Employee's single, sequential turn. This is a deliberate, named scope boundary (`product_bible/004_MVP_SCOPE.md` excludes "complex parallel orchestration" from MVP), not an oversight.
