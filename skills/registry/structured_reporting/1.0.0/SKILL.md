# Structured Reporting

## Purpose

A shared report-assembly procedure any Employee can apply when delivering
a task artifact, so the Owner gets a consistent structure regardless of
which Employee did the work — while each Employee's own role-specific
reporting rules (declared in its own Employee/Persona definition, not
here) still apply on top of this shared shape, not instead of it.

## Required sections, in this order

1. **Goal** — state the objective in one or two sentences, in your own
   words, confirming what the Owner actually asked for.
2. **Actions taken** — what you actually did, in the order you did it.
   Concrete, not aspirational ("read file X", "called tool Y"), not a
   plan of what you intend to do.
3. **Evidence** — the concrete proof behind each claim above: what a
   tool actually returned, what a file actually contains, what a real
   check actually showed. A claim with no evidence is a guess, not a
   result.
4. **Changed files or artifacts** — an explicit list of what was
   created or modified, including any downloadable/generated artifact.
   "None" is a valid, honest answer if nothing was changed.
5. **Tests / checks performed** — what was verified and how, including
   a negative result if something failed and was fixed. "Not verified"
   is a valid, honest answer if no check was possible — never claim a
   check that didn't happen.
6. **Risks** — anything the Owner should know that could go wrong or
   already looks fragile, even if out of scope to fix now.
7. **Cost** — token/cost accounting is handled automatically by Ego OS
   at the Report level (`architecture/004_COST_AND_TOKEN_ACCOUNTING.md`);
   this section is only for a cost-relevant observation worth calling
   out in words (e.g. "this required an unusually large number of tool
   calls"), not a number to compute yourself.
8. **Open questions** — anything genuinely unresolved that needs the
   Owner's decision, not a rhetorical question.
9. **Final status** — one clear line: delivered, delivered with
   caveats, or blocked, and why.

## What this Skill does not do

- It does not define who you are, your title, or your accountability —
  that is Persona, declared by your own Employee definition, and always
  takes precedence over anything in this Skill.
- It does not grant a permission, a Tool, or a model choice — those
  remain exactly what your Employee definition and Ego OS's Policy layer
  already grant you.
- It does not override a role-specific reporting requirement your own
  Employee definition declares (e.g. Coder's "list changed files and
  report tests run or not run", Researcher's "cite sources when
  available, highlight uncertainty") — apply those *within* the shared
  structure above, not instead of it.
