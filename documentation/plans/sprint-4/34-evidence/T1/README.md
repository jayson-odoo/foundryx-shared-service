# Plan 34 (A7b) - T1: independent tester evidence run

Recorded 2026-09-08 by the independent tester (post `93efa28a`), against the SAME live lane
(`:8014` DB `foundryx_service_s34`, `:3012` prod build) the S6/S6-fix coder passes used, plus a
fresh static host-page server on `:3013` (killed at the end of this run). Real clicks throughout,
via `agent-browser` (`s34t` admin wizard, `s34tadmin` agent inbox, `s34tv`/`s34tv2`/`s34tv3`/`s34tv4`
visitor sessions). Every created name is timestamped (`1788818335`, `1788818778`) so residue is
identifiable and ignorable by a future run.

## What this re-verifies

- **AC-WEB-64** - connect a NEW web chat channel (`E2E Web Chat 1788818335`) from `/`, real clicks:
  Channels > Connect channel > Channel type = Web chat (searchable select, AC-WEB-01) > name +
  workspace + origin `http://localhost:3013` (Add enables Connect only once an origin exists,
  AC-WEB-02) > Connect > secret revealed once > Channels list shows the row with the Web chat badge.
  Channel detail tabs = Configuration / Widget / Webhooks (AC-WEB-03).
- **AC-WEB-65 core path** - a fresh static host page on `:3013` loads the snippet, opens the
  widget, fills pre-chat (name + email), sends a message; the agent sees the thread live in the
  Omnichannel inbox (composer never locked, AC-WEB-08) and replies; the visitor's page shows the
  reply **with zero reload** (screenshot 10, taken without navigating).
- **AC-WEB-66 first half** - `http://127.0.0.1:3013/` (same file, a genuinely different origin, NOT
  on the channel's allowlist) injects **zero iframes** (`get count iframe` = 0, screenshot 13).
  Direct navigation to the panel URL (`http://localhost:3012/public/webchat/<widgetKey>`, no loader,
  no iframe) renders a blank document (screenshot 14) and the `contact_channel_identities` row count
  for that channel stayed at 1 (unchanged) before and after - zero sessions started server-side.
- **AC-WEB-66 second half** - a DEDICATED new workspace (`T1 Closed Hours 1788818778`) with all
  seven days' business hours set to empty windows, a new web chat channel on it
  (`T1 Offline Chat 1788818778`), the panel shows the offline greeting ("We're offline right now -
  leave a message and we'll reply.") instead of the online greeting, and the visitor's message still
  lands in the inbox through the identical pipeline (contact created, `channelType: WEBCHAT`,
  `cswExpiresAt`/`windowExpiresAt`/`humanAgentExpiresAt` all null, confirmed via
  `GET /omnichannel/contacts`).

A dedicated workspace was used for the business-hours-closed half rather than mutating the shared
`General` workspace's hours, since other channels (including live coder work in this lane) live on
it - the "provision a dedicated tenant/workspace when mutating shared state" rule extended to
workspace-level state here.

## Steps and screenshots

| # | File | What |
|---|---|---|
| 1 | `shots/01-wizard-webchat-1280.png` | Connect wizard, Web chat branch, name + origin filled, Connect enabled |
| 2 | `shots/02-secret-revealed-1280.png` | Widget secret revealed once in the connect dialog |
| 3 | `shots/03-widget-tab-1280.png` | Channel detail, Widget tab (appearance, greeting, pre-chat toggles, install snippet) |
| 4 | `shots/04-host-launcher-1280.png` | Host page `:3013`, launcher bubble rendered |
| 5 | `shots/05-prechat-filled-1280.png` | Pre-chat name + email + first message typed |
| 6 | `shots/06-visitor-sent-1280.png` | Greeting + the visitor's sent message |
| 7 | `shots/07-agent-inbox-1280.png` | Thread live at the top of the agent inbox, Web chat badge |
| 8 | `shots/08-agent-thread-1280.png` | Agent composer, never locked, reply typed |
| 9 | `shots/09-agent-replied-1280.png` | Agent reply sent |
| 10 | `shots/10-visitor-live-reply-1280.png` | Visitor's page after the reply, **no reload performed** |
| 11 | `shots/11-visitor-375.png` | Visitor panel at 375px, fills viewport, tappable |
| 12 | `shots/12-agent-thread-375.png` | Agent thread view at 375px |
| 13 | `shots/13-offlist-origin-no-widget-1280.png` | `127.0.0.1:3013` - zero iframes injected |
| 14 | `shots/14-direct-panel-blank-1280.png` | Direct panel URL navigation - blank document |
| 15 | `shots/15-offline-greeting-1280.png` | Dedicated closed-hours workspace, offline greeting + pre-chat |
| 16 | `shots/16-offline-message-sent-1280.png` | Offline message sent from the visitor |

## Live curl/API cross-checks (same channel/session as the click-through above)

- `GET /omnichannel/widget/<unknown>.js` -> `404 {"detail":"Not found."}` (23 bytes, byte-identical
  to the pytest-asserted uniform 404).
- `POST /session` with `Origin: http://localhost:3012` (the app's own/panel origin, off the
  channel's allowlist) -> `404` (same uniform body) even though `access-control-allow-origin` is
  echoed (that header comes from the general app CORS middleware, not the webchat allowlist check -
  matches the pytest comment in `test_session_from_the_panels_own_origin_is_the_uniform_404`).
- `POST /session` with the allowlisted origin -> `200` + `Access-Control-Allow-Origin: <exact
  origin>` + `Vary: Origin`, no `Access-Control-Allow-Credentials`.
- No `Origin` header, and `Origin: https://evil.example` -> both `404`, byte-identical body.
- No Bearer -> `401`. Honeypot (`hp` filled) -> `200 {"ok":true}`, zero rows written (confirmed via
  `GET /messages` on that same token returning `{"data":[],"nextAfter":null}` afterwards, then a
  valid message DOES land normally).
- 4097-char text -> `422 text_too_long`. Oversized raw body -> `422 body_too_large`. Multipart ->
  `422 unsupported_content`. None of these three wrote a `ConversationMessage` row.
- An internal note (`POST /contacts/{id}/notes`) with the real agent's name never appeared in the
  visitor's `GET /messages` - only the agent's text reply, with `agentName: "Support"` (the
  channel's configured display name, never "Demo User").
- Gateway `webchat:visitor:<id>` on a live API key resolved the existing identity and queued a send
  (`202`); `webchat:visitor:no-such-visitor-<ts>` returned `422 invalid_recipient` and created no
  contact (row count unchanged before/after).
- Both gateway read shapes (`format` unset and `format=rio`) carried `channelType: "WEBCHAT"`,
  `cswExpiresAt`/`windowExpiresAt`/`humanAgentExpiresAt: null`, `visitorLastSeenAt` populated.

## Cleanup

- Both probe channels (`E2E Web Chat 1788818335`, `T1 Offline Chat 1788818778`) disconnected via
  `POST /omnichannel/channels/disconnect`.
- The dedicated workspace `T1 Closed Hours 1788818778` was left in place (workspaces have no
  disconnect/trash action exposed on this surface); it is timestamped and inert (no channels, no
  contacts) so it is identifiable residue for a future pass, not live noise.
- All `agent-browser` sessions (`s34t`, `s34tv`, `s34tv2`, `s34tv3`, `s34tv4`, `s34tadmin`) closed by
  name.
- The `:3013` static host server (this run's own `python3 -m http.server`, a different process from
  any prior evidence pass's) was killed; `:8014` and `:3012` left running for the next
  reader/reviewer as instructed.

## Result

All four re-verified journeys (AC-WEB-64, AC-WEB-65 core path, AC-WEB-66 both halves) **PASS**,
consistent with the S6-fix coder's own evidence (`../S6-fix/README.md`) and with the fresh backend
regression suite run this pass. See the rewritten Test Execution Report
(`../../34-omnichannel-channel-web-chat-test-report.md`) for the full AC table and defects found.
