# Usage Optimization Policy

Implements ADR-0010. This is a policy document: it defines what "more efficient" is allowed to mean in this codebase, and what evidence is required before anything may be described that way. It is not itself a new subsystem.

## The seven principles

See ADR-0010's Decision section for the full text. Summarized as a checklist any executor's usage behavior can be scored against:

1. One stage = one new session (no cross-stage continuation mechanism, for any executor).
2. Git + structured handoff replaces conversation history, size-bounded.
3. Prompt/handoff size measured and logged per stage, per executor.
4. Capability-based model routing, explicit and disclosed — never a silent auto-switch.
5. Independent review for complex changes, regardless of cost.
6. Vendor-neutral metrics: tokens/analog, cost, retries, defect rate, wall-clock time.
7. Baseline measured before any variant is claimed better.

## Reference implementation: Claude runner (already shipped)

`automation/session_manager.js` + `automation/claude_task_runner.js` (TOKEN-EFFICIENCY-001) implement principles 1-3 for Claude today: `claudeInvocationArgs()` never emits `--continue`/`--resume`; `buildHandoffBlock()`/`validateHandoff()` enforce the size-bounded handoff; `estimatePromptSize()` logs every stage's prompt size to `result.sessions[]`. No new code is needed to satisfy 1-3 for Claude — this epic's tasks build the *comparison* and *baseline* tooling around what already exists.

## Real baseline (measured, not estimated)

From this repository's own runner logs, cited in `automation/README.md`'s TOKEN-EFFICIENCY-001 section and reused here as the Claude baseline principle 7 requires:

| Task | Turns | Cache-read tokens | Outcome |
|---|---|---|---|
| `RUNNER-002` (trivial doc task) | 46 | 3.1M | done |
| `DA-02` (real feature) | 86 | 9.3M | done |
| `DA-03` (real feature) | 55 | 4.2M | did not finish |

UOP-03 extends this table with every task run since (including the multi-stage `TOKEN-EFFICIENCY-VERIFY` runs, which are themselves a useful data point: three real rate-limit encounters, zero false successes).

## Capability-based routing decision table (principle 4, made explicit and disclosed)

| Work shape | Recommended tier | Reasoning |
|---|---|---|
| Reading logs, checking task/queue status, mechanical doc edits | cheaper/faster model | Low ambiguity, high volume, cost dominates |
| Ordinary feature code with clear acceptance criteria | mid-tier | Balance of correctness and cost |
| Architecture, non-trivial code, cross-cutting changes, final review | strongest available model | Correctness dominates; a mistake here is expensive to unwind later |

This table is **guidance for a task author setting `preferred_model` explicitly** (per `architecture/015`'s schema addition) — it is not, and this epic does not build, an automatic classifier that silently picks a model. That remains an explicitly named non-goal, matching TOKEN-EFFICIENCY-001's own "don't invent unsupported capabilities" stance.

## Defect-rate tracking (principle 6, the metric most usage-optimization efforts skip)

A task's `result` gains an optional `retries_after_apparent_done` counter: incremented if a task previously reached `status: "done"` (or was believed complete) but was later reopened, retried, or found to require further work. This is the concrete, measurable form of "don't cut corners for a lower token count" — an executor/policy variant that lowers token count while raising this counter has not improved anything.

## Vertical task sequence

See `tasks/queue/UOP-*.yaml`. Order: `UOP-01 → UOP-02 → UOP-03 → UOP-04` (01/02 can run in either order; 03 depends on 01; 04 is independent documentation work and may run anytime after this document exists).
