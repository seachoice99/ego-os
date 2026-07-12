# Multi-Executor Dispatch: schema, tiers, and API contract

Implements ADR-0012. This finalizes the schema `architecture/015_RUNNER_OPERATIONS_INTEGRATION.md` introduced as a placeholder (`executor`, `preferred_model`, `fallback_executor`, `context_budget`) and extends it with the fields needed for a real Claude + Codex + OpenRouter-free-tier dispatch. Read this before implementing any `MED-*` task or touching `RCI-01`/`RCI-02`.

## Topology (unchanged from ADR-0012's core decision)

One dispatcher (`claude_task_runner.js`'s local loop, or `windows_agent.js`'s claim-execute cycle) runs exactly one child CLI process at a time. Two executors never hold the working tree simultaneously. "Multi-executor" describes which binary/flags a given task uses, not concurrent processes.

## Task-model schema (final form)

```yaml
executor: claude            # claude | codex | auto | openrouter_free
preferred_model: null       # optional capability hint (architecture/015, models/MODEL_SELECTION_POLICY.md)
fallback_executor: null     # optional; same fail-closed rule applies once resolved
context_budget: null        # optional int, informational only (matches token_budget's precedent)
model_tier: null            # optional: "free" | "standard" | "strong" -- used by chooseExecutor() when executor: "auto"
review_executor: null       # optional: executor that must independently review before "done" (ADR-0010 principle 5)
```

All fields optional; a task with none of them behaves exactly as today (`executor` defaults to `"claude"` when absent, matching every existing `DA-*`/`SR-*`/`RUNNER-*` task unchanged).

**Fail-closed rule (extends architecture/015):** `execute()` refuses (status `"failed"`, explicit `result.runner_error`, no process spawned) any task whose `executor` is present and is not one of `claude`, `auto`, or — once each is actually implemented — `codex`/`openrouter_free`. Until `MED-02` ships, `codex` is rejected exactly like today; until `MED-03` ships, `openrouter_free` is rejected the same way. An implemented-but-currently-rate-limited executor is a different, already-existing state (`waiting_for_limit`), not a fail-closed rejection.

## The three tiers (routing guidance, made explicit and disclosed per ADR-0010 principle 4)

| Tier | `model_tier` | Executor | Work shape | Repo access |
|---|---|---|---|---|
| 0 | `free` | `openrouter_free` | Reading logs/status, mechanical doc edits, summaries | `docs/`, `product_bible/`, `CHANGELOG.md`, read-only elsewhere. Never `ego_os/`, `automation/`, tests. |
| 1 | `standard` | `claude` or `codex` | Ordinary feature work, clear acceptance criteria | Same as today (`allowed_paths` per task) |
| 2 | `strong` | `claude`/`codex` + `review_executor` set to the other | Architecture, cross-cutting, risky changes | Same as today; a second, independent stage reviews before `done` |

This table extends (does not duplicate) the capability-routing table in `architecture/016_USAGE_OPTIMIZATION_POLICY.md`; that table's three rows map onto tiers 0/1/2 here. A task author sets `model_tier`/`executor` explicitly based on this table — there is no automatic complexity classifier.

## `chooseExecutor(task, runnerState)` — the one authorized automatic behavior

A pure, unit-tested function (`automation/executor_routing.js`, `MED-04`):

1. If `task.executor` is `claude`, `codex`, or `openrouter_free` explicitly — use it (subject to the fail-closed/implemented check above).
2. If `task.executor` is `auto` (or absent with `model_tier` set) — resolve tier from `model_tier`; tier 0 → `openrouter_free`; tier 2 → whichever of `claude`/`codex` is not currently `waiting_for_limit`/`waiting_for_auth` (ties broken by a fixed, documented default, e.g. `claude` first), with `review_executor` set to the other; tier 1 → same limit-aware choice, no review stage.
3. **Limit-aware fallback**: if the resolved executor is currently `waiting_for_limit`/`waiting_for_auth` (per that executor's own recorded runner/agent state) and the *other* real executor is not, use the other one instead — a concrete, logged substitution (`result.sessions[].executor_fallback_reason`), never a silent guess. If both are unavailable, the task itself moves to `waiting_for_limit`/`waiting_for_auth` exactly as today.

This function never invents a third option, never silently downgrades tier-2 work to skip review to save tokens (ADR-0010 principle 5 overrides principle 1-style cost savings for anything tier 2), and never picks `openrouter_free` for a task whose `allowed_paths` reach outside its permitted scope (a scope violation is a task-authoring error, caught by the same validation `RCI-02` already establishes for `executor` fail-closed handling).

## Cross-executor independent review (tier 2)

Reuses the existing TOKEN-EFFICIENCY-001 handoff mechanism unchanged: the implementer stage writes its normal handoff file; if `review_executor` is set, the next stage spawns *that* executor instead of continuing with the implementer's, with a prompt built from the handoff plus an explicit "review this diff, approve or request changes" instruction. A review that requests changes returns the task to a further implementer stage (same executor as tier-1 continuation logic already handles); only an explicit review approval allows `status: "done"`.

## Executor-aware claim (`control_server.js`, `MED-06`)

`handleAgentClaim` passes the calling agent's own registered `executor` (already stored per-agent in `summarizeAgents()`'s backing store, currently display-only) into `nextTask()`. A task with an explicit `executor` is only handed to an agent registered under that same executor; a task with `executor: "auto"` (or absent) may be claimed by any registered agent. This makes the existing agent registry load-bearing instead of decorative, with no new state added.

## Vertical task sequence

`RCI-01 → RCI-02 → {MED-01} → MED-02 → {MED-03, MED-04} → MED-05 → MED-06 → MED-07`. `MED-01` (Codex CLI recon) has no dependency and may run immediately; `MED-03` (OpenRouter free-tier executor) depends only on `RCI-02`, not on Codex being ready. See `tasks/queue/MED-*.yaml`.
