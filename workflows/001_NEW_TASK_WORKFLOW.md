# New Task Workflow

1. User creates task.
2. Orchestrator creates interpretation.
3. Clarification Check — if a critical, result/budget/rights/risk-changing fact is missing, the Orchestrator asks only that question and waits for the Owner's answer before continuing (`architecture/002_TASK_LIFECYCLE.md`, `ADR-0014`); a safely-assumable gap is never asked about.
4. Orchestrator estimates required capabilities.
5. Employee Registry is checked.
6. Missing employee is created/proposed if needed (Owner approval creates an EmployeeProvisioningTask, not an Employee directly — `ADR-0015`).
7. Plan is created and persisted (`ProductTaskPlan`, `ADR-0014`).
8. The Orchestrator itself tracks execution status today (`pm` is a **planned**, not yet runtime-active role — `company/EMPLOYEE_REGISTRY.md`).
9. Employees produce outputs.
10. Token/cost usage is recorded automatically by the system for every step (`architecture/004_COST_AND_TOKEN_ACCOUNTING.md`) — this does not require CFO to be the staffed specialist; CFO's own role is analysis/advisory, not mandatory bookkeeping (`ADR-0016`).
11. QA reviews the result — a real gate: PASS delivers, one REVISE gets exactly one automatic retry, a second REVISE (or a malformed verdict) requires an explicit Owner decision (`needs_owner_review`, `ADR-0014`).
12. Final response and report are delivered.
13. Memory is updated.
