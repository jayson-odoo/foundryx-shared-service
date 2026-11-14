# Plan 34 / A7b - S4 evidence run log (the panel)

Lane: backend `:8014` (DB `foundryx_service_s34`), frontend `:3012`,
`agent-browser --session s34` (visitor) + `--session s34admin` (agent, signed
in as `demo@example.com`). Real clicks, no Playwright.

Channel used for the LIVE (real-backend) run: created via
`POST /omnichannel/onboarding/webchat/connect` (workspace `General`,
`allowedOrigins: ["http://localhost:3012"]`) - widget key
`wk_23e3024145a341c4b747a71ad6f51367`, name `S4 Evidence Web Chat <unix ts>`.
Channel used for the mock-mode quick-reply/responsive shots: the S0-seeded
mock widget key `wk_demo0000000000000000000001` (no real backend involved -
`webchatVisitorService` is bound to `mockWebchatVisitorService` in the
committed source; these two screenshots demonstrate the mock's canned reply
+ quick-reply affordance the same way S0's own mock states were verified).

## Steps and screenshots (real backend, :8014)

1. `01-prechat-1280.png` - `http://localhost:3012/public/webchat/wk_23e30...`
   opened directly, clicked the launcher bubble. Pre-chat step renders
   (askName + askEmail toggles on this channel; askPhone off), greeting
   "Hi! How can we help you today?", bottom-right anchored panel at 1280px
   (AC-WEB-51).
2. `02-visitor-sent-1280.png` - filled Name "Ada Lovelace", Email
   "ada@example.com", message "Hi, I need help with my order", clicked Send.
   The pre-chat step never resurfaces after the first message (AC-WEB-53).
   Verified server-side: `GET /omnichannel/contacts?workspaceId=...` shows a
   NEW `WEBCHAT` contact with `lastMessagePreview: "Hi, I need help with my
   order"`, `unreadCount: 1` (AC-WEB-26 - lazy creation on first message).
3. `03-admin-reply-1280.png` - signed in as `demo@example.com` in a SECOND
   agent-browser session, opened `/omnichannel/inbox`, found the thread,
   replied "Hi Ada! Happy to help - what's your order number?". Drawer shows
   the "Web chat" channel badge and the neutral presence marker "Last seen
   08 Sept 2026, 01:56" (AC-WEB-43) - composer never locked.
4. `04-visitor-live-reply-1280.png` - back on the visitor panel (NO reload),
   the agent's reply arrived live over the visitor WebSocket
   (`?workspaceId=&token=<visitor token>`, AC-WEB-38/40) within seconds.
5. `05-visitor-375-open.png` - same widget key, page reloaded, viewport set
   to 375x812. The STORED visitor token (localStorage) resumed the SAME
   session and full history on a fresh page load (AC-WEB-29/49/50) - no
   pre-chat step re-shown, panel fills the viewport edge to edge (AC-WEB-51).

Origin enforcement (curl, AC-WEB-23/24, R6/R7):
```
POST .../wk_23e30.../session  Origin: http://evil.example      -> 404
POST .../does-not-exist/session  Origin: http://localhost:3012 -> 404
```
Both byte-identical uniform 404s.

`Content-Security-Policy` on the panel document (curl -I, AC-WEB-47):
```
content-security-policy: frame-ancestors http://localhost:3012
```
Resolved live from the NEW `GET /public/omnichannel/webchat/{key}/frame-policy`
endpoint via `middleware.ts`.

## Steps and screenshots (mock mode, quick replies + a second 375/1280 pass)

6. `06-quick-replies-1280.png` - mock widget key, pre-chat completed with
   "What are your pricing plans?"; the mock's canned agent reply "Thanks for
   reaching out! Someone from our team will be with you shortly." arrives
   with two quick-reply buttons (Pricing / Support), rendered via the poll
   fallback (see the D-A7B-16 fix in the commit body). Clicking "Pricing"
   sends it as a normal message.
7. `07-prechat-375.png` - the pre-chat step at 375px, non-clipped, full
   viewport.
8. `08-quick-replies-375.png` - the quick-reply buttons tappable at 375px
   (AC-WEB-51).
9. `09-launcher-375.png` - the closed launcher bubble (AC-WEB-45's panel
   side - the loader itself, and its resize contract, are S1/S6 concerns;
   this confirms the panel renders ONE bubble control, not the loader's
   iframe chrome, and posts `opened`/`closed`/`ready` to `window.parent`).

## Console / network

`agent-browser console` returned no output (no console errors/warnings) on
both the visitor and the admin session for the entire run. Backend log
(`/tmp/s34-backend.log`) shows no tracebacks across the run - only routine
outbox-poll `SELECT`s.

## Not covered here (explicitly out of S4 scope per the brief)

- The real loader (`loader.js`) embedding the panel in an iframe on a
  genuinely different origin (`:3013` static host) - that is S6's
  host-page-in-iframe E2E (AC-WEB-64..66).
- Business hours / offline greeting (S5) and host identity assertions (S5).
- Agent-to-visitor media (`AC-WEB-41`) - the `MessageBubble` component
  renders `message.media` (image inline / file as a link) but no S3 seed
  data included a media message in this run; the rendering path is covered
  by the component's own structure and by S3's backend test suite for the
  signed-URL contract.
