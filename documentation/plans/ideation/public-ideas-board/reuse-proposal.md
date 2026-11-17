# PUBLIC-IDEAS-BOARD reuse proposal (replaces the new-page plan of card v2 / mock v2)

Owner (15 Nov ~10:03): "I remember we already have that one". Correct: the Canny-like board exists.

## The existing board (screenshots with fake data: `evidence/existing/existing-*-{1280,375}.png`)
The idea portal (lane IDEA-PORTAL, `components/platform/idea-portal/`), one component set, two entry points today:
- `/portal/ideas/*` - shared-service staff sign-in (`PortalRoot`, `portal-root.tsx:54`).
- `/embed/ideas/portal/*` - inside Sorento CRM `/ideas` through the iframe SSO (`EmbedPortalRoot`, `portal-root.tsx:63`).

| Canny pattern | Already there |
|---|---|
| Post list: vote box left, title, status badge, comment count, "Your idea" | Feedback tab `feedback-view.tsx`, `idea-card.tsx`, `upvote-box.tsx` |
| Search, status filter, sort (Top / New), My filter | Feedback tab toolbar (`My ideas` toggle) |
| Roadmap: Under review / Planned / In progress / Complete | Roadmap tab `roadmap-view.tsx`, `roadmap-board.tsx` (columns from the status map, `services/portal.py:385`) |
| Changelog | Changelog tab `changelog-view.tsx` |
| Post page: vote, status, fields, "Where is it" steps, voters, comments, activity (status history) | `idea-page.tsx` |
| One vote per person, toggle | `POST /portal/ideas/{id}/vote` (`PortalPrincipal.voter_id`) |
| "Mine" = my own items incl. same-phone contacts, never by name | `_owned_q` -> `ownership.owned_filter` (`services/ownership.py:97`) |
| Hidden / draft / test / merged rules | `PortalService._visible` (`services/portal.py:446`) |

## Smallest change: a third entry point, a personal link
Shared-service (this PR):
1. `app_ideation.idea_contact_links` (tenant_id, contact_id, token, created_at, revoked_at). Token = `secrets.token_urlsafe(24)`, unguessable, revocable, one per contact.
2. Portal principal kind `contact`: `POST /portal/ideas/session/link {token}` mints the SAME portal token as staff/crm (`mint_portal_token`). Each request re-checks the link is not revoked and the contact still exists in that tenant. Identity = the contact's phone, so the existing `owned_filter` gives "My requests" (same-phone contacts included). `voter_id = contact:<id>`, so the existing vote toggle gives one vote per contact per item. `can_manage` is always false.
3. Frontend: `LinkPortalRoot` next to the two existing roots, at `/feedback/{token}` (+ `/roadmap`, `/changelog`, `/{number}`). The same views. Memory-only token. "My requests" wording. No Submit form for a contact (Q-B).
4. Link builder `mint_board_link(db, idea)` -> `{base}/feedback/{token}/{ideaNumber}`. It is used for the WhatsApp intake reply and added as `board_url` on every `idea_status_events` payload (`track_url` unchanged) for CRM lane FEEDBACK-STATUS-WA.

Sorento CRM (second PR): a public route `/feedback/[token]` with the CRM portal header that iframes the shared-service board in link mode, the same way `/ideas` already iframes it for signed-in users.

Wording / URLs: "Feedback" everywhere user-visible; paths aligned with lane FEEDBACK-RENAME.
