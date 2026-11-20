# Plan 34 (A7b) S6-fix - BL-SS-183 evidence run log

Recorded 2026-09-09 (host clock reads 2026-09-07 late evening in the timestamped
names below - same run, no significance). This run re-records the two things
BL-SS-183 invalidated in the S6 run: **AC-WEB-66's first half** (an off-list
origin never opens a chat, while the allowlisted host origin does) and
**AC-WEB-65's core path** (visitor sends, agent replies, live delivery, reload
resumes the same thread). It also verifies the new quiet no-session state.

## The change under test

The LOADER now mints the visitor session. It runs in the customer's own
top-level document, so its `fetch` carries that document's origin - the value
the channel allowlist is about, and one no other website can forge. The panel
never calls `/session`, never stores a token, and renders nothing without one.

**The single most important fact about this run: the channel's `allowedOrigins`
is `["http://localhost:3013"]` and NOTHING ELSE.** The app's own origin
(`http://localhost:3012`) is NOT on it - which is what the S6 run had to add to
get past session start, and what defeated the whole allowlist.

## Lane

- Backend `:8014`, DB `foundryx_service_s34`, `PUBLIC_BASE_URL=http://localhost:8014`,
  `FRONTEND_URL=http://localhost:3012`.
- **`CORS_ORIGINS` deliberately does NOT contain `http://localhost:3013` this run**
  (the S6 lane command had it). A real customer website is on the CHANNEL's
  allowlist and never in the service's own env CORS list, so leaving `:3013` in
  the env list would have hidden the fix's second half: the webchat public
  prefix answering its own CORS preflight. With `:3013` absent, Starlette's
  `CORSMiddleware` would have answered the loader's preflight
  `400 Disallowed CORS origin` and the POST would never have left the browser.
- Frontend `:3012`, fresh `rm -rf .next && npm run build`, `npx next start -p 3012`.
- Static host page `:3013` from `34-evidence/S6-fix/host/` (same snippet, same
  channel `wk_8b2ea66a6818437396f4924c32299a28`).
- `agent-browser --session s34` (visitor) and `--session s34admin` (agent,
  `demo@example.com`).

## Pre-flight curl proof (the exact hole, closed)

```
POST /session  Origin: http://localhost:3012 (the PANEL's own origin)  -> 404 {"detail":"Not found."}
POST /session  Origin: http://localhost:3013 (the allowlisted HOST)    -> 200 + ACAO: http://localhost:3013
OPTIONS /session Origin: http://localhost:3013 (not in env CORS_ORIGINS) -> 204 + ACAO echo,
                 allow-methods GET, POST, OPTIONS, allow-headers authorization, content-type,
                 Vary: Origin, NO Access-Control-Allow-Credentials
```

## Steps

1. **Host page, 1280px (01).** Opened `http://localhost:3013/`. The launcher
   bubble renders - the loader minted a session from the customer's origin with
   the app's own origin nowhere on the allowlist. Console clean, no page errors.
2. **Pre-chat + first message (02, 03).** Clicked the launcher, filled name
   `Fix Visitor 20260907204808` and email `fix.visitor.20260907204808@example.com`,
   sent "Loader-minted session 20260907204808 - can you see this?". The bubble
   and the greeting render; console clean.
3. **Agent sees it live (04).** Logged in at `:3012` as `demo@example.com` (real
   clicks from `/`, sidebar Omnichannel > Inbox). The thread is at the top of
   the list with the **Web chat** badge and the visitor's pre-chat name.
4. **Agent replies (05).** "Agent reply 20260907204808 - yes, received via the
   loader-minted session."
5. **Visitor receives it with NO reload (06 at 1280px, 07 at 375px).** The reply
   appears in the open panel over the existing transport.
6. **Token ownership + reload resume (08).**
   `Object.keys(window.localStorage)` on the HOST page (`:3013`, not the panel
   origin) is exactly `["fx-webchat-token:wk_8b2ea66a6818437396f4924c32299a28"]`
   - the loader owns the token, namespaced per widget key (AC-WEB-49/50).
   Reloaded the host page and re-opened the widget: the SAME thread comes back
   (both messages, no pre-chat re-ask).
7. **AC-WEB-66 first half - off-list origin (09).** Opened
   `http://127.0.0.1:3013/` (same page, genuinely different origin, NOT on the
   allowlist). **No iframe is injected at all** - no launcher, no panel, no copy,
   nothing. Backend log for that load: one
   `POST .../session -> 404 Not Found`, and no message route was ever reachable
   because no token was ever issued.
8. **Direct panel navigation (10).** Opened
   `http://localhost:3012/public/webchat/wk_8b2ea66a6818437396f4924c32299a28`
   with no loader anywhere. The document body renders EMPTY
   (`document.body.innerText.trim().length === 0`): no launcher, no error copy,
   no vendor string. The backend log shows only the Next middleware's own
   server-side `GET .../frame-policy` for that page load - **zero session
   starts**, so nothing exists server-side for a stranger who knows a widget key.
9. **375px (11, 12).** Host page launcher at 375px (non-clipped, tappable) and
   the agent thread at 375px (Web chat badge, transcript, presence line).

## Result

- **AC-WEB-66 first half: PASS** - and for the RIGHT reason this time: the
  allowlisted origin works while the off-list one gets nothing, with the app's
  own origin never added to the channel.
- **AC-WEB-65 core path: PASS** (send, live agent reply, reload resume). The
  agent-image half of AC-WEB-65 was not re-driven - it is untouched by this fix
  and was recorded in `../S6/README.md` steps 8 (screenshots 15-17).
- **AC-WEB-47 (quiet no-session state): PASS** - step 8.

## Screenshots

| File | What |
|---|---|
| `shots/01-host-1280-launcher.png` | Launcher on the allowlisted host page, 1280px |
| `shots/02-prechat-filled-1280.png` | Pre-chat name + email + first message typed |
| `shots/03-visitor-sent-1280.png` | Greeting + the visitor's sent message |
| `shots/04-agent-inbox-thread-1280.png` | The thread live in the agent inbox |
| `shots/05-agent-replied-1280.png` | Agent reply sent from the inbox composer |
| `shots/06-visitor-live-reply-1280.png` | Reply delivered to the visitor, no reload, 1280px |
| `shots/07-visitor-live-reply-375.png` | The same at 375px |
| `shots/08-visitor-reload-resumes-1280.png` | Same thread after a host-page reload |
| `shots/09-offlist-origin-no-widget-1280.png` | `127.0.0.1:3013` - no widget injected at all |
| `shots/10-direct-panel-navigation-blank-1280.png` | Panel URL opened directly - blank document |
| `shots/11-host-375-launcher.png` | Launcher at 375px |
| `shots/12-agent-thread-375.png` | Agent thread at 375px |

## Cleanup

- `:3013` static host server killed.
- Both `agent-browser` sessions (`s34`, `s34admin`) closed by name.
- `:8014` (with `FRONTEND_URL=http://localhost:3012`, and `:3013` NOT in
  `CORS_ORIGINS`) and `:3012` left running.
- The test channel's `allowedOrigins` was never modified - it is still
  `["http://localhost:3013"]`, exactly as AC-WEB-64 connected it.

## Noted, not fixed (out of scope for BL-SS-183)

Directly navigating to the panel URL shows `Foundryx` as the browser TAB TITLE
(the app's root metadata; the panel document itself renders nothing). A real
visitor never sees it - the panel is only ever rendered inside the loader's
iframe, where the tab belongs to the customer's page. Flagged for the reviewer
as a white-label nit that predates this fix (S4).
