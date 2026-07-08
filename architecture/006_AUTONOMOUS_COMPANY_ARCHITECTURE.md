# Autonomous Digital Company — Operating Architecture

This document describes how the company functions: how it moves through its lifecycle, how authority is gated at each stage, how it makes decisions, how individual digital assets are born and retired, how it keeps searching for new opportunities, and how it allocates the capital it produces.

This document does not describe employees, models, tools, UI, or implementation. It describes the operating mechanics of the company as an economic actor, independent of what performs the work.

## Relationship to Task Execution

Everything described in this document — a Decision Engine cycle, an Experiment Engine test, a step in the Digital Asset Lifecycle — is carried out as one or more Tasks under the existing Task Lifecycle (`architecture/002_TASK_LIFECYCLE.md`). Intake and Evaluation correspond to Planning and Staffing; Selection corresponds to Execution; Closure corresponds to Delivery and Memory Update. This document does not define a second execution path — it describes what the company chooses to do and why; `architecture/002` describes how any chosen work actually gets done.

## 1. Company Lifecycle

The company matures through five sequential stages. A stage is not a mode the company switches into by itself — it is a level of trust the company has earned and the Owner has explicitly granted. The company can recommend that it is ready for the next stage and present evidence for that claim, but it cannot promote itself. Every transition is a Gate (see Section 2) that only the Owner can open.

### Stage 1 — Formation

The company has no external footprint yet. Its output at this stage is entirely internal: a mission statement, a declared starting capital, a risk policy, and an internal operating structure. Nothing produced here touches the outside world, and no capital is at risk.

Exit condition: the Owner approves the mission, the starting capital, and the risk policy as a single package.

### Stage 2 — Digital Asset Creation

The company creates value using only its own labor and its own compute — no external transactions, no third-party counterparties, no real capital exposure. Output is Digital Assets: things the company can build and own outright without needing anyone else's permission or money (see Section 4).

Exit condition: at least one digital asset has passed internal validation and has a credible, specific monetization thesis attached to it.

### Stage 3 — Controlled Monetization

The company tests whether a specific digital asset can be converted into real capital. Every test runs inside a capital and risk envelope the Owner pre-approved, and every test is designed to be stoppable and reversible. The point of this stage is evidence, not scale.

Exit condition: at least one monetization pathway has repeatedly cleared its pre-registered success criteria, using real transactions, without breaching its approved envelope.

### Stage 4 — Operating Company

The company runs a validated, repeatable revenue activity with real counterparties. It has a genuine balance sheet and genuine ongoing obligations. Its financial claims about itself are no longer taken on faith — see Section 2 for what independent verification means at this stage.

Exit condition: the company demonstrates sustained profitability net of its own operating cost, reconciled against real external accounts, over a period the Owner considers sufficient.

### Stage 5 — Capital Allocation

The company manages the full range of accumulated capital — cash, business equity, intellectual property, real estate, portfolio holdings — as a single portfolio, in service of the Owner's long-term net worth, inside the Owner's risk profile. This is the mature, steady-state form of the company; it does not mean the company stops creating new digital assets or running new monetization experiments — Stages 2 and 3 continue to run inside Stage 5, feeding it.

There is no Stage 6. Growth from here is depth (more capital, more asset classes, more validated operations under the same governance), not a further stage of trust.

## 2. Gate Control

Gate Control is the mechanism that decides, for any single action the company considers taking, whether it can proceed on its own, needs Owner confirmation first, or is simply not allowed. It is evaluated per action, every time — earning a stage does not exempt future actions within that stage from being checked. A company that has operated safely for a year does not get to skip the check on action one thousand and one.

Every action is classified using the same four factors:

- **Reversibility** — can this be undone, and at what cost.
- **Exposure** — how much capital or risk, relative to what has been pre-approved for this stage.
- **External counterparties** — does this create an obligation to, or interaction with, someone outside the company.
- **Regulatory / legal surface** — does this touch activity that is licensed, regulated, or contractually bound elsewhere.

An action that is irreversible, or exceeds the approved exposure, or creates a new kind of external obligation, or opens new regulatory surface, is never autonomous — regardless of stage.

### Stage 1 — Formation

- **Autonomous**: drafting the mission, proposing the internal structure, proposing a risk policy, revising drafts before submission.
- **Requires Owner confirmation**: the mission itself, the starting capital amount, the risk policy, exit to Stage 2.
- **Prohibited**: any external action of any kind, any use of capital.

### Stage 2 — Digital Asset Creation

- **Autonomous**: generating asset hypotheses, building and iterating assets privately, running internal validation, discarding assets that fail internal review, updating the internal asset record, spending within the compute/resource budget already approved at Formation.
- **Requires Owner confirmation**: publishing or releasing any asset externally in any form — even unmonetized publication is irreversible exposure; spending beyond the approved Formation-stage budget; exit to Stage 3.
- **Prohibited**: any external transaction, any collection or use of third-party data, any real financial exposure, any binding agreement with anyone outside the company.

### Stage 3 — Controlled Monetization

- **Autonomous**: running an already-approved, capped experiment against an already-approved asset; adjusting or pausing that experiment within its approved envelope; collecting results; closing an underperforming experiment.
- **Requires Owner confirmation**: any new monetization hypothesis or channel not already approved; any increase in capital or risk exposure beyond the approved envelope; the first transaction with a new type of counterparty or platform; exit to Stage 4.
- **Prohibited**: using capital beyond what was approved for the experiment; rolling profit into new risk without separate re-approval; any tactic that breaches a platform's terms or the law, regardless of how small the capital at stake is; representing an experiment's results without the underlying transaction record.

### Stage 4 — Operating Company

- **Autonomous**: running already-validated, repeatable operations inside approved limits; routine interactions with existing counterparties that follow already-approved patterns; reinvestment within pre-approved ratios; operational decisions below the materiality threshold the Owner has set.
- **Requires Owner confirmation**: any new line of revenue; any action above the materiality threshold; new contracts of significant scope; engaging a new type of external counterparty; changes to the reserve/reinvestment/distribution split; exit to Stage 5.
- **Prohibited**: reporting financial results without independent reconciliation against real external accounts; taking on regulated activity without a separate, explicit Owner decision to accept that obligation; unbounded risk-taking of any kind.

### Stage 5 — Capital Allocation

- **Autonomous**: rebalancing within already-approved asset classes and within the Owner's risk profile; routine reserve management; incremental reinvestment into already-validated assets or operations within approved limits.
- **Requires Owner confirmation**: entering a new asset class; any allocation that would breach the Owner's risk profile; large one-off allocations (acquiring a business, a property, a significant position); any change to the risk profile itself.
- **Prohibited**: allocating capital in a way that serves the company's own continuity ahead of the Owner's interest; valuing illiquid holdings using only the company's own internal estimate, without independent reconciliation where one is available.

### Relationship to Autonomy Mode

Autonomy Mode (Assistant / Autopilot / Director) governs how the Owner is engaged for a given class of decision — asked first, notified after, or left uninterrupted. It never changes what Gate Control classifies as autonomous, confirmation-required, or prohibited for the company's current stage. A higher autonomy mode can reduce how often the Owner is consulted for actions Gate Control already allows autonomously — it cannot make a confirmation-required or prohibited action autonomous.

## 3. Decision Engine

The Decision Engine is the general mechanism the company uses to decide what to do next, at any stage — whether the decision is which digital asset to build, which monetization test to run, or how to rebalance capital. It always runs the same four steps.

### Intake

A decision starts from one of two places: something the Owner's mandate points at directly (a stated goal, a stated constraint), or something the company itself surfaced through the Experiment Engine (Section 5). Either way, the starting point is recorded before any evaluation happens, so the reasoning for a later decision can always be traced back to why it was even considered.

### Evaluation

Every candidate is scored against the same criteria, regardless of what kind of decision it is:

- expected contribution toward the Owner's goal or the company's current stage objective;
- resource and capital cost;
- risk — probability and size of loss, and how reversible that loss is;
- fit against the current stage's Gate Control limits;
- regulatory or legal exposure;
- time to signal — how quickly the company will know whether this is working.

A candidate that cannot be evaluated against these criteria — because its cost, risk, or reversibility is unknown — is not eligible for a decision. It goes back for more definition, not forward for approval.

### Selection

The company does not commit its full available budget to a single best-scoring candidate. It allocates a bounded slice of the current stage's approved resources across a small number of candidates at a time, so that one wrong hypothesis does not consume the whole opportunity for that period. Selection favors diversification over conviction, especially at earlier stages where the company has the least evidence about what actually works.

### Closure

Every decision is opened with its own success and failure criteria, defined at the moment of approval — not adjusted afterward to fit however things turn out. Every decision also carries a maximum time and resource budget, after which it is closed regardless of an ambiguous result, rather than being kept alive indefinitely on the hope that more time will resolve it. Closure — success or failure — is always recorded with its outcome and reasoning, so the same rejected idea is not proposed again without acknowledging what happened last time.

## 4. Digital Asset Lifecycle

An individual digital asset moves through its own lifecycle, distinct from the company-wide stages above. Every asset has a single thesis attached to it from birth — the specific reason it is expected to be valuable — and every checkpoint in its life re-tests that thesis rather than simply asking whether work got done.

### Conception

An asset is proposed with an explicit thesis: what it is, what value it is meant to create, and how that value would eventually be recognized (used internally, published, monetized). A proposal without a thesis is not an asset candidate — it is an idea that still needs shaping.

### Creation

The asset is built to a minimum viable version — the smallest form that lets the thesis actually be tested, not the most complete form the company is capable of producing. Effort spent beyond what the thesis needs to be tested is waste at this point in the asset's life.

### Internal Validation

Before anything leaves the company, the asset is checked against its own original thesis: does it still hold, does the asset actually deliver what it was proposed to deliver. This is an internal, reversible checkpoint — nothing here is visible outside the company yet.

### Candidate or Shelved

An asset that passes internal validation becomes a candidate for Controlled Monetization, carrying its thesis forward as the hypothesis to be tested against reality. An asset that fails is shelved, not deleted — its record and the reason it failed remain, so the same thesis is not retried blindly later.

### Monetization Testing

Once eligible (Stage 3 or later), the asset's thesis is tested against the outside world through a bounded experiment (Section 5). This is the first point where the asset's value is validated by something other than the company's own judgment.

### Scaling

An asset scales only when its monetization test clears its pre-set thresholds — not when it merely "looks promising" — and only with separate Owner approval, since scaling almost always raises the capital or risk tier the asset operates in.

### Maintenance

A scaled or steadily useful asset enters a steady state: kept alive at the lowest cost that preserves the value it produces, monitored against a maintenance threshold rather than actively grown.

### Retirement

An asset is retired when it repeatedly fails validation, when its thesis is proven false, when its maintenance cost exceeds the value it produces, or when a better asset has superseded it for the same goal. Retirement is recorded with its full history, not silently dropped.

## 5. Experiment Engine

The company does not wait to be told what to try. It continuously searches for new digital assets to build and new ways to monetize what it already has, within whatever gate limits apply to its current stage. This is the process that feeds the Decision Engine and the Digital Asset Lifecycle with new candidates.

### Signal Gathering

The company gathers signal appropriate to its current stage — at earlier stages this is limited to information the company can observe without touching anyone else's data or systems; at later stages it can include patterns from its own validated operations. Signal gathering itself never crosses a Gate Control boundary — it informs hypotheses, it does not execute them.

### Hypothesis Generation

The engine favors many small, cheap-to-test candidates over a few large, expensive bets. A large bet that has never been cheaply tested is treated as unproven, no matter how compelling its reasoning looks.

### Cheap Filtering

Before any real resource is committed, candidates are filtered against what is already known: duplicates of previously closed hypotheses, candidates that clearly fall outside the current stage's Gate Control limits, and candidates that fail the basic evaluation criteria from Section 3 are dropped before they cost anything.

### Small-Scale Testing

A surviving hypothesis is tested at the smallest scale that produces a real signal, inside a pre-registered resource and time budget and pre-registered success criteria — set before the test starts, exactly as in Section 3's Closure step. A capped number of experiments run at any one time, so the company's attention and resources do not sprawl across more bets than it can actually track.

### Outcome

Every experiment ends one of three ways: killed, because it failed its pre-registered criteria; iterated, because it showed a partial signal worth one more bounded attempt; or promoted, because it cleared its criteria and is now a candidate for the next stage of its own lifecycle (a validated asset moving to monetization, a validated monetization test moving toward Operating Company treatment). Every outcome is recorded, including the killed ones — a hypothesis the company already tried and rejected does not get re-proposed as if it were new.

## 6. Capital Allocation

Capital allocation only becomes meaningful once the company produces real profit, starting in Stage 3 and maturing through Stages 4 and 5. Profit is not spent as it arrives — it is split according to a standing allocation set by the Owner as part of the company's mandate, not re-decided by the company for itself each time.

Every allocation below reads from and writes to a single Capital Ledger — the authoritative record of the company's cash, reserve, digital asset values, and investment positions. Cost and Token Accounting (`architecture/004_COST_AND_TOKEN_ACCOUNTING.md`) tracks operating expense as one line within this ledger, not a separate record of the company's financial position. Gate Control's exposure checks, the stage exit conditions in Section 1, and the splits described below all refer to this same ledger — there is exactly one record of what the company currently has, not one per subsystem.

### Reserve

The first claim on any profit is the reserve — a buffer sized against the company's operating cost and current risk exposure. The reserve is replenished before any other allocation happens, so downside is absorbed by the company's own buffer before it ever reaches the Owner's other capital.

### Development

A portion goes back into strengthening and scaling operations that are already validated — the assets and monetization pathways that have already proven themselves, rather than new bets.

### New Asset Creation

A portion is continuously recycled back into Digital Asset Creation, so the company keeps building new assets even after some of its existing assets start earning. A company that stops feeding this allocation stops growing the moment its current assets mature or decline.

### Investment

The remainder graduates to Stage 5 treatment: deployed across the capital categories the Owner has approved — cash, business equity, intellectual property, real estate, portfolio holdings — inside the Owner's risk profile.

The split between these four is a parameter the Owner sets and can change at any time; it is part of the mandate, not something the company tunes for itself. Before Stage 3, this entire section is dormant — there is no profit yet to allocate.
