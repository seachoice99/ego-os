# System Architecture

## Product-level entities

- Company
- Employee
- Department
- Project
- Task
- Report
- Memory
- Model Provider
- Tool
- Budget

## Definition, Runtime, and Infrastructure

Company, Employee, Department and Project are Definitions — versioned specifications that stay stable regardless of what executes them. Model Provider, Tool and Budget are Infrastructure — replaceable resources a Definition is executed against. Runtime is not a further set of entities; it is the architectural layer where a Definition is actively executed against Infrastructure, producing the operational record (Task, Report, Memory already listed above). A dedicated Runtime architecture — how execution actually happens — is not yet defined and should be written when implementation begins.

## Runtime flow

1. User submits goal.
2. Orchestrator creates Task.
3. Orchestrator estimates required capabilities.
4. Employee Registry returns matching employees.
5. Missing capabilities trigger Employee Creation Proposal or automatic employee creation depending on autonomy mode, always within the bounds of Gate Control for the company's current lifecycle stage (see `architecture/006_AUTONOMOUS_COMPANY_ARCHITECTURE.md`).
6. Task Plan is created.
7. Employees execute assigned subtasks.
8. Every step writes Work Log events.
9. Finance module records usage.
10. QA reviews output.
11. Result and summary are stored in Project Memory.

## Owner Interface Principle

The Owner interacts with a single executive operating layer — the company's central point of coordination — never with individual employees directly. Employees perform work internally and surface results only through reports, task outputs, and the operating layer's own communication back to the Owner.

## Hard rule

Business/product entities must not depend on specific AI vendors. GPT, Claude, Gemini, Veo, Runway, Flux and other providers are replaceable infrastructure.
