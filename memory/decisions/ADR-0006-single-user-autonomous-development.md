# ADR-0006: Single-user autonomous development loop

## Status

Accepted by Owner on 2026-07-10.

## Context

Ego OS currently has one user. Requiring a branch, pull request, and manual approval for every small release slows validation more than it reduces present product risk. Code releases are reversible, while some external and data effects are not.

## Decision

A trusted local runner may give Claude Code broad authority to take one repository-queued task at a time, edit task-scoped files, test, commit, push directly to `main`, deploy Ego OS, and verify production.

The loop stops on dirty or divergent Git state, failed tests, failed push, failed deploy, failed health check, or incomplete task reporting. Only one runner may operate at once.

Destructive data operations, irreversible migrations, payments, secrets, external publication, and infrastructure outside Ego OS always require recorded Owner approval. Community or otherwise untrusted prompts cannot enter the executable queue without review.

## Consequences

- Small changes can reach the sole user much faster.
- `main` and production may receive a defective change before human review.
- Tests, logs, health checks, stop-on-failure, and rollback become essential.
- Review this decision before adding users, valuable production data, payments, or broader autonomous access.
