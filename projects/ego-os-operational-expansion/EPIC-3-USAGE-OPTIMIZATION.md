# Epic 3: Usage Optimization

## Owner brief

Turns "run more tasks within the same usage limits" from something only Claude's runner happens to do into a written, checkable policy any future executor (Codex included) has to meet — with an explicit rule that a lower token count is never an excuse for lower quality. This epic mostly measures and documents what already works; it does not rebuild the runner.

**Product impact:** a real, evidence-based baseline exists to judge any future "efficiency" claim against — including ones made about Claude itself.

## Governing documents

- `memory/decisions/ADR-0010-vendor-neutral-usage-optimization-policy.md`
- `architecture/016_USAGE_OPTIMIZATION_POLICY.md`

## Risks

- **Metrics theater.** A metrics exporter that nobody reads before making changes is decoration, not policy. UOP-03's baseline report is the concrete artifact meant to prevent this — it should be genuinely referenced whenever a future usage-optimization change is proposed.
- **Defect-rate field with no real path to increment (UOP-02).** RUNNER-CONTROL-UI's `taskActionAllowed` only permits retry from `failed`/`waiting_for_auth`/`interrupted`, not from `done` — the "reopen a done task" scenario this counter is meant for may not have a real trigger yet. UOP-02's own acceptance criteria require reporting this honestly rather than forcing an artificial code path just to exercise the field.

## Dependencies

- No dependency on Epic 1 or Epic 4.
- Loosely related to Epic 2 (both touch task-schema fields) but independently executable — UOP tasks never touch `executor`/`preferred_model`/etc.

## Acceptance criteria (epic-level)

1. `automation/USAGE_BASELINE.md` cites real, run-derived numbers — no estimates presented as measurements.
2. The capability-routing table exists in exactly one authoritative place, cross-linked, not duplicated with drift risk.
3. No task in this epic claims an "optimization" without a baseline-vs-variant comparison, per ADR-0010 principle 7 — since this epic only measures the *existing* Claude baseline, no variant claim is made yet; that discipline applies to whoever proposes the first variant later.

## Execution order

`UOP-01 → {UOP-02, UOP-03} → UOP-04` (UOP-04 is independent and may run anytime; ordered last here only because it's lowest-value if the routing table it references were still being revised).

## Owner gates

None — this epic is entirely internal tooling and documentation, no `OWNER_ONLY` risks, no external effects.

## Tasks

`UOP-01.yaml` · `UOP-02.yaml` · `UOP-03.yaml` · `UOP-04.yaml` — all `status: blocked`, none executed as part of this planning session.
