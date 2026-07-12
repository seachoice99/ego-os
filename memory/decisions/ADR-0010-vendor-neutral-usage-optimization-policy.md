# ADR-0010: Usage optimization is a vendor-neutral policy, not a Claude-specific implementation detail

## Status

Accepted by Owner on 2026-07-12, as part of the EGO OS OPERATIONAL EXPANSION initiative (Epic 3).

## Context

TOKEN-EFFICIENCY-001 already implemented Claude-specific staged execution: fresh session per stage, Git-plus-handoff instead of conversation history, rate-limit detection, per-stage size logging. The Owner now wants this generalized into an explicit policy that applies equally to any future executor (Codex, per Epic 2's schema placeholder, or others) — not a description of what the Claude runner happens to do, but a standing policy used to *evaluate* any executor's usage behavior, including Claude's own.

The risk this ADR exists to prevent: "usage optimization" quietly becoming a euphemism for cutting corners — fewer tokens achieved by skipping review, under-specifying prompts, or accepting lower-quality output. The Owner was explicit: "не снижать качество ради формально меньшего token count."

## Decision

Adopt the following vendor-neutral principles, already proven for Claude in this codebase and now stated independent of any one executor's implementation:

1. **One stage = one new session.** No executor-specific continuation mechanism (Claude's `--continue`/`--resume`, or any future Codex equivalent) is used across a stage boundary, for any executor.
2. **Git plus a structured handoff replaces conversation history** as the sole cross-stage carryover, bounded by an explicit size limit (words or an executor-appropriate token proxy).
3. **Starting-prompt and handoff size are measured and logged for every stage, for every executor** — comparable apples-to-apples across vendors, not just within one.
4. **Capability-based model routing, never vendor lock-in.** A task/stage declares required capabilities (`models/MODEL_SELECTION_POLICY.md`'s existing pattern), not a hardcoded model. A cheaper model handles mechanical/low-ambiguity work; a stronger model handles architecture, complex code, and final review. This choice is made by the task author or an explicit, documented, testable heuristic — **never** an undisclosed automatic switch, extending TOKEN-EFFICIENCY-001's own "don't invent unsupported capabilities" honesty rule.
5. **Independent review is required for complex changes, regardless of which executor produced them, and regardless of token cost.** This principle explicitly overrides principle 3-4's cost focus: a second, independent review pass is preferred over a cheaper single pass whenever task complexity warrants it, even if that costs more tokens. Usage optimization that degrades defect rate is not optimization — it is a regression wearing a lower price tag.
6. **Metrics are collected in a vendor-neutral shape** for every stage/task: tokens (or the nearest real analog for a non-token-metered executor), estimated cost, retry count, defect rate (a task that reached apparent "done" and was later reopened/retried), and wall-clock time. Comparisons are made on this metric set, never on token count alone.
7. **Baseline before claim.** No variant may be described as "more efficient" without a same-metric-set baseline measured first, on the same or comparable real workload. TOKEN-EFFICIENCY-001's own numbers (`RUNNER-002`: 46 turns/3.1M cache-read tokens; `DA-02`: 86 turns/9.3M cache-read tokens; `DA-03`: 55 turns/4.2M cache-read tokens, unfinished) are the existing valid Claude baseline; any additional executor needs its own comparable baseline before its "optimized" variant can be claimed to help.

## Consequences

- This is primarily a normative document, not new architecture — most of principles 1-3 are already implemented for Claude by the existing runner. This epic's tasks instrument metrics collection and baseline measurement; they do not re-architect what already works.
- Explicitly defers building a second executor (no Codex implementation exists yet, per Epic 2's fail-closed placeholder) — this epic measures and prepares, it does not build Codex.
- Creates a standing gate against "regression dressed as optimization": any future change claiming a usage improvement must show baseline-vs-variant metrics side by side per this policy, or it does not qualify as validated.
- `architecture/016_USAGE_OPTIMIZATION_POLICY.md` carries the full policy text and the decision table for capability-based routing.
