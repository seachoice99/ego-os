# Ego OS v0.2.0 — "Useful Company"

Released 2026-07-08. Tag: `v0.2.0`. Live at `https://os.fiveseven.ru`.

v0.2's objective, per `IMPLEMENTATION_ROADMAP.md`, was for the company to take on a meaningfully wide variety of real work, not just text drafting and review. All seven planned capabilities shipped and were verified end to end against real production tasks, not simulated ones.

## Capabilities delivered

| Capability | Gated on | Real output |
|---|---|---|
| Tool Framework | — (prerequisite) | name-checked tool registry in `ego_os/tools.py` |
| Repository Access | Coder's `read_repository`/`write_repository` | real file reads/writes in this repo |
| Web Research | Researcher's `use_web` | live Tavily search results with real URLs |
| Document Generation | Writer's `create_documents` | real `.md`/`.docx`/`.pdf` files |
| Spreadsheet Generation/Editing | CFO's `create_finance_reports` | real `.xlsx` files, typed cells, bold header |
| Structured Artifacts | — (generalization) | every artifact typed (`text`/`document`/`spreadsheet`), one unified render path |
| Multi-Project Operations | — | real Project creation, per-task assignment, verified memory isolation |

Also shipped this cycle: first production deployment (Ubuntu VPS, systemd, nginx + Let's Encrypt), and a UX pass (submit-button loading state, professional Markdown rendering) just ahead of the capability work.

## Bugs found and fixed

All five were found through live verification (a real task against a real model, not a unit test in isolation) and fixed at the root cause rather than patched around:

1. **Date blindness.** Specialists and QA had no notion of today's real date, so genuinely current web-search results got misjudged as "future." Fixed by stating the real date in every prompt.
2. **fpdf2 cursor bug.** `multi_cell` left the cursor at the right margin instead of the next line, crashing any second heading/paragraph in a generated PDF. Fixed with explicit `new_x`/`new_y`.
3. **PDF font encoding.** The PDF core font can't render em-dashes, curly quotes, or bullets that LLM output routinely contains. Fixed with a Latin-1 sanitization step.
4. **TOOL_REQUEST parser fragility.** A strict single-line `json.loads` broke on multi-line file content or trailing text after the JSON, silently failing the tool call while QA passed the result anyway (a false PASS). Fixed with a regex-located marker + `json.JSONDecoder().raw_decode()`.
5. **systemd restart race.** Checking service health immediately after `systemctl restart` sometimes hit the app before it finished booting. Not a code bug — documented as an operational timing note, not "fixed" in code.

## Known limitations

- **QA can't see tool execution.** It only reasons over the drafted text, not the timeline. This produced both a false PASS (a tool silently failed but QA approved the apology text) and a false REVISE (QA doubted a tool call that actually succeeded). Not fixed this cycle — would require exposing tool-execution evidence to QA's prompt.
- **Staffing is judgment-based, not guaranteed-correct.** Orchestrator picks a specialist by LLM judgment over the request text. A domain-ambiguous request (e.g., "generate an Excel file" with no financial framing) can be routed to an employee without the right tool (e.g., Coder instead of CFO), who then falls back to a tool it does have permission for. Clear phrasing routes correctly; this is a known characteristic of the current design, not a bug.
- **One tool call per specialist turn.** Deliberately bounded (matches the one-revision QA cap) — a specialist cannot chain multiple tool calls in a single execution.
- **"Editing" is overwrite, not incremental.** Both `create_document` and `create_spreadsheet` regenerate the whole file from scratch on a repeat call; there's no diff/patch operation.
- **Coder's `run_local_commands` permission has no backing tool.** It's declared in `coder.yaml` but nothing in the registry lets Coder actually execute anything yet — only read/write files.
- **Single SQLite database, no concurrency handling.** Fine for the current single-Owner usage; would need attention before multi-user or high-concurrency use.
- **No automated backups.** Manual `sqlite3 .backup` procedure is documented in `DEPLOYMENT.md`; nothing scheduled yet.

## Technical debt

- **No automated test suite.** All verification this cycle was live-task-based (real model calls against a running server), not unit/integration tests. Fast for catching real behavioral bugs, but nothing guards against regression automatically.
- **Missing `pm.yaml`.** `company/EMPLOYEE_REGISTRY.md` references a PM role with no corresponding employee definition — a pre-existing gap, not introduced this cycle.
- **Manually maintained pricing table.** `model_provider._PRICE_PER_TOKEN` needs a manual update if OpenRouter's pricing changes.
- **Capability-to-model mapping is unexercised beyond one model.** Every capability currently maps to the same model (`anthropic/claude-haiku-4.5`); the abstraction is real but hasn't yet been proven with a genuinely different model for a different capability.
- **Command/Dashboard still one combined page.** Explicitly deferred to v0.3 per the roadmap, not an oversight.

## Metrics

- **Capabilities shipped:** 7/7 planned for v0.2.
- **Commits this cycle:** 15 (since the v0.1 roadmap commit `d7b69b6`), 30 total in repo history.
- **Files changed this cycle:** 13 changed, +789/-75 lines (net, after reverted experiments).
- **`ego_os/` application code:** 7 Python files, ~1,006 lines.
- **Employees:** 7 (Orchestrator, Writer, Researcher, Coder, CFO, QA, Designer — Designer not yet wired into staffing).
- **Tools registered:** 5 (`read_repository_file`, `write_repository_file`, `web_search`, `create_document`, `create_spreadsheet`).
- **Real bugs found and fixed during verification:** 5.
- **Production spend to date:** $0.026 (OpenRouter, `anthropic/claude-haiku-4.5`, live dashboard figure at release time).
- **Repository size:** 55 tracked files.
