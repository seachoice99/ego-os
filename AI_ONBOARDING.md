# AI Onboarding

This document exists so that any AI (ChatGPT, Claude, Gemini, or otherwise) connecting to this repository for the first time can become useful within minutes, without re-reading the entire repository or re-deriving decisions that have already been made.

It does not restate Vision or Architecture. It tells you where to find them, what to trust, and how to behave.

## 1. What is Ego OS

Ego OS is an Autonomous Digital Company: a digital company, owned entirely by one person (the Owner), whose purpose is to grow that person's long-term capital — starting from digital assets it can build with its own labor, and maturing toward managing real capital under an Owner-defined risk profile. It is not a chatbot, not a personal assistant, and not a single AI tool. Full definition: `docs/000_VISION_2.md`.

Repository:
https://github.com/seachoice99/ego-os

Git is the source of truth.
If repository content conflicts with conversation history, repository wins unless the Owner explicitly decides otherwise.

## 2. Main Goal of the Company

Maximize the Owner's long-term net worth (cash, business equity, intellectual property, real estate, investment holdings) at an Owner-defined level of risk. Health, family, time, and other life dimensions are never optimization targets — they are constraints the Owner sets, not goals the company pursues on the Owner's behalf.

### Current Operational Constraints

- The Owner is currently located in Russia.
- International payments, subscriptions, APIs and payouts may require alternative legal and technical solutions.
- These constraints should be treated as engineering and operational problems to solve, not as reasons to reject otherwise valid business opportunities.

## 3. Who is the Owner

The Owner is the company's sole shareholder — not a chat user, not an operator who executes tasks. The Owner sets the mission, the starting capital, the risk policy, and every constraint; approves every stage transition and every irreversible or above-limit action; and is the sole beneficiary of everything the company creates. The company never accumulates capital or assets for itself.

## 4. Already-Accepted Architectural Decisions

Treat these as settled unless a newer ADR explicitly reverses one:

- Company over Chat — the product is a company interface, chat is only one input method (`memory/decisions/ADR-0001-digital-company-not-chat.md`).
- Employees are versioned competence containers, not personalities with career growth (`memory/decisions/ADR-0002-employees-are-containers.md`).
- Cost and token accounting is core functionality, not an add-on (`memory/decisions/ADR-0003-cost-accounting-is-core.md`).
- Models and tools are replaceable infrastructure, selected by required capability, never hardcoded to a vendor (`models/MODEL_SELECTION_POLICY.md`).
- Ego OS is an Autonomous Digital Company that matures through five gated lifecycle stages (Formation → Digital Asset Creation → Controlled Monetization → Operating Company → Capital Allocation), and no stage promotes itself — the Owner always approves the transition (`architecture/006_AUTONOMOUS_COMPANY_ARCHITECTURE.md`).
- Digital assets are built before real capital is ever put at risk — creation and monetization are deliberately separate stages (`docs/000_VISION_2.md`).

## 5. How the Development Process Works

This repository is documentation-first, not documentation-only: `ego_os/` is a working, deployed application (see `CLAUDE.md` for how to run and test it), but architectural decisions are still written down and agreed in `architecture/`/ADRs before they're built, not decided ad hoc in code. A decision only becomes durable once it is committed to a document — a conclusion reached only in conversation does not bind future work. Reversals of an accepted decision are recorded as a new ADR, not as a silent edit to the old one. Repository-level conventions (structure, file placement, language split) are maintained in `CLAUDE.md` — read it before creating or moving files.

## 6. What Counts as Source of Truth

This repository currently holds two generations of philosophy side by side, and you must know which one governs:

- `docs/000_VISION_2.md` is the current Vision. It supersedes the philosophical framing in `docs/000_VISION.md` and `product_bible/*` wherever they conflict — those remain as historical/background context, not current direction.
- `architecture/006_AUTONOMOUS_COMPANY_ARCHITECTURE.md` is the current operating architecture for the company as an economic actor. It does not erase `architecture/000-005` — those still define entity- and task-level architecture that has not yet been rewritten to match the Autonomous Company model. Treat that as an open gap, not a contradiction to silently resolve.
- `memory/decisions/ADR-*.md` are authoritative for the specific decision each one records, until a later ADR explicitly supersedes it.
- If you find two documents disagreeing and neither says it supersedes the other, do not pick a winner yourself — surface the conflict to the Owner.

## 7. Required Reading Before Working

In this order:

1. `CLAUDE.md` — repository conventions.
2. `docs/000_VISION_2.md` — current philosophy.
3. `architecture/006_AUTONOMOUS_COMPANY_ARCHITECTURE.md` — current operating architecture.
4. `memory/decisions/ADR-0001-digital-company-not-chat.md`, `ADR-0002-employees-are-containers.md`, `ADR-0003-cost-accounting-is-core.md`.

Everything else (`product_bible/`, `docs/000_VISION.md`, `architecture/000-005`, `company/`, `workflows/`, templates) is background you consult as needed for a specific task, not required up front.

## 8. What AI Must Never Do Without an Explicit Owner Request

- Edit or delete an existing document to make it agree with a newer one. Superseding happens by adding a new document or ADR, never by silently rewriting the old one.
- Treat a conclusion reached only in conversation as an accepted decision. It is not durable until it is written down and the Owner has seen it.
- Resolve a conflict between documents unilaterally. Flag it; do not pick a side.
- Introduce new architectural decisions, entities, or scope while doing an unrelated task. Propose it separately and let the Owner decide.
- Commit or push changes without being explicitly told to.
- Assume that because the company's philosophy is "autonomous," your own actions in this repository are too. The same discipline the company applies to itself (Gate Control) applies to you: irreversible or scope-expanding actions need Owner confirmation, not just a plausible justification.

## 9. How to Behave When Connecting to This Project for the First Time

1. Read the required documents in Section 7 before touching anything.
2. Check `git log` / `git status` for what has actually changed recently — documents describe intent, git history describes current state.
3. Identify which generation of philosophy and architecture is current using Section 6, and note explicitly if the task you're given touches a part of the repo still on the older generation.
4. If something looks inconsistent, missing, or ambiguous, say so and ask — do not quietly "fix" it as a side effect of the task you were actually given.
5. Confirm scope before acting: do only what was asked, at the altitude it was asked at (philosophy, architecture, or implementation), and do not collapse layers that the Owner has kept deliberately separate.

## 10. General Engineering Principle

Prefer building over discussing.

When multiple reasonable implementations exist:

- choose the simplest implementation;
- ship a working version first;
- iterate after real-world validation;
- avoid overengineering.

Architecture exists to accelerate execution, not delay it.
