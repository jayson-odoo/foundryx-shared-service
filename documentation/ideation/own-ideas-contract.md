# Own-idea contract (SS-IDEATION-OWN) - for IDEATION-CAPTURE (sorento PR #1444)

Crew lane SS-IDEATION-OWN. Additive only: the `/ideation/intake/create-idea`
turn flow (draft / collect / review / confirm) is unchanged.

Owner rule (from IDEATION-CAPTURE): only senders with a CRM login + Ideas
permission create via the chatbot; a user may edit their own idea, others' ideas
need the manage permission. Shared-service supports this with a required CRM
user link on chatbot creates, `isMine`, `mine=true`, and an opt-in
`ideas_manage` assertion claim the embed enforces.

## Ownership rule

An idea belongs to a submitter identified by EITHER

- `ideas.submitter_crm_user_id` (new column, migration 0015) - the host CRM user
  id; set by the one-shot chatbot create and the embed create (assertion `sub`), or
- the submitter contact's phone - `ideas.submitter_contact_id` -> an omnichannel
  contact in the SAME tenant whose phone has the same digits (omnichannel's
  `digits_only` / `Contact.phone_digits`, so formatting on either side does not
  matter: `+60 12-345 6789` matches `60123456789`).

Never by display name. A blank CRM id or a phone with fewer than 8 digits is no
identity: it matches nothing, so `mine=true` without identity is an empty list,
never "all". Code: `modules/ideation/services/ownership.py`.

Trust assumptions (the host must honour these):

- **One CRM user-id namespace per tenant.** `sub` / `submitter_crm_user_id` are
  compared as-is. A tenant with two different host CRMs (or two embed
  connections whose user ids collide) would see false `isMine`. Today: one
  sorento per tenant.
- **`phone` must be a verified number** (the user's WhatsApp number the CRM has
  verified), never a profile field the user can edit freely - it grants
  ownership of ideas that phone sent from WhatsApp.
- **The workspace key is a tenant-level server credential.** It may assert any
  submitter on one-shot create and similar-own, and sees ideas from every
  workspace of its tenant (ideas and contacts are tenant-wide).
- Embed ideas created before migration 0015 carry no CRM link, so an
  `ideas_manage=false` viewer cannot edit those older embed ideas (WhatsApp
  ideas stay owned through the phone link).

## Idea number

Main already mints `idea_number` (`IDEA-0001`, per-schema Postgres sequence,
`services/numbering.py`) when an idea is promoted by the completion sink; existing
captured ideas were backfilled by migration 0010. The one-shot create promotes
through the SAME sink, so it gets a number the same way. Drafts never get one.
Operator/embed-created ideas have no number on main today - unchanged here.

## API contract (final)

All intake endpoints: workspace API key (`Authorization: Bearer fxw_live_...`),
snake_case, errors use `{"error": {"code", "message"}}`.

### 1. One-shot create - `POST /ideation/intake/ideas` -> 201

Request:

| field | type | notes |
|---|---|---|
| `product_id` | string | required; 404 `unknown_product` if not the key's tenant |
| `problem` | string | required; blank = 422 `problem_required` |
| `submitter_crm_user_id` | string | **required**; blank = 422 `submitter_required` |
| `submitter_phone` | string? | E.164; links/creates the contact copy; junk = 422 `invalid_phone` |
| `submitter_name` | string? | display name |
| `title` | string? | 1-8 words; longer = 422 `title_too_long` |
| `proposed_solution`, `impact`, `department` | string? | |
| `submitter_tier` | string? | |
| `raw_transcript` | string? | stored as `raw_text` (else `problem`) |
| `attachments` | array? | same shape as `/create-idea` (`source_msg_id`, `type`, `url`, `filename?`, `caption?`) |
| `is_test` | bool | default false |
| `intake_ref` | string? | idempotency key (e.g. the confirming Respond.io message id) |

Response: `{"idea_id", "idea_number", "status": "captured", "title", "link"}`
(`link` = the public status link, null when no `status_token`).
No cross-submitter dedup on this call: run the own-similar lookup first.

Idempotency: a retry with the same `intake_ref` (same tenant, same
`submitter_crm_user_id`) returns the idea already created, same body, no second
idea and no second number. The same `intake_ref` from a different CRM user =
409 `intake_ref_conflict`. Without `intake_ref` every call creates a new idea.

Other errors: 422 `no_workspace` (a phone was given but the tenant has no
omnichannel workspace to attach the contact copy to).

### 2. Own-similar - `POST /ideation/intake/ideas/similar-own` -> 200

Request: `product_id` (required), `text` (the new idea's problem text),
`submitter_crm_user_id?`, `submitter_phone?` (at least one usable, else 422
`submitter_required`), `is_test` (default false).

Response: `{"matches": [{"idea_id", "idea_number", "title", "problem", "status",
"status_label", "similarity", "created_at", "link"}]}` - at most 3, best first.
Same submitter only, same product, same test/real lane, survivors only (not
merged away), live only (the shared dedup candidacy predicate: not draft /
rejected / duplicate / archived; `closed` counts as live, as in dedup). Score =
`pg_trgm similarity(lower(problem), text)` >= 0.3 (difflib >= 0.55 on SQLite),
the existing dedup thresholds. `created_at` is ISO-8601 `Z`.

### 3. Embed - `isMine` + `mine=true`

- Every embed idea response (`GET /embed/ideas`, `/embed/board`,
  `/embed/ideas/{id}`, `/merged`, and every write that returns ideas) carries
  `isMine: bool` for the viewing CRM user. Operator surfaces always return false.
- `GET /embed/ideas?mine=true` returns only the viewer's own ideas.
- Embed `POST /embed/ideas` stamps `submitter_crm_user_id = sub` and
  `submitter_name = name`, so the creator sees `isMine: true`.

### 4. Assertion claims (sorento `mint_embed_assertion`)

Existing claims unchanged. New optional claims:

| claim | type | effect |
|---|---|---|
| `phone` | string | second ownership link (WhatsApp-submitted ideas) |
| `ideas_manage` | bool | `false` = the viewer may only edit / status-move / delete / reorder / merge / unmerge / attach their OWN ideas (others = 403 `not_owner`; unmerging a survivor needs every idea in the group to be theirs); voting stays open. `true` or absent = today's behaviour. Non-bool values (e.g. the string `"false"`) are ignored = treated as absent, so send a JSON boolean. |

## Security notes

- Every ownership query is tenant-scoped, including the contact phone lookup.
- `isMine` / `mine` derive only from the signed assertion (`sub`, `phone`) and
  stored ids; never from request params or names.
- CRM user ids are assumed unique per tenant (one host CRM per tenant).
- `ideas_manage` is enforced server-side in the embed router; the host still owns
  the decision of who gets `true`.

## Tests

`service_backend/tests/test_ideation_own.py` (red-first), Postgres path verified
manually (migration `0015_ideation_own_ideas` upgrade from 0014 + pg_trgm
own-similar + one-shot sequence mint on a local Postgres 16).
