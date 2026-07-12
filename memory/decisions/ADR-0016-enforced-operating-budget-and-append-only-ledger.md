# ADR-0016: Enforced operating budget (USD 15.00) and an append-only budget ledger

## Status

Accepted by Owner on 2026-07-13, as part of the 2026-07-13 architecture-correction pass. Resolves `architecture/018_ARCHITECTURE_CONTRADICTION_AUDIT_2026-07.md`'s C-13, and the fail-closed half of C-12.

Does not reverse ADR-0003 (cost accounting is core) — it makes accounting *enforced*, not just recorded. Does not change `mandate.starting_capital`, which remains a separate, Owner-set business-mandate figure (see Context).

## Context

Discovery found no persisted budget ceiling anywhere in this codebase: `ego_os/store.py` has no budget/ledger table; `ego_os/model_provider.py`'s `complete()` makes zero budget check before a paid call; `store.get_total_cost()` is a read-only derived sum with no enforcement power; an unmapped capability or unpriced model currently raises an unhandled `KeyError` rather than a deliberate fail-closed decision. `finance/FINANCE_SYSTEM.md` and `architecture/004_COST_AND_TOKEN_ACCOUNTING.md` describe CFO's monitoring/reporting role but never name a concrete budget figure. Cost accounting (ADR-0003) has therefore been *recorded* but never *enforced* — a real gap the Owner is closing now with a concrete number.

**`mandate.starting_capital` is a different concept, not superseded or touched by this ADR.** It is the Owner-set business mandate parameter from `ego_os/store.py`'s `mandate` table (free-form, no fixed value defined by any prior ADR) — a statement about the simulated company's capital position. The budget this ADR defines is the real, spendable ceiling on **AI/model/tool operating cost** — a completely different quantity, and conflating them was itself one of the risks the Owner explicitly flagged.

## Decision

### The current global operating budget

| Field | Value |
|---|---|
| Currency | USD |
| Approved amount | 15.00 |
| Scope | Total AI/model/tool operating budget for Ego OS, company-wide, until the next Owner decision |
| Authority | Owner |
| Status | Active |
| Effective | 2026-07-13 |
| Replenishment | Only by a new, explicit Owner decision (a new `budget_approved` ledger event) |

This is the **total** available budget, not a per-task allowance — no single ProductTask is entitled to spend all of it. Each ProductTask receives its own sub-limit reserved out of the global balance (set in its persisted Plan, per ADR-0014).

### Append-only ledger

A new `budget_ledger_events` table (additive `CREATE TABLE IF NOT EXISTS`, no change to any existing table) records every budget-affecting fact as an immutable, timestamped event. Event types: `budget_approved`, `task_reserved`, `spend_recorded`, `reservation_released`, `adjustment_approved`, `budget_exhausted`. Nothing is ever updated or deleted from this table — the current available balance is always a computed sum over it, never a mutable counter.

### Representation

Money is stored as **integer minor units** (cents), never a binary `FLOAT`/`REAL` column, in every new budget-related field. Python-side arithmetic uses `Decimal` or integer cents exclusively when converting to/from a human-readable dollar amount — floating-point is never the authoritative representation for anything money-shaped introduced by this ADR (existing `reports.cost`/`employee_proposals.cost` `REAL` columns are unchanged by this ADR — a separate, later migration would be needed to convert those, and is not in this pass's scope).

### Enforcement sequence (binding on `ego_os/model_provider.py` and any future paid-call site)

Before any paid model/tool call:
1. Determine a conservative maximum cost estimate (a reservation), never optimistic.
2. Check the ProductTask's own remaining sub-limit.
3. Check the remaining global balance.
4. Record a `task_reserved` ledger event for the reservation amount.
5. Make the call.
6. Record a `spend_recorded` event for the actual measured cost.
7. Record a `reservation_released` event for the unused portion (reservation minus actual spend) — the reserved-but-unspent amount is never silently forgotten.

If either the task limit or the global limit would be exceeded by the reservation in step 1, the call does not happen — the ProductTask moves to a `waiting_for_owner`-shaped state (per ADR-0014's terminal/needs-review vocabulary: `terminal_reason.category` reflecting budget exhaustion, or a non-terminal pause if the ProductTask lifecycle has a waiting state available) and a `budget_exhausted` event is recorded. **Automatic overspend is never permitted, under any condition.**

### Unknown pricing

If a call's price cannot be determined in advance (an unmapped capability, an unpriced model), the cost is **never treated as zero**. A conservative, Owner-approved ceiling reservation is used if one exists for that situation; if no such ceiling can be determined, the call fails closed (does not happen) and the task moves to the waiting-for-owner state described above — this is the deliberate replacement for today's unhandled `KeyError`.

### Global budget changes

Any change to the global budget figure itself (raising, lowering, or replenishing it) requires a fresh, explicit Owner decision recorded as its own `budget_approved`/`adjustment_approved` ledger event — no code path may adjust the global ceiling on its own.

## Consequences

- `ego_os/store.py` gains a `budget_ledger_events` table and helper functions (`reserve`, `record_spend`, `release_reservation`, `get_available_balance`, etc.), all additive.
- `ego_os/model_provider.py`'s `complete()` gains the reserve→call→record→release sequence above; an unmapped capability/model now fails closed deliberately instead of raising an unhandled `KeyError`.
- `finance/FINANCE_SYSTEM.md` is updated to record the concrete USD 15.00 figure and point at this ADR as its authority.
- No real paid API call is made anywhere during the implementation or testing of this ADR — every test uses a scripted/mocked cost, exactly like the rest of this repository's existing test suite (`ego_os.model_provider.complete` is already replaced by a fake in tests per `tests/conftest.py`).
- A future decision to convert `reports.cost`/`employee_proposals.cost` from `REAL` to an integer-minor-units representation is named here as a known, deliberately deferred follow-up — not silently ignored.
