# Personal feedback link contract (lane PUBLIC-IDEAS-BOARD)

A dealer (omnichannel contact) opens the tenant's feedback board with no login
through a personal link. Shared-service is the source of truth; the Sorento CRM
only hosts a public page that shows the shared-service board in an iframe.
Plan + UAC: `documentation/plans/ideation/public-ideas-board/`.

## 1. The link
- One live link per contact (database-enforced), token =
  `secrets.token_urlsafe(32)`. It stays valid until staff cancel it (owner QD a);
  the next message to that contact then carries a fresh token.
- Shape: `{board base}/{link token}/{idea number}` (the idea number is omitted
  when the idea has none; the board then opens on its Feedback tab).
- Board base, from the tenant `public_link_base_url` (core catalog settings):
  - a `{token}` / `{ideaId}` template (the CRM portal) ->
    `{scheme}://{host of that template}/feedback/board` (the CRM public page, section 3);
  - a plain URL, or unset -> `{that URL or frontend_url}/public/feedback/board`
    (the shared-service page).
- Where it is sent: the WhatsApp intake "Track it here" reply for the
  contact's own idea or the idea they voted for, and `board_url` on every
  `idea_status_events` item (`status-events-contract.md`). NOT returned by the
  one-shot or own-similar intake APIs (those answer the host). Test ideas never
  mint one.
- It is a bearer credential: send it only to that contact; never log it.

## 2. What the link allows (`POST /portal/ideas/session/link {token}`)
- Returns `{token, principal}` with `principal.kind = "contact"`, `role =
  "Dealer"`, `canManage = false`; the portal token lasts 2 h and every request
  re-checks the link (cancelled / contact gone / tenant suspended / module off
  = 401).
- Bad, unknown or cancelled link = uniform 401 `{"error":{"code":"unauthorized",...}}`;
  failed exchanges are throttled per IP (429 + `Retry-After`).
- The dealer reads the same set as a staff-portal non-manager (no draft, test,
  merged child or hidden item), upvotes (one vote per contact, the same vote as
  a WhatsApp upvote), and comments. Submit, hide and changelog notes = 403.
- "My requests" (`mine=true`) = items filed by that contact or any same-tenant
  contact with the same phone digits. Never by name.
- Items open by id or by idea number: `GET /portal/ideas/IDEA-0042`.

## 3. Sorento CRM public page (second PR, sorento-crm)
- Route `/feedback/board/{linkToken}` and `/feedback/board/{linkToken}/{ideaNumber}`, no
  login, CRM portal header.
- Body = an iframe of `{shared-service frontend}/public/feedback/board/{linkToken}`
  (+ `/{ideaNumber}`), same as `/ideas` iframes the board for signed-in users.
- The page must send `Referrer-Policy: no-referrer`, `Cache-Control: no-store`
  and `X-Robots-Tag: noindex`, and must not log the path.
- Colours: the Sorento tenant's Branding settings (owner QA a), no CRM code.
