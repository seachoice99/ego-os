# Chip-Chip TV Licensing: domain model

Per ADR-0011. Every table is additive SQLite in a dedicated set of tables (namespaced `cctv_*` to keep them visually and structurally distinct from `ego_os/store.py`'s core product tables), gitignored exactly like `ego_os/*.db` — no table here is ever exported wholesale into a committed file. `Research Evidence` is deliberately absent as its own table: Chip-Chip TV research uses Epic 1's Evidence Research Engine tables directly (`research_goals`, `datasets`, `facts`, ...), scoped by a Chip-Chip-TV-specific `ResearchGoal`.

```text
cctv_rights_catalog
  id, title, rights_holder_org_id, territory, media_type,
  rights_type (broadcast|streaming|merchandising|other),
  status (available|licensed|disputed|unknown),
  source_of_truth_ref, created_at

cctv_content_catalog
  id, title, content_type (episode|series|format|other),
  original_language, episode_count, duration_minutes,
  related_rights_ids (json), metadata (json), created_at

cctv_organizations
  id, name, org_type (rights_holder|broadcaster|distributor|agency|other),
  country, website, do_not_contact (bool, default false),
  do_not_contact_reason, created_at, source

cctv_contacts
  id, org_id, name, role, email, phone,
  do_not_contact (bool, default false, can override org-level to true but never to false),
  consent_basis (e.g. "publicly listed business contact"),
  created_at, source

cctv_outreach_campaigns
  id, name, goal, target_org_ids (json),
  status (draft|active|paused|completed), created_at, owner_approved_at

cctv_messages
  id, campaign_id, contact_id, direction ('outbound' -- inbound is a Reply, not a Message),
  status (draft|pending_owner_approval|approved|sent|failed|suppressed),
  subject, body, drafted_at, approved_at, approved_by, sent_at,
  suppressed (bool), suppression_reason

cctv_replies
  id, in_reply_to_message_id (nullable -- unmatched replies still recorded, never dropped),
  from_contact_id, received_at, raw_source_ref, body,
  classified_intent (interested|not_interested|unsubscribe|auto_reply|unknown),
  ingestion_run_id

cctv_opportunities
  id, org_id, content_or_rights_ref, stage (identified|contacted|engaged|negotiating|won|lost),
  value_estimate, created_at

cctv_negotiations
  id, opportunity_id, status, terms_summary, started_at, last_activity_at

cctv_agreements
  id, negotiation_id, org_id, terms (json or document ref),
  signed_at, term_start, term_end, status (draft|executed|expired|terminated)

cctv_revenue
  id, agreement_id, amount, currency, recognized_at, payment_status, notes
```

## Suppression / do-not-contact (mandatory, checked before draft creation)

A `cctv_messages` row may never be created (not merely blocked from sending) for a contact where `cctv_contacts.do_not_contact = true` OR the contact's `org_id` has `cctv_organizations.do_not_contact = true`. This check happens at draft-generation time, not send time — a suppressed contact never even gets a drafted message sitting in the queue.

## Message lifecycle (drafts-only, Owner-gated)

```text
draft → pending_owner_approval → approved → sent
                                → suppressed (if suppression discovered after draft, before approval)
              ↘ failed (send attempt failed, requires investigation, never silently retried)
```

No code path in this Project may move a `cctv_messages` row directly from `draft` to `sent` — `approved_at`/`approved_by` must be populated first, always by an explicit Owner action, never inferred.

## Audit-to-domain-model mapping (produced by CCTV-01, not assumed here)

`CCTV-01`'s findings doc must map every existing local table/document's columns onto this domain model (or explicitly flag a column with no home here, rather than silently dropping it). This document does not pre-guess that mapping — it is deliberately written before the audit so the audit can validate or correct it, not rubber-stamp it.
