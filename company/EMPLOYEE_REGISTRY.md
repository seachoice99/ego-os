# Employee Registry

## Core employees for MVP

| ID | Title | Department | Purpose | Status |
|---|---|---|---|---|
| orchestrator | Orchestrator | Executive | Understand task, plan, staff, coordinate | implemented (`company/employees/core/orchestrator.yaml`) |
| pm | Project Manager | Operations | Track execution, statuses, dependencies | **planned** — no `company/employees/core/pm.yaml` exists; not runtime-active; never staffed on a ProductTask today (`architecture/018` C-08, `RELEASE_NOTES_v0.2.md`) |
| cfo | CFO | Finance | Track tokens, costs, budget, model efficiency | implemented (`company/employees/core/cfo.yaml`) — an ordinary capability-matched specialist, not staffed on every task; automatic accounting does not depend on it (`architecture/004`) |
| qa | QA Reviewer | Quality | Check result before delivery | implemented (`company/employees/core/qa.yaml`) |
| researcher | Researcher | Research | Search, analyze, summarize evidence | implemented (`company/employees/core/researcher.yaml`) |
| writer | Writer | Content | Create structured texts, emails, proposals | implemented (`company/employees/core/writer.yaml`) |
| designer | Designer | Creative | Visual concepts, presentation logic, image tasks | implemented (`company/employees/core/designer.yaml`) |
| coder | Coder | Engineering | Code, technical implementation, repo work | implemented (`company/employees/core/coder.yaml`) |

## Registry rule

Employees are versioned definitions. Updating an employee should not break old task history.

A row with Status `planned` is documentation of intent only — it must never be read as "this employee already tracks/executes work at runtime." `pm` is activated (a real YAML added, registered, and wired into `ego_os/lifecycle.py`'s staffing) only once real Subtasks, dependencies, and multi-Employee coordination exist to actually track (`ADR-0014`/`architecture/001_CORE_ENTITIES.md`).
