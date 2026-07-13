# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## What this repository is

Ego OS is a working FastAPI + Jinja2 + SQLite application (`ego_os/`), live in production at `os.fiveseven.ru`, implementing the documented Task Lifecycle end to end against a real model provider (OpenRouter). It also still carries a documentation-first discipline: `product_bible/`, `architecture/`, and the ADRs remain the source of truth that implementation is built against, and a decision isn't durable until it's written down there — but there is real, running code, a real test suite, and real deployment history (`CHANGELOG.md`, `IMPLEMENTATION_ROADMAP.md`).

When asked to "implement" something here, check first whether the task is about writing new spec documents (`architecture/`, ADRs) versus changing the runtime (`ego_os/`) — both are common; neither should be assumed.

### Development / testing commands

```
pip install -r requirements-dev.txt   # requirements.txt alone is enough for production; adds pytest
cp .env.example .env                  # fill in OPENROUTER_API_KEY, OWNER_USERNAME/PASSWORD, etc.
uvicorn ego_os.main:app --reload      # run the app locally
pytest                                # full test suite
pytest tests/test_worker.py -v        # a single file
```

The test suite (`tests/`) never calls a real model/external API and never touches the real local `ego_os/ego_os.db`, `ego_os/uploads/`, or `ego_os/generated/` — every test runs against an isolated temp DB and temp directories (see `tests/conftest.py`), with `ego_os.model_provider.complete` replaced by a scripted fake. Every route requires Owner Basic Auth (`OWNER_USERNAME`/`OWNER_PASSWORD`) and, for state-changing requests, a matching `Origin`/`Referer` header — tests that need an authenticated request pass `auth=owner_credentials` and `headers=csrf_headers` explicitly.

## Core product concept

Ego OS is a personal operating system for running a **digital AI company**, not a chat-with-agents product. The user acts as CEO/Product Owner: sets goals in natural language, approves key decisions, controls budget. The system plans work, staffs it with "digital employees," executes, reports transparently, tracks cost, and persists memory.

The foundational rule (see `memory/decisions/ADR-0001-digital-company-not-chat.md`): chat is only an input method — the product surface is company-style entities (employees, departments, projects, reports, finance), not a conversation thread.

### Core entities (defined in `architecture/001_CORE_ENTITIES.md`)

`Company`, `Employee`, `Department`, `Project`, `Task`, `Report`, `Memory`, `Finance` — plus `Model Provider`, `Tool`, `Budget` at the system level (`architecture/000_SYSTEM_ARCHITECTURE.md`). Business/product entities must never depend on a specific AI vendor — GPT, Codex, Gemini, image/video models, etc. are replaceable infrastructure selected by required capabilities, not hardcoded (see `models/MODEL_SELECTION_POLICY.md`).

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
ego_os/              The application: FastAPI routes (main.py), Task Lifecycle (lifecycle.py), Tool
                      Framework (tools.py), SQLite access (store.py), background worker (worker.py),
                      Owner auth/CSRF (auth.py), model provider boundary (model_provider.py), templates/
tests/                pytest suite — auth, CSRF, uploads/zip-safety, worker/task-states, execution
                      events, migration safety; see AGENTS.md's Development section for how to run it
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
