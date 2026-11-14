# Plan 58 acceptance criteria (contact erase register)

Plan: `58-contact-erasures-register.md`. Follow-up to plan 56 C (contact erase, PR #188). Final: crew rulings 1a 2a 3a 4a (5 Nov) on the behaviour card.

## Journey

1. An Admin (or a workspace integration through its API key) erases a contact, exactly as plan 56 C ships it: the staff menu or `DELETE /omnichannel/contacts/{id}`, or `DELETE /api/v1/omnichannel/contacts/{identifier}`.
2. Nothing new to click or send. The erase answers the same `ContactEraseResponse` as today.
3. In the same commit the system writes one register row: who erased (the staff user, or the API key), when, which contact id in which workspace, and how many messages and files went.
4. Later someone asks "who erased contact X, and when?". The tenant's operator answers it from the register with a read query (no screen in this plan; a viewer is backlog BL-SS-350). The row names no person: the contact, its messages and files are gone and the row only carries ids and counts.

## S0. Register table

- AC-58-01 [BE] New module table `app_omnichannel.contact_erasures` with exactly these columns: `id` (string PK), `tenant_id` (not null), `workspace_id` (not null), `contact_id` (not null), `actor_kind` (not null, `staff` or `api_key`), `actor_user_id` (nullable), `api_key_id` (nullable), `messages` (int, not null), `files` (int, not null), `erased_at` (`UTCDateTime`, not null). No foreign key to `contacts` or `workspaces`.
- AC-58-02 [BE] A database check holds the actor rule: `actor_kind = 'staff'` needs `actor_user_id` set and `api_key_id` null; `actor_kind = 'api_key'` needs `api_key_id` set and `actor_user_id` null; any other `actor_kind` is refused.
- AC-58-03 [T] Module migration `0026_omni_contact_erasures` (revises `0025_omni_migration_sync`, id <= 32 chars, one head) creates the table, the check and indexes on (`tenant_id`, `erased_at`) and (`tenant_id`, `contact_id`), idempotent like `0025`; downgrade drops it. Applied with `bootstrap_db` to a throwaway restore of a dev copy DB on Postgres before review, and checked there (columns, check, indexes, downgrade then upgrade again).

## S1. Every erase writes its row

- AC-58-10 [BE] Given an Admin with `contacts.erase`, when they erase a contact through `DELETE /omnichannel/contacts/{id}`, then exactly one register row exists for it with `actor_kind = 'staff'`, `actor_user_id` = that user's id, `api_key_id` null, the contact's `tenant_id`, `workspace_id` and `contact_id`, and `messages`, `files` and `erased_at` equal to the response's `messages`, `files` and `erasedAt`.
- AC-58-11 [BE] Given a workspace API key, when it erases a contact through `DELETE /api/v1/omnichannel/contacts/{identifier}` (by id and by `phone:`), then exactly one register row exists with `actor_kind = 'api_key'`, `api_key_id` = that key's id, `actor_user_id` null, and the same counts and time as the response. The request's existing `integration_activity` row is still written.
- AC-58-12 [BE] The row is written in the erase's own transaction: when the erase fails before commit (forced failure in the row deletes or at commit), no register row exists and the contact and its messages are still there; when writing the register row fails, the erase rolls back the same way and answers an error.
- AC-58-13 [BE] An erase that does not happen writes nothing: unknown id, another tenant's contact, a second erase of the same id (all 404), a user without `contacts.erase` (403), a bad or revoked key (401), and a key from another workspace (404).
- AC-58-14 [BE] The row carries no erased personal data: given a contact with a distinctive name, phone, email and message text, none of those values appears in any column of its register row.
- AC-58-15 [BE] The row outlives the contact: after the erase, a new inbound message or send to the same number creates a new contact with a new id; the register row is unchanged. The later file purge (`purge_erased_files`) does not change the row.
- AC-58-16 [BE] No erase path can skip the row: `ContactEraseService.erase` and `erase_in_tenant` take the actor as a required keyword argument (no default), so a caller without one fails at the call.
- AC-58-17 [BE] Module uninstall for a tenant removes that tenant's register rows with its other omnichannel rows (`bootstrap.uninstall_tenant`), and never another tenant's.

## Contract and docs

- AC-58-20 [T] No wire change: the staff and API-key erase responses, status codes and the `contact.erased` event are unchanged; the consumer guide needs no edit.
- AC-58-21 [T] `documentation/engineering/omnichannel-service.md` erase section names the register (what it holds, same transaction, no personal data, removed only with the tenant's module data); backlog row BL-SS-350 "Erase register viewer" links this plan.
