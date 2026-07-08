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

## Runtime flow

1. User submits goal.
2. Orchestrator creates Task.
3. Orchestrator estimates required capabilities.
4. Employee Registry returns matching employees.
5. Missing capabilities trigger Employee Creation Proposal or automatic employee creation depending on autonomy mode.
6. Task Plan is created.
7. Employees execute assigned subtasks.
8. Every step writes Work Log events.
9. Finance module records usage.
10. QA reviews output.
11. Result and summary are stored in Project Memory.

## Hard rule

Business/product entities must not depend on specific AI vendors. GPT, Claude, Gemini, Veo, Runway, Flux and other providers are replaceable infrastructure.
