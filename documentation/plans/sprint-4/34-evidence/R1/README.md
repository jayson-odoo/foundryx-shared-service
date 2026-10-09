# Plan 34 (A7b) review round 1 - live verification

Recorded 2026-09-07/08 against the s34 lane rebuilt on the review-round-1 fix commit (backend
`:8014`, DB `foundryx_service_s34`, module head `0022_omni_webchat_profile`; frontend `:3012`, fresh
`rm -rf .next && npm run build` + `npx next start -p 3012`), plus a dedicated static host-page server
on `:3013` (`documentation/plans/sprint-4/34-evidence/R1/host/index.html`, killed at the end of this
run). Real clicks via `agent-browser` (`s34p2` visitor session, `s34p2admin` agent session), curl for
the API-level probes. A dedicated channel (`R1 Probe <ts>`, widget key
`wk_170cf5bf8477456285555da25cc3108a`) was connected for this pass with `allowedOrigins:
["http://localhost:3013"]` and `preChat.askPhone: true` (needed to exercise B3), then disconnected at
the end - none of the shared demo/seed channels were mutated.

## D1 - storage-key drift gate

Fixed in `service_backend/app/storage_migration/registry.py` (`_NON_STORAGE_KEY_COLUMNS` gains
`"widget_key"` with a one-line comment). Re-run in isolation:

```
tests/test_storage_migration_registry.py            9 passed
tests/test_omnichannel_media_backfill.py             4 passed
```

`visitor_profile_json` (the B3 migration's new column) does not end in `_key`, so it is out of scope
for this drift gate - confirmed by reading `_is_storage_key_column`'s rule (`name.endswith("_key")`).

## Backend regression - the nine touched files + the storage files + WS, re-run one at a time

| File | Result |
|---|---|
| `tests/test_omnichannel_webchat_public.py` | 53 passed |
| `tests/test_omnichannel_webchat_outbound.py` | 15 passed |
| `tests/test_omnichannel_webchat_frame_policy.py` | 8 passed |
| `tests/test_omnichannel_webchat_hours_prechat_identity.py` | 22 passed |
| `tests/test_omnichannel_channels_webchat.py` | 28 passed |
| `tests/test_omnichannel_gateway_webchat.py` | 10 passed |
| `tests/test_omnichannel_contacts_module.py` | 38 passed |
| `tests/test_omnichannel_embed.py` | 36 passed |
| `tests/test_module_platform.py` | 17 passed |
| `tests/test_storage_migration_registry.py` | 9 passed |
| `tests/test_omnichannel_media_backfill.py` | 4 passed |
| `tests/test_omnichannel_ws.py` | 3 passed |

All match (or exceed, for the two storage files, which now pass instead of failing) the phase-1
coder's own counts. Zero failures, zero new skips.

## Frontend - touched vitest files re-run

| File | Result |
|---|---|
| `components/platform/conversation-drawer/contact-details-form.test.tsx` | 9 passed |
| `lib/channel-capabilities.test.ts` | 8 passed |
| `app/(protected)/omnichannel/settings/channels/components/webchat-identity-block.test.tsx` (new) | 3 passed |
| `services/webchat-visitor-service.real.test.ts` (new) | 5 passed |
| `components/platform/conversation-drawer/composer.channels.test.tsx` | 12 passed |
| `app/(protected)/omnichannel/settings/embed/embed-access.test.tsx` | 7 passed |
| `app/(protected)/omnichannel/settings/channels/components/use-channel-form.channels.test.tsx` | 4 passed |
| `components/platform/channel-connect-wizard/channel-connect-wizard.test.tsx` | 10 passed |

`npx eslint` on the 12 round-1-touched non-test files: **0 errors**, 2 pre-existing `jsx-a11y`
warnings on `composer.tsx` (unrelated categories, present before this round). `npx tsc --noEmit`
(whole project): 78 pre-existing errors elsewhere (autocount, workflow-doc, no-playwright guard,
storage-migration-service, broadcasts binding-editor - none touched by plan 34 round 1), **zero
errors in any plan-34 file** (grepped the full output for `webchat`/`omnichannel` - the one hit,
`binding-editor.test.tsx`'s `WhatsAppTemplate` cast, is an unrelated broadcasts file not touched by
this branch).

## Migration 0022

Applied directly against `foundryx_service_s34` via `run_module_migrations(engine, 'omnichannel')`
with `DATABASE_URL` pinned explicitly in the command's own environment (the worktree's `.env` is a
symlink to the main checkout's `.env`, which points at the wrong database - never touched):

```
module alembic current -> 0022_omni_webchat_profile   (was 0021_omni_webchat)
core alembic current    -> workflows_http_s31           (unchanged)
```

`psql -c '\d app_omnichannel.contact_channel_identities'` confirms `visitor_profile_json | json`
is present.

## Servers restarted on the new code

- `:8014` - killed the old pid (confirmed `cwd` = this worktree first), relaunched
  `uvicorn app.main:app --port 8014` with the exact env copied off the old process
  (`DATABASE_URL=...foundryx_service_s34`, `CELERY_TASK_ALWAYS_EAGER=true`, `CORS_ORIGINS` (no
  `:3013`), `CORS_ORIGIN_REGEX`, `PUBLIC_BASE_URL=http://localhost:8014`,
  `FRONTEND_URL=http://localhost:3012`, `ENVIRONMENT=development`). `curl -o /dev/null -w '%{http_code}'
  http://localhost:8014/docs` -> `200`.
- `:3012` - killed the old pid (cwd confirmed), `rm -rf .next && npm run build` (clean build, no
  errors), `npx next start -p 3012`. `curl -o /dev/null -w '%{http_code}' http://localhost:3012/` ->
  `200`.

## Live curl probes

### S9 - module-registered public CORS, scoped to the webchat prefix only

```
OPTIONS /public/omnichannel/webchat/<key>/session, Origin: http://localhost:3013
  -> 204, access-control-allow-origin: http://localhost:3013 (exact echo), vary: Origin

OPTIONS /public/omnichannel/webchat/<key>/session, Origin: http://evil.localhost:3013
  -> 204, NO access-control-allow-origin header at all

OPTIONS /omnichannel/conversations (non-webchat path), Origin: http://localhost:3013
  -> 400 "Disallowed CORS origin" (Starlette's own CORSMiddleware, which only knows this
     service's CORS_ORIGINS env - :3013 is not in it). Unaffected by the new module-registered
     prefix middleware, confirming it is scoped to exactly the webchat public prefix.
```
Full transcript: `probes-s9.txt`.

### S1 - typed 422s, no 500s, on non-string JSON scalars

```
POST /session {"token":123}                          -> 404 {"detail":"Not found."}
POST /session (unknown widget key)                    -> 404 {"detail":"Not found."}  (byte-identical)
POST /messages {"text":"","hp":1}                     -> 422 {"error":{"code":"invalid_request",...,"fieldErrors":{"hp":"Input should be a valid string"}}}
POST /messages {"text":[]}                            -> 422 {"error":{"code":"invalid_request",...,"fieldErrors":{"text":"Input should be a valid string"}}}
```
No `AttributeError`, no 500, on either non-string scalar. Full transcripts: `probes-s1.txt`,
`probes-s1b.txt`.

### S2 - honeypot returns the real success shape, stores nothing

```
POST /messages {"text":"x","hp":"bot"}   -> 201 {"id":...,"direction":"in","text":"x","media":null,
                                              "quickReplies":null,"agentName":null,"createdAt":...,"status":null}
POST /messages {"text":"real message for R1 probe", preChat:{...}}
                                          -> 201 {"id":...,"direction":"in","text":"real message ...",
                                              "media":null,"quickReplies":null,"agentName":null,
                                              "createdAt":...,"status":null}
```
Identical key set on both. `psql` confirms exactly ONE `conversation_messages` row for the channel
(the real one) - the honeypot hit wrote nothing. Full transcript: `probes-s2.txt`.

### B3 - unverified pre-chat profile never touches the stitch key

First message carried `preChat: {"name":"R1 Visitor","email":"r1visitor@example.com","phone":"+60123456789"}`.

```
contacts:                       first_name=R1, last_name=Visitor, email=NULL, phone=NULL, phone_digits=NULL
contact_channel_identities:     visitor_profile_json = {"name":"R1 Visitor","email":"r1visitor@example.com","phone":"+60123456789"}
GET /omnichannel/contacts/<id> (authed): "phone": null, "email": null,
                                          "visitorProfile": {"name":"R1 Visitor","email":"r1visitor@example.com","phone":"+60123456789"}
```
Confirms the contact's `phone`/`phone_digits` (the WhatsApp inbound stitch key) are never written from
pre-chat; the unverified values live only on the identity's `visitor_profile_json` and surface via
`ThreadItem.visitorProfile`. Also re-verified end-to-end through the browser flow below (a second,
independent message) with the same result.

### B1 - in-flight delivery status never 500s the visitor read (not observable live)

Both `:8014` and the pytest suite run `CELERY_TASK_ALWAYS_EAGER=true`, so a real agent reply always
lands at `SENT` before any visitor read can observe `QUEUED`/`SENDING` - there is no way to force the
in-flight window live in this lane, exactly as the review noted. Covered by
`tests/test_omnichannel_webchat_public.py::test_in_flight_delivery_status_still_returns_200_on_the_visitor_read`
and `::test_visitor_projection_maps_in_flight_delivery_status_to_null` (both green, part of the 53/53
above), which construct `QUEUED`/`SENDING`/an unrecognised value directly and assert `200` / `None`.

### B2 - channel-scoped visitor relay (not independently re-driven live; code + pytest verified)

Reproducing the cross-channel WhatsApp-stitch scenario live needs a WhatsApp-connected sandbox number,
which this lane does not have. Verified by reading `webchat_projection.visitor_frame` (now requires
`frame["message"]["channelId"] == principal.visitor_channel_id` before projecting) and by
`tests/test_omnichannel_webchat_public.py::test_visitor_frame_drops_a_frame_from_another_channel_on_the_same_contact`
and `::test_visitor_frame_fails_closed_when_the_frame_carries_no_channel` (both green, part of the
53/53 above).

### S8 - `frame-policy` is cached and unthrottled-but-cheap

```
GET /public/omnichannel/webchat/<key>/frame-policy   (1st call)  -> 200 {"allowedOrigins":["http://localhost:3013"]}
GET /public/omnichannel/webchat/<key>/frame-policy   (2nd call)  -> 200 (identical body)
GET /public/omnichannel/webchat/wk_totallybogus.../frame-policy  -> 200 {"allowedOrigins":[]}
```
The backend log is definitive: the FIRST call issued a `SELECT ... FROM app_omnichannel.channels
WHERE widget_key = ...` (visible in `/tmp/s34-backend.log` at `06:34:15,375`); the immediately
following SECOND call to the SAME widget key logged its `200 OK` with **no SQL query in between** -
served entirely from the 60s in-memory cache. The THIRD call, to a different (unknown) widget key,
issued its own fresh `SELECT` (cache miss, different key) and returned `[]` for the unresolved key.
Full transcript: `probes-s8.txt`.

### S7 - a valid-token session resume does not spend an IP throttle token

```
psql auth_throttle (scope='webchat', key='ip:127.0.0.1'): fail_count = 8   (before)
POST /session {"token": "<valid, unexpired>"}             -> 200, full config + transcript replayed
psql auth_throttle (scope='webchat', key='ip:127.0.0.1'): fail_count = 8   (after, UNCHANGED)
```
Confirms the resume path does not spend an IP token (the per-visitor bucket is the one that
legitimately increments per message, separately, as seen in the same table's `v:vis_*` rows).

## Browser check - real clicks, 375px and 1280px

- **1280px visitor flow** (`s34p2`, host page `:3013`): opened the launcher, pre-chat form asked for
  Name/Email/Phone (channel's `askPhone: true`), filled `Browser Visitor R1` /
  `browser.r1@example.com` / `+60129998888`, typed and sent "Hello, I need help with my order".
  `shots/01-visitor-sent-1280.png`.
- **1280px agent inbox** (`s34p2admin`, `demo@example.com`): logged in, opened Omnichannel > Inbox
  from the sidebar (real clicks - expand the Omnichannel accordion, click Inbox), the new thread
  "Browser Visitor R1" appeared at the top with a **Web chat** badge and an **Online now** presence
  marker. `shots/02-agent-thread-1280.png`.
- **1280px "Visitor provided" block**: opened the contact details panel (the "Toggle contact panel"
  button next to the channel badges). The panel's own `First name`/`Last name`/`Phone`/`Email` fields
  show `Browser` / `Visitor R1` / `-` / `-` (phone and email genuinely null on the contact record);
  a separate **Visitor provided** section below shows `Name: Browser Visitor R1`,
  `Email: browser.r1@example.com`, `Phone: +60129998888` - the unverified pre-chat values, visually
  distinguished from the verified contact fields. `shots/03-agent-details-visitor-provided-1280.png`.
- **375px visitor panel**: same host page at 375x812 - the panel fills the viewport width, transcript
  and composer both usable, no clipping. `shots/04-visitor-375.png`.
- **375px agent details panel**: the same "Visitor provided" block re-screenshotted at 375px (the
  contact panel becomes the full-width view at this breakpoint) - same three fields, fully legible,
  no truncation. `shots/05-agent-thread-375.png`.

Two clicks in this pass (the inbox row selection, the "Toggle contact panel" button) did not register
through the CDP-driven `agent-browser click` command on the first few attempts - a UI sidebar
accordion toggle and a list-row selection both needed a manually dispatched
`pointerdown/mousedown/pointerup/mouseup/click` sequence via `eval` to land (visible screenshots
confirm the intended UI state was reached both times; this is a browser-automation-tooling
observation, not an application defect - the same rows respond normally to a human mouse click, and
no console error was logged on either occasion).

**Not verified this pass:** a `channels.read`-only (no `channels.manage`) user's view of the same
surfaces - no such role is seeded in this lane and none was created for this pass (out of scope per
the brief). AC-WEB-25/session-start-writes-zero-rows and the honeypot's zero-write claim were
cross-checked via `psql` row counts rather than a UI action, consistent with the rest of this
plan's evidence style.

## Cleanup

- The probe channel `R1 Probe <ts>` (widget key `wk_170cf5bf8477456285555da25cc3108a`) was
  disconnected via `POST /omnichannel/channels/disconnect` at the end of this pass.
- `agent-browser` sessions `s34p2` and `s34p2admin` closed by name (never `close --all`).
- The dedicated `:3013` static host server for this pass was killed.
- `:8014` and `:3012` are left running on the review-round-1 code for the next reader.
