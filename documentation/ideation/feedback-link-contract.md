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
  `idea_status_events` item (`status-events-contract.md`), and `board_url` on
  the one-shot (`POST /ideation/intake/ideas`) and own-similar
  (`POST /ideation/intake/ideas/similar-own`, per match) intake APIs ONLY when
  the host sends `reply_to_submitter: true` - i.e. it states its reply goes to
  the submitter themself, never to an operator filing for someone else (owner
  16 Nov Q2 a). Without the flag those APIs answer exactly as before (no
  `board_url` key); `link` (the per-idea status page) is unchanged in every
  case. `board_url` is null for a test idea or an idea with no submitter
  contact. Test ideas never mint one.
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
- Framing: the shared-service frontend answers every `/public/feedback/board/**`
  page with `Content-Security-Policy: frame-ancestors 'self' <CRM origins>`
  (env `FEEDBACK_BOARD_FRAME_ANCESTORS`, space/comma separated bare origins;
  default `https://fe-sorento.foundryx.my`) and no `X-Frame-Options`. The board
  needs no cookies (Bearer from `/portal/ideas/session/link`), so it works in a
  cross-site iframe without any SameSite change.
- Share page (lane FEEDBACK-SHARE-SS-HOST): share links follow the same host
  rule as board links - `{CRM origin}/feedback/share/{shareToken}` for a CRM
  tenant, else `{base}/public/feedback/share/{shareToken}`. The CRM route
  `/feedback/share/{shareToken}` iframes `{shared-service frontend}/public/feedback/share/{shareToken}`
  with the same headers as the board page; SS answers `/public/feedback/share/**`
  with the same `frame-ancestors` list. After the phone check the framed page
  navigates the TOP window to the visitor's board.
- Phone check errors: a 403 from the CRM lookup or send-code (integration user
  lacks `integration.contact_phone.verify`) shows "Phone check is not set up for
  this product yet." (error code `not_set_up`); other failures keep "We could not
  check your number right now. Try again." 
