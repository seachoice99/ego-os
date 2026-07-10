# Ego OS

Ego OS is a personal operating system for managing a digital AI company.

The user sets goals in natural language. Ego OS plans the work, selects digital employees, creates missing roles when needed, tracks execution, reports what happened, counts tokens and cost, stores results and updates project memory.

## Core idea

Ego OS is not a chat with agents. It is a company interface for AI work.

## Core entities

- Company
- Employee
- Department
- Project
- Task
- Report
- Memory
- Finance

## Current phase

Working software, live in production. `ego_os/` is a FastAPI + Jinja2 + SQLite application implementing the documented Task Lifecycle end to end against a real model provider (OpenRouter): Owner authentication, a tool framework (repository access, web research, document/spreadsheet/presentation-website generation), a background task worker, capability-gap handling, and full cost/execution-event accounting. See `IMPLEMENTATION_ROADMAP.md` for what's shipped per version and `CHANGELOG.md` for the detailed history.

The `product_bible/`, `architecture/`, and `docs/` folders remain the source of truth for product vision, principles, and architecture that implementation is built against — this is still documentation-first in the sense that a decision is written down before it's built, not that no code exists yet.

## Running it

```
pip install -r requirements-dev.txt   # includes pytest; requirements.txt alone is enough for production
cp .env.example .env                  # fill in OPENROUTER_API_KEY, OWNER_USERNAME/PASSWORD, etc.
uvicorn ego_os.main:app --reload
pytest                                # full test suite -- no real API calls, no real DB touched
```

See `DEPLOYMENT.md` for the production setup (systemd + nginx + Let's Encrypt) and `CLAUDE.md` for repository conventions.

## Repository structure

```text
ego_os/             The application: FastAPI routes, Task Lifecycle, Tool Framework, worker, store
tests/              pytest suite -- auth, CSRF, uploads, worker/task-states, execution events, etc.
company/            Company description and employee YAML definitions
product_bible/      Product definition and principles
architecture/       Core architecture and lifecycle docs
projects/           Project contexts
tasks/templates/    Task and report templates
memory/decisions/   Architecture Decision Records
finance/            Token and cost accounting
models/             Model selection policy
workflows/          Operating workflows
ui/                 Interface concepts
docs/               Legacy notes from the first version
```
