# Plan 38: Shared Service readiness for a partner CRM inbox (lane SS-FUJI-READINESS)

Size L, lead pattern. A partner CRM moves its WhatsApp inbox onto the omnichannel module and never logs in to SS: everything goes through the API key gateway. Repo is public, so no keys, tokens, phone numbers or customer data here. Security findings are tracked in private notes, not in this file.

## Phases

| Phase | Output |
|---|---|
| 0 Diagnose | Live environment check of omnichannel and Gemini. Notes are private |
| 1 Gap table | Gaps 1-7 checked against the code, open questions answered |
| 2 Build | One PR per gap, red-first, kill test, reviewer, security-reviewer on API-key routes. Order: 2, 3, 7, then 1, 5, 4, 6 |
| 3 Environment test | End to end PASS/FAIL: send, receive on 2 numbers, signed webhooks, voice, templates, Gemini. Guide and Outline updated |

## Gap table

Paths are under `service_backend/modules/omnichannel/` unless they start with `app/`.

| Order | Gap | Status | Size | Plan |
|---|---|---|---|---|
| 1 | 2 Webhook per channel | Confirmed, webhook create binds one channel (`services/public_gateway_service.py`) | M | Per decision D1 |
| 2 | 3 `message.outbound` | Event missing. `message.status` already fires for every send, with ids and no body | M | Emit from `_enqueue_and_finalize`, additive and opt-in, guide section 7 |
| 3 | 7 Config under the API key | Confirmed. Business hours are per workspace plus tenant default. Node field schemas need a new read route | L | Per D2, D3. Slices: key scope, hours, catalog from the registry, CRUD, validate, publish, versions, runs, run for one contact |
| 4 | 1 `GET /channels` | Confirmed | S | New route with a narrow public schema |
| 5 | 5 Mark as read | Confirmed, needs an adapter call | M | `mark_read` on the adapters, `POST /contacts/{id}/read` |
| 6 | 4 `replyToMessageId` | Confirmed, internals already support it | S | Add the field and multipart key, thread through the gateway |
| 7 | 6 Guide + Outline | Partly | S | Docs, then publish to Outline |

Also noted: `POST /messages` without `channelId` sends from the default channel even if the contact last wrote on another number. Document it, do not change the default.

## Open questions

| Question | Answer |
|---|---|
| Rate limits, replay after outage, retention and PDPA erase, file library, pricing data | Product decisions, see D5 |
| Import fidelity | Timestamps kept, some derived and flagged. Sender only for mapped users. Media in API mode, none in CSV mode |
| Webhooks during import | None, no workflow triggers either |
| One source into 2 workspaces | Not blocked. Contacts may land in both, UNVERIFIED |
| After-hours per company | Workspace plus tenant default only, see D2 |
| Workflow per channel | Trigger config only, single channel equality |
| `draftDefinition` stability | Pin and check the version before a second editor writes it |
| Assign nodes | SS user assign nodes must not port as they are |
| Who pays Meta, any SS fee | Not a code question, owner decision |
| webm voice | Accepted, transcoded to ogg opus. No real send run yet |

## Decisions asked of the owner

D1 webhook scope, D2 business hours scope, D3 API key power and node allow-list, D4 where Phase 3 runs, D5 which open questions join this lane. Recorded here once answered.
