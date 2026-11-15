# PUBLIC-IDEAS-BOARD plan (shared-service slice; CRM page = second PR)

Contract: `acceptance-criteria.md`. Reuse decision: `reuse-proposal.md`.

## Backend (`modules/ideation`)
1. **Model** `IdeaContactLink` (`app_ideation.idea_contact_links`): id, tenant_id, contact_id (FK omnichannel
   contacts, same as `Idea.submitter_contact_id`), token (unique), created_at, revoked_at. Migration
   `0020_ideation_contact_links` (idempotent `IF NOT EXISTS`, Postgres only). Tenant uninstall already wipes every
   module table by `tenant_id`.
2. **Service** `services/feedback_links.py`: `get_or_create_link`, `cancel_links_for_contact`, `resolve_link`
   (shape check, token lookup, not revoked, contact resolved WITH the link's tenant), `mint_board_link`.
3. **Portal principal** `kind="contact"` in `services/portal.py`: `session_for_link` (IP-throttled failures, own
   throttle scope), `resolve_portal_token` re-checks the link per request (`lid` claim), `voter_id` = bare contact id
   (same id as the intake upvote), comments as author kind `contact` (role "Dealer"), `_owned_q` = contact id +
   same-phone contacts, `submit` refused. Hide / note already need `can_manage` (always false).
4. **Router** `POST /portal/ideas/session/link`; staff `POST /ideation/ideas/{id}/feedback-link/cancel`.
5. **Links sent**: `board_url` in `status_events._write_event` payload; intake reply uses `mint_board_link` first.

## Frontend
6. `LinkPortalRoot` (third root next to `PortalRoot` / `EmbedPortalRoot`) + `useLinkPortalSession(token)`, memory-only
   token, `LINK_PORTAL_PATHS(token)`; routes `app/(public)/public/feedback/board/[token]/{page,roadmap,changelog,[id]}`.
   Feedback view hides Submit when `principal.kind === 'contact'`; "My requests" label for contacts.
7. Staff idea page action "Cancel feedback link" (only when the idea has a submitter contact).

## Out of scope / follow-ups
- Contact picker on the staff form (QE b) -> backlog.
- Sorento blue = tenant Branding settings (QA a), no code.
- CRM `/feedback/board/[token]` page iframing `/public/feedback/board/{token}` -> sorento-crm PR.
