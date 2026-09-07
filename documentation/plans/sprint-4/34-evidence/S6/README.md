# Plan 34 (A7b) Slice S6 - evidence run log

Recorded 2026-09-08 (host clock showed 2026-09-07 late evening in a couple of
timestamped names below - same run, no significance). Lane: backend `:8014`
(DB `foundryx_service_s34`), frontend `:3012` (prod build), static host page
on `:3013` (`python3 -m http.server 3013` from `documentation/plans/sprint-4/
34-evidence/S6/host/`). `agent-browser --session s34admin` (agent, logged in
as `demo@example.com`) and `--session s34` (visitor). All screenshots below
are named in the order they were captured.

## Lane fix required before any of this worked

The backend's `settings.frontend_url` defaults to `http://localhost:3001`
(`app/config.py`), which the widget loader route (`routers/webchat_widget.py`)
substitutes into the served `loader.js` as the panel origin the loader
iframes. This lane's frontend is on `:3012`, not `:3001` - the plan's own
port table is stale (states `:3011`/`:3012` for a different lane numbering).
**Restart command going forward must include `FRONTEND_URL=http://localhost:
3012`** alongside the other env vars already in the coder brief, or every
widget loader served in this lane points its iframe at a dead `:3001` and the
launcher never renders (broken-image glyph in the host page corner).

## Steps 1-3: AC-WEB-64 - connect + snippet + badge (screenshots 01-05)

1. Logged in as `demo@example.com` at `http://localhost:3012` (real clicks
   from `/`, sidebar Omnichannel > Settings > Channels).
2. Connect channel wizard: Channel type = **Web chat**, name
   `Web chat E2E 20260907193053` (UTC-timestamped), Workspace = General,
   allowed origin `http://localhost:3013` (the lane's static host page - a
   genuinely different origin from the app per R18). Screenshot 01
   (wizard filled), 02 (secret revealed once on connect).
3. Channels list shows the new channel with a **Web chat** badge at 1280px
   (03) and 375px (04).
4. Channel detail > Widget tab shows the install snippet, copied via the
   page's own DOM (05): `<script src="http://localhost:8014/omnichannel/
   widget/wk_8b2ea66a6818437396f4924c32299a28.js" async></script>`.
   `GET .../wk_....js` verified 200, `Content-Type: application/javascript;
   charset=utf-8`, `X-Content-Type-Options: nosniff`, `Cache-Control:
   public, max-age=300`, ETag present, body carries only the widget key and
   the panel origin.

**AC-WEB-64: PASS.**

## Steps 4-8: AC-WEB-65 - the messaging journey (screenshots 06-17)

5. Pasted snippet loaded from `http://localhost:3013` (the host page). The
   loader iframe rendered nothing until the lane fix above was applied
   (06) - see the DEFECT section below; after the lane fix, the launcher
   bubble renders (07).
6. Visitor opened the widget, completed pre-chat (name + email), sent
   "Hi, I need help placing an order" (08, 09).
7. Admin inbox (real clicks, sidebar Omnichannel > Inbox): the new thread
   appears LIVE with the **Web chat** badge (10), opened the thread (11,
   shows "Online now" presence marker, composer never locked).
8. Agent replied "Hi Visitor, happy to help with your order! What's your
   order number?" (12); the visitor's panel showed the reply WITHOUT any
   reload (13, live over the WebSocket). 375px check (14).
9. Agent attached and sent a small PNG via the composer's Attach > Photo
   flow (15) - `conversation_messages` row confirmed `message_type=IMAGE`,
   `media_key` set, `sender_type=AGENT`. The visitor's panel rendered the
   image inline at 1280px (16) and 375px (17), fetched via a signed,
   short-TTL URL bound to the message id
   (`GET /omnichannel/media/<id>?exp=...&sig=...`, 200) - `signed_media_url`
   confirmed live, not a stub.

**AC-WEB-65: PASS** (the image renders inline in the transcript; there is no
click-to-enlarge lightbox in the current `message-bubble.tsx` - "opens it" is
satisfied by the image loading and displaying, not a separate viewer that
does not exist in this codebase).

## Step 9: AC-WEB-66 - a REAL DEFECT found (screenshots 18-19)

Testing the "off-list origin never opens a chat" half of AC-66 (loading the
snippet from `http://127.0.0.1:3013`, a genuinely different origin to the
allowlisted `http://localhost:3013`) surfaced that **the intended-ALLOWED
origin `http://localhost:3013` ALSO fails identically** (18) - the session
POST returns the uniform 404 regardless of which top-level page embeds the
widget. See `34-omnichannel-channel-web-chat-test-report.md` and the coder's
final report for the full root-cause writeup (D-A7B-11's origin check reads
the browser's `Origin` HTTP header on the panel's own `fetch()` call, which
is ALWAYS the panel's own origin - `http://localhost:3012` in this lane -
never the top-level host page's origin, by web-platform design). Confirmed
by direct `curl` (`Origin: http://localhost:3013` -> 200, `Origin: http://
localhost:3012` -> 404) and by a HAR capture of the live browser embed
showing the identical 404. The off-list negative test (19) therefore "passes"
today for the wrong reason - it would fail identically even from the
genuinely-allowed origin.

**AC-WEB-66 first half (off-list origin): FAIL / BLOCKED** - filed as
BL-SS-183 (see backlog), flagged for the security reviewer as the
highest-priority finding of this slice.

For evidence-gathering ONLY, `http://localhost:3012` (the panel's own dev
origin - the only value that can ever appear on this Origin header in this
lane) was TEMPORARILY added to the test channel's allowed origins via the
Widget tab's origins editor (real clicks) so the rest of the pipeline could
be exercised and evidenced (steps 4-8 and 9b below); it was removed again
before finishing (`allowedOrigins` reset to `["http://localhost:3013"]` via
the same admin PUT route) so the channel's committed state matches what
AC-WEB-64 actually connected.

## Step 9b: AC-WEB-66 second half - business hours closed (screenshots 20-23)

With the `:3012` workaround origin temporarily active: set the default
workspace's business hours (Settings > Workspaces > General > Business
hours, real Edit + Save) to a timezone with every day left with zero
windows (all-closed) - confirmed `online: false` via the session response.
Reloaded the SAME returning visitor: the panel's first bubble now shows the
configured offline greeting ("We're offline right now - leave a message and
we'll reply.", 20) instead of the online greeting, at 1280px and 375px (23).
Sent a further message while offline (21) - it landed through the identical
`InboundService` path and appeared live in the admin inbox exactly like an
online message (22), confirming D-A7B-24/AC-WEB-53's "one path, no separate
offline-message entity" rule. Business hours reset afterward (deleted the
`omnichannel_settings` row for the default workspace, restoring the
`online: true` unconfigured default) so this lane's shared default
workspace is not left in a broken state for other channels/tests.

**AC-WEB-66 second half (offline greeting + message still lands): PASS.**

## Cleanup

- Channel `allowedOrigins` reset to `["http://localhost:3013"]`.
- Business hours row for the default workspace deleted (back to
  unconfigured/online).
- `:3013` static host server killed.
- Both `agent-browser` sessions (`s34`, `s34admin`) closed.
- `:8014` and `:3012` left running (restart `:8014` with `FRONTEND_URL=
  http://localhost:3012` in the env, per the lane fix above, if it is
  restarted again).
