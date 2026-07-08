# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

Ego OS is currently a **specification-only repository** ("Genesis / Product architecture" phase per `README.md`). There is no application code, build system, package manifest, or test suite yet — the repo is a set of Markdown/YAML documents defining the product before any implementation begins. There are no build/lint/test commands to run.

When asked to "implement" something here, check first whether the task is actually about writing new spec documents (most likely) versus scaffolding real application code (a significant, distinct undertaking not yet started).

## Core product concept

Ego OS is a personal operating system for running a **digital AI company**, not a chat-with-agents product. The user acts as CEO/Product Owner: sets goals in natural language, approves key decisions, controls budget. The system plans work, staffs it with "digital employees," executes, reports transparently, tracks cost, and persists memory.

The foundational rule (see `memory/decisions/ADR-0001-digital-company-not-chat.md`): chat is only an input method — the product surface is company-style entities (employees, departments, projects, reports, finance), not a conversation thread.

### Core entities (defined in `architecture/001_CORE_ENTITIES.md`)

`Company`, `Employee`, `Department`, `Project`, `Task`, `Report`, `Memory`, `Finance` — plus `Model Provider`, `Tool`, `Budget` at the system level (`architecture/000_SYSTEM_ARCHITECTURE.md`). Business/product entities must never depend on a specific AI vendor — GPT, Claude, Gemini, image/video models, etc. are replaceable infrastructure selected by required capabilities, not hardcoded (see `models/MODEL_SELECTION_POLICY.md`).

### Employees are competence containers, not personalities

Per ADR-0002 and `architecture/005_EMPLOYEE_MODEL.md`: employees have no career growth or RPG-style progression. They are versioned definitions (role, mission, responsibilities, required capabilities, tools, permissions, reporting rules, cost policy) that get updated — new instructions, new models, new tools — rather than "promoted." Old task history must keep referencing the employee version that actually performed the work.

Core employee definitions live in `company/employees/core/*.yaml` (orchestrator, pm, cfo, qa, researcher, writer, designer, coder), indexed in `company/EMPLOYEE_REGISTRY.md`. Each YAML follows a consistent shape: `id, name, title, department, version, mission, responsibilities, required_capabilities, reporting_rules, permissions`. Follow this exact shape when adding or editing an employee definition.

### Task lifecycle

`architecture/002_TASK_LIFECYCLE.md` and `workflows/001_NEW_TASK_WORKFLOW.md` define the flow: Intake → Clarification Check → Planning (Orchestrator) → Staffing (existing employees or new/proposed ones) → Execution (with logged events) → QA → Delivery (with mandatory report) → Memory Update.

### Reporting and cost are first-class, not optional

Every task must produce a report (`tasks/templates/REPORT.md`, `architecture/003_REPORTING_AND_LOGS.md`) covering employees involved, timeline, decisions, models/tools used, token usage, cost, outputs, and open questions. Cost/token accounting (`architecture/004_COST_AND_TOKEN_ACCOUNTING.md`, `finance/FINANCE_SYSTEM.md`, ADR-0003) is tracked at task/employee/project/company levels — this is core functionality, not an add-on, per explicit ADR.

Logs should expose *operational* reasoning (what was done, why, what changed) — never raw hidden chain-of-thought (`architecture/003_REPORTING_AND_LOGS.md`).

## Repository layout

```text
product_bible/      Product definition and principles (Russian) — vision, principles, user journey, MVP scope
architecture/        Core architecture and lifecycle docs (English) — system architecture, entities, task lifecycle, reporting, cost accounting, employee model
company/             Company description, employee registry, and employee YAML definitions
projects/            Project contexts (one folder per project, e.g. projects/ego-os/PROJECT.md)
tasks/templates/     Templates for tasks, reports, and employee-creation proposals
memory/decisions/    Architecture Decision Records (ADR-NNNN-slug.md)
finance/             Token and cost accounting system description
models/              Model selection policy (capability-based, not vendor-based)
workflows/           Operating workflows (new task, employee update)
ui/                  Interface concept (screens, product metaphor)
docs/                Legacy notes from the first version of the project (superseded by product_bible/ and architecture/ — treat as historical context, not current spec)
```

## Conventions to follow when editing these docs

- **Language split**: `product_bible/`, `docs/`, and `company/COMPANY.md` internal-role notes are written in Russian; `architecture/`, `company/employees/*.yaml`, `workflows/`, ADRs, and templates are written in English. Match the existing language of whichever file you're editing rather than translating wholesale.
- **ADRs** live in `memory/decisions/` as `ADR-NNNN-kebab-case-title.md` with `Status / Context / Decision / Consequences` sections. Add a new ADR (don't edit an accepted one) when reversing or superseding a prior architectural decision.
- **New employee definitions** go in `company/employees/core/<id>.yaml`, must be registered in `company/EMPLOYEE_REGISTRY.md`, and must use `required_capabilities` rather than naming a specific model/vendor (per `models/MODEL_SELECTION_POLICY.md`).
- **`docs/`** is explicitly legacy (per `README.md`) — prefer updating `product_bible/` and `architecture/` for current product/architecture decisions rather than editing `docs/`.
