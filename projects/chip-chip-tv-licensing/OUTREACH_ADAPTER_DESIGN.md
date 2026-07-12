# Outreach adapter design: Timeweb SMTP send + reply ingestion

Per ADR-0011 §7-8. This document is a design, not an implementation authorization — no task in this epic's initial queue connects a real credential, sends a real email, or polls a real mailbox. It exists so the eventual real connection (a distinct, later Owner decision) has a reviewed design to implement against, rather than being designed under time pressure later.

## Send path: Timeweb SMTP adapter

```text
cctv_messages (status='approved')
        │
        ▼
SmtpAdapter.send(message)         -- new, isolated module; the ONLY code path
        │                             allowed to open an SMTP connection
        ▼
[MOCK TRANSPORT in this epic]      -- real smtplib.SMTP_SSL(...) call is written
        │                             but never exercised against a real Timeweb
        │                             account until a distinct future task
        ▼
cctv_messages.status = 'sent' | 'failed'
```

- Credentials (`CCTV_SMTP_HOST`, `CCTV_SMTP_PORT`, `CCTV_SMTP_USER`, `CCTV_SMTP_PASSWORD`) are read from server-side environment variables only, matching `.env`'s existing pattern (`OWNER_USERNAME`/`OWNER_PASSWORD`/`OPENROUTER_API_KEY`) — never a database column, never a committed default, never logged.
- `SmtpAdapter` is the *only* module permitted to import `smtplib` (or any SMTP client) for this Project — enforced by a static test, matching the pattern Epic 2's RCI-05 already establishes for the control-server boundary.
- A message is only ever passed to `SmtpAdapter.send()` if its status is exactly `'approved'` — the adapter itself re-checks this and refuses otherwise, as a second, independent gate beyond whatever called it.
- The adapter re-checks `do_not_contact` on both the contact and its organization immediately before sending (a third, final gate) — suppression state could theoretically change between draft and send; this is not assumed impossible.
- In this epic, `SmtpAdapter`'s real transport is behind a strategy interface with exactly one implementation available: a mock/no-op transport that records "would have sent X to Y" for test assertions. A second, real implementation is a distinct future task, explicitly requiring a real, Owner-approved credential.

## Reply ingestion

Timeweb's SMTP relay is outbound-only; replies land in whatever mailbox `cctv_organizations`/`cctv_contacts` correspondence uses — the ingestion design assumes IMAP polling of that mailbox (the concrete mailbox/provider to be confirmed by the Owner when real ingestion is authorized; this design does not assume it is also Timeweb-hosted).

```text
IMAP poll (scheduled, not this epic's scope to schedule)
        │
        ▼
ReplyIngestionAdapter.poll()       -- new, isolated module; the ONLY code path
        │                              allowed to open an IMAP connection
        ▼
[MOCK TRANSPORT in this epic]       -- real imaplib call is written but never
        │                              exercised against a real mailbox until a
        │                              distinct future task
        ▼
cctv_replies row created, matched to in_reply_to_message_id where possible
        (unmatched replies are still recorded, never dropped)
```

- Same credential-isolation rule as `SmtpAdapter`: env-var-only, one module allowed to import the IMAP client, static test enforcing this.
- A reply is never used to directly infer `do_not_contact = false` — an unsubscribe-shaped reply (`classified_intent = 'unsubscribe'`) sets `do_not_contact = true` on the contact automatically (the one write ingestion is allowed to make to `cctv_contacts` without a separate approval step, since honoring an unsubscribe request promptly is a stronger obligation than requiring Owner review first); no other intent classification writes to `cctv_contacts`/`cctv_organizations` without a human reviewing it.

## What this epic's task queue actually builds

`CCTV-*` tasks implement the schema, the drafting pipeline with suppression checks, and both adapters *behind their mock transport* — proving the full pipeline from Opportunity through a drafted, Owner-approved, "sent" (mock) Message and a matched (mock) Reply. Connecting a real Timeweb account is explicitly out of this epic's scope; see `PROJECT.md`'s "Next milestone."
