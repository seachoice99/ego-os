# Digital Asset Model

This document defines the domain model for Digital Assets — the concrete implementation of `architecture/006_AUTONOMOUS_COMPANY_ARCHITECTURE.md` Section 4's Digital Asset Lifecycle, scoped to its first three steps (Conception, Creation, Internal Validation, and the Candidate/Shelved decision) for v0.5, per `IMPLEMENTATION_ROADMAP.md`. See ADR-0007 for the decisions this document implements.

This document does not define UI layout, database column types, or route signatures in detail — those are implementation choices for DA-01/DA-02 to make, consistent with the concepts fixed here.

## 1. Digital Asset

A **Digital Asset** is a company-owned record of something the company built that:

- can be reused, independent of the request that originally produced it;
- retains value after its source Task is closed;
- has an identifiable audience or internal consumer (who would use or benefit from it);
- carries evidence of its own quality, not just a claim of quality;
- has a clear, specific next step (what would actually be done with it next);
- can eventually carry a testable monetization thesis (a hypothesis, never a valuation);
- required no external transaction, third-party counterparty, or real capital exposure to create.

A Digital Asset is not a copy of an artifact and not a duplicate Task record. It is a distinct, durable pointer to something already produced, plus the evidence and thesis that justify treating it as more than disposable output.

## 2. Candidate

A **Candidate** is a Digital Asset in its earliest state: proposed, but not yet reviewed by the Owner. A Candidate can be created two ways:

- **automatically**, by the bounded post-Delivery assessment described in DA-03, when a Task's result plausibly meets the properties in Section 1;
- (not built in v0.5, but not precluded by this model) manually, by a future Owner-initiated action.

A Candidate carries the same record shape as an Accepted Asset — status is what distinguishes them, not a separate table (ADR-0007, decision 1). A Candidate has no authority: it cannot be validated, cannot receive a monetization thesis beyond an initial hypothesis, and does not change what the system is allowed to do. It is a proposal, not a decision.

## 3. Provenance

**Provenance** is the immutable record of exactly where a Digital Asset came from. It is written once, when the Candidate is created, and never edited afterward (ADR-0007, decision 4). Provenance includes:

- the **source Task** (`source_task_id`) — which Task's Delivery produced this Asset;
- the **source Report** — the Report record for that Task, which already carries `employees_involved`, `employee_versions`, `skills_used`, `input_tokens`/`output_tokens`/`cost`, and `artifacts`;
- **source artifact references** — for each generated artifact the Asset is built from, its filename/type and the task it belongs to, resolved through the existing `tools.GENERATED_DIR`/`download_artifact` path-safety logic (`ego_os/main.py`) rather than copied to a new location;
- **Employee versions** — which version of which Employee(s) actually did the work, taken from `reports.employee_versions` (ADR-0002: history must keep referencing the Employee version that performed the work, not whatever version exists now);
- **Skills used**, if any — taken from `reports.skills_used` (Skills and Capability Management initiative, `architecture/012_EMPLOYEE_SKILL_COMPOSITION_CONTRACT.md`);
- **Model used**, where available, from the corresponding `execution_events` rows;
- a **created timestamp**.

Provenance is the difference between a Digital Asset and an arbitrary claim of value: every Asset must be traceable back to the real Task, Report, Employee versions, and artifacts that produced it, and that trace can never be rewritten (`CLAUDE.md`'s "historical Task/Report/Memory records are never rewritten" principle, extended here to Digital Assets).

## 4. Source Task / Report / Artifact

These are the existing entities from `architecture/001_CORE_ENTITIES.md` and `architecture/002_TASK_LIFECYCLE.md`, unchanged by this document:

- **Task** — the unit of work that was requested and delivered. A Digital Asset always has exactly one source Task; a Task may have zero or one Candidate (DA-03: at most one automatic assessment per Task, so at most one automatically-nominated Candidate per Task).
- **Report** — the mandatory Delivery-time record (`architecture/003_REPORTING_AND_LOGS.md`) a Digital Asset's provenance reads from. A Digital Asset does not replace or duplicate a Report; it references one.
- **Artifact** — a typed, durable output already defined by the Structured Artifacts capability (v0.2). A Digital Asset may reference one or more of a Task's artifacts, or may be based primarily on the Report's `result_text`, without needing a file artifact to exist.

## 5. Evidence

**Evidence** is the concrete, checkable support for why an Asset is believed to have reusable value — never an unsupported claim. Evidence recorded at Candidate creation includes at minimum the specific reason the assessment judged the output reusable (Section 8's `reusable_value` and `evidence` fields). Evidence recorded at Internal Validation (Section 7) additionally addresses whether the artifact/source still exists, whether the result is reproducible or accessible, and whether the claimed audience and reusable value hold up under a direct check. Evidence is operational and checkable, matching the reporting principle already established for logs (`architecture/003_REPORTING_AND_LOGS.md`: "operational reasoning... never raw hidden reasoning") — never the model's raw chain-of-thought.

## 6. Lifecycle

A Digital Asset moves through these states (ADR-0007, decision 6: every transition is an append-only event, never a silent field update):

```
candidate --owner_accepted--> accepted --validation passed--> internally_validated
    |                              |                                    |
    +--owner_rejected--> rejected  +--(archival, later)--> archived <---+
```

- **`candidate`** — nominated, awaiting Owner decision. Initial state for every Asset.
- **`accepted`** — the Owner has explicitly approved this Candidate as a real Digital Asset. Independent of the source Task's own lifecycle from this point on (ADR-0007, decision 4), but provenance is unchanged.
- **`rejected`** — the Owner has explicitly declined this Candidate. Not deleted (ADR-0007, decision 7). A `rejected` Asset can only ever become `accepted` again through a *new*, explicit Owner decision event — never automatically, never by re-running the same assessment.
- **`internally_validated`** — an `accepted` Asset that has passed the Internal Validation flow (Section 7, DA-04) and carries a required, specific monetization thesis (Section 9).
- **`archived`** — a terminal, inert state for an Asset that is no longer active (superseded, no longer relevant) but is kept for history. Not built as an Owner-facing action in v0.5's DA-01..DA-05; the status and event type exist in the model so a later, explicitly-scoped capability can use them without a schema change.

Disallowed transitions (enforced at the persistence layer, not just the UI):

- `candidate → internally_validated` directly — Owner acceptance is mandatory first.
- `accepted → internally_validated` without a recorded validation result and its supporting evidence.
- `rejected → accepted` without a new, distinct Owner decision event (the original rejection event is never overwritten to flip the outcome).

### Conceptual lifecycle ↔ runtime mapping (2026-07-13 audit, `architecture/018` C-15)

`architecture/006_AUTONOMOUS_COMPANY_ARCHITECTURE.md`'s Digital Asset Lifecycle (conceptual) and this document's persisted `digital_assets.status`/`digital_asset_events` (runtime, `ego_os/store.py`) already agree with each other — this table makes that mapping explicit rather than leaving a reader to infer it across two documents. No contradiction was found here during the audit; this is the one area of this pass that needed only documentation, not a fix.

| Conceptual phase (`architecture/006`) | Persisted `status` | Required event (`digital_asset_events.event_type`) | Allowed actor | Gate Control result | Implementation status |
|---|---|---|---|---|---|
| Conception / creation | `candidate` | `candidate_created` | `system` (automatic nomination, e.g. DA-03) | none required — a Candidate is not yet a company commitment | implemented |
| Owner continuation decision (accept) | `accepted` | `owner_accepted` | `owner` only | Owner approval required — an automatic process may never accept its own nomination (ADR-0007, decisions 2–3) | implemented |
| Owner continuation decision (decline) | `rejected` | `owner_rejected` | `owner` only | Owner approval required | implemented |
| Internal validation pass + thesis | `internally_validated` | `validation_passed` | `system` or `owner` | requires a recorded `validation_status='passed'` and a non-empty `monetization_thesis` in the same call — no partial/implicit pass | implemented |
| No longer active | `archived` | `archived` | `system` or `owner` only | — | implemented at the persistence layer; **not yet exposed as an Owner-facing UI action** in DA-01..DA-05 (the status/event exist so a later, explicitly-scoped capability can use them without a schema change) |
| Monetization (Stage 3 / Controlled Monetization, `architecture/006`) | — | — | Owner, with its own dedicated Gate Control review | requires explicit, separate Owner approval; never triggered by reaching `internally_validated` alone | **planned** |
| Scaling | — | — | Owner | requires explicit, separate Owner approval | **planned** |
| Maintenance | — | — | system/Owner | — | **planned** |
| Retirement (distinct from `archived`) | — | — | Owner | requires explicit, separate Owner approval | **planned** |

DA-03 (automatic nomination) creates a `candidate` and nothing more — it never accepts, publishes, monetizes, or otherwise bypasses the Owner-approval rows above; every row past `candidate`/`rejected` requires an explicit `owner` actor or, for `internally_validated`, a real validation result with its required evidence.

## 7. Internal Validation

**Internal Validation** is a bounded check, run only against an `accepted` Asset, that re-tests the claims made at Candidate creation against reality — matching `architecture/006` Section 4's "Internal Validation... checked against its own original thesis: does it still hold." It checks, at minimum:

- the source artifact or reference still exists and is reachable;
- the result is reproducible or otherwise accessible (not something that silently rotted since Candidate creation);
- the claimed target audience is specific, not vague;
- the claimed reusable value is substantiated, not asserted;
- the evidence actually supports the claims made;
- there is no apparent violation of an Owner constraint (from the mandate, from `architecture/006`'s Gate Control, or from this document);
- known shortcomings are stated plainly, not omitted;
- a concrete internal next step is identified.

Internal Validation is itself internal and reversible — nothing about running it, passing it, or failing it is visible outside the company or constitutes any external action (`architecture/006` Section 2, Stage 2 Gate Control).

## 8. Value Thesis

The **value thesis** is the specific reason a Candidate is believed to be worth keeping, recorded at nomination time (automatic assessment, DA-03) and re-checked at validation time (DA-04). It answers, concretely: what is this, what value does it create, and for whom. A value thesis that only restates that "this could be useful" without a specific audience or specific reusable property is not sufficient — matching `architecture/006` Section 4's "A proposal without a thesis is not an asset candidate — it is an idea that still needs shaping."

## 9. Monetization Thesis

The **monetization thesis** is a hypothesis about how an `internally_validated` Asset's value *might eventually* be converted into something the Owner could realize — never a valuation, never a plan of record, and never itself a permission to act. Per ADR-0007 decision 5, it must contain:

- who this could plausibly be useful to;
- what value someone might plausibly pay for;
- the cheapest possible future test of that hypothesis;
- what assumptions remain unproven;
- what is explicitly prohibited without separate Owner approval (any external action at all, at this stage).

A monetization thesis existing, however specific, changes nothing about Gate Control (`architecture/006` Section 2): Stage 2 still prohibits any external transaction, publication, or third-party contact regardless of how validated an Asset is or how confident its thesis reads. Money is never invented at this stage — v0.5 fixes evidence, a value thesis, and a monetization thesis, deliberately not an unverified valuation (per the accepted product decisions this document implements).

## 10. Owner Approval

Owner approval is the only mechanism that:

- moves a Candidate to `accepted` or `rejected`;
- authorizes Internal Validation to run against an `accepted` Asset;
- (in a later, separately-scoped stage) authorizes any Controlled Monetization test.

No automatic process may perform any of the above. Silence is not approval (`docs/000_VISION_2.md`: "Молчание Owner не означает согласие"). Owner approval events are themselves part of the append-only `digital_asset_events` history (ADR-0007, decision 6) — a decision is a fact about what happened, not a mutable flag.

## 11. Boundaries

- **Project** — a Digital Asset belongs to the same Project as its source Task (`project_id`, carried through from `tasks.project_id`), so Asset visibility can eventually be scoped per-Project the same way memory already is. A Digital Asset does not become a new kind of Project.
- **Task** — a Digital Asset references its source Task via immutable provenance (Section 3) but is not a Task itself, has no `run_state`, and does not go through the Task Lifecycle. Creating or reviewing a Digital Asset never re-opens, re-runs, or mutates its source Task.
- **Report** — a Digital Asset's provenance reads from its source Report but does not replace it; a Report remains the mandatory Delivery-time record for its Task regardless of whether that Task ever produces a Digital Asset.
- **Memory** — Memory entries (`architecture/001`) remain the company's running record of what happened project-wide; a Digital Asset is a distinct, heavier-weight record reserved for output judged to have durable, reusable value, not a replacement for ordinary Memory entries.
- **Finance** — Cost and Token Accounting (`architecture/004_COST_AND_TOKEN_ACCOUNTING.md`, ADR-0003) continues to track the cost of producing the source Task and the cost of the assessment/validation steps themselves (as ordinary task/tool cost). A Digital Asset's `monetization_thesis` is never itself a Finance record, never contributes a number to any cost or revenue report, and is not the Capital Ledger described in `architecture/006` Section 6 (out of scope until Stage 3, per ADR-0007).
