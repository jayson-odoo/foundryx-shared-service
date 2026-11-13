# Plan 34 S5 evidence - business hours, pre-chat write-if-empty, host identity, dev seed

Backend :8014, DB `foundryx_service_s34`, `ENVIRONMENT=development`. All curls run live
against a fresh restart of the lane's own uvicorn after the S5 code changes.

## 1. Dev seed applied to the live DB (no drop)

```
$ psql foundryx_service_s34 -c "select id, channel_type, widget_key, is_active from app_omnichannel.channels where id='chn-demo-web';"
      id      | channel_type |            widget_key             | is_active
--------------+--------------+-----------------------------------+-----------
 chn-demo-web | WEBCHAT      | wk_demo00000000000000000000000000 | t

$ psql foundryx_service_s34 -c "select id, first_name, email from app_omnichannel.contacts where id in ('cnt-web-001','cnt-web-002');"
     id      | first_name |       email
-------------+------------+-------------------
 cnt-web-001 |            |
 cnt-web-002 | Jamie      | jamie@example.com
```

## 2. Host identity assertion - valid HMAC resolves `host:<userRef>`

```
$ python3 -c "import hmac,hashlib; print(hmac.new(b'whsec_demo0000000000000000000000000000', b'demo-live-probe-1', hashlib.sha256).hexdigest())"
8e30859249711245708e9db88de3cb19790c9e9bd56d0c50090c85350c7bc9f5

$ curl -s -X POST http://localhost:8014/public/omnichannel/webchat/wk_demo00000000000000000000000000/session \
    -H "Origin: http://localhost:3012" -H "Content-Type: application/json" \
    -d '{"identity": {"userRef": "demo-live-probe-1", "hash": "8e30859249711245708e9db88de3cb19790c9e9bd56d0c50090c85350c7bc9f5"}}'
{
  "token": "<jwt, decoded claims include "identityKey":"host:demo-live-probe-1">",
  "visitorId": "vis_7dea3d4cb5b945bc9c1a716928ae71dd",
  "online": true,
  "messages": [],
  ...
}
```
Decoded JWT payload (base64 middle segment) confirms `"identityKey":"host:demo-live-probe-1"`.

## 3. Garbage hash - byte-shape-identical anonymous session, no error

```
$ curl -s -X POST http://localhost:8014/public/omnichannel/webchat/wk_demo00000000000000000000000000/session \
    -H "Origin: http://localhost:3012" -H "Content-Type: application/json" \
    -d '{"identity": {"userRef": "demo-live-probe-1", "hash": "0000...0000"}}'
{
  "token": "<jwt, decoded identityKey = "visitor:vis_053da10601a14d73ba8cd32cc594dade">",
  "visitorId": "vis_053da10601a14d73ba8cd32cc594dade",
  "online": true,
  "messages": [],
  ...
}
```
Same 200 shape as request 2 - `identity` failed verification and was silently ignored;
the session proceeded anonymously (AC-WEB-56). No `error`/`code` field anywhere in the body.

## 4. Pre-chat write-if-empty on the FIRST message

```
$ TOKEN=$(curl -s -X POST .../session -d '{}' | jq -r .token)
$ curl -s -X POST .../messages -H "Authorization: Bearer $TOKEN" \
    -d '{"text": "Hi, evidence probe message 1", "preChat": {"name": "Riley Probe", "email": "riley@example.com"}}'
{"id": "6354ac17-...", "direction": "in", "text": "Hi, evidence probe message 1", ...}

$ psql foundryx_service_s34 -c "select first_name, email from app_omnichannel.contacts order by created_at desc limit 1;"
 first_name |       email
------------+-------------------
 Riley      | riley@example.com
```

## 5. Second message with a DIFFERENT name never overwrites

```
$ curl -s -X POST .../messages -H "Authorization: Bearer $TOKEN" \
    -d '{"text": "evidence probe message 2", "preChat": {"name": "Someone Else"}}'
{"id": "d23f8db2-...", "direction": "in", "text": "evidence probe message 2", ...}

$ psql foundryx_service_s34 -c "select first_name, email from app_omnichannel.contacts where email='riley@example.com';"
 first_name |       email
------------+-------------------
 Riley      | riley@example.com     -- UNCHANGED
```

## 6. Business hours -> `online` flag (AC-WEB-52)

Unconfigured workspace (default demo tenant, before any PUT):
`online: true` (see request 1/2 above - both show `"online": true"` with no
business-hours row present).

Configured, all-day windows empty (closed):

```
$ curl -s -X PUT http://localhost:8014/omnichannel/workspaces/<ws>/business-hours \
    -H "Authorization: Bearer <demo admin>" \
    -d '{"timezone":"UTC","windows":{"mon":[],"tue":[],"wed":[],"thu":[],"fri":[],"sat":[],"sun":[]}}'
{"workspaceId": "...", "timezone": "UTC", "windows": {...all empty...}}

$ curl -s -X POST .../session -d '{}'
{"online": false, ...}
```

Restored to unconfigured afterwards (`DELETE FROM app_omnichannel.omnichannel_settings
WHERE workspace_id = '<ws>'`) so the demo tenant is not left "offline" for S6.
Re-check: `online: true` again.

## Pytest (this slice's own file + the two named regression files, one invocation each)

```
tests/test_omnichannel_webchat_hours_prechat_identity.py   18 passed
tests/test_omnichannel_webchat_public.py                   33 passed (unedited assertions; _session() gained an optional identity= kwarg)
tests/test_omnichannel_webchat_outbound.py                 12 passed
tests/test_omnichannel_channels_webchat.py                  26 passed
tests/test_omnichannel_business_hours.py                    14 passed
tests/test_omnichannel_conversation_events.py                21 passed
tests/test_omnichannel_channels_messenger.py
  + tests/test_omnichannel_channels_instagram.py             64 passed
tests/test_omnichannel_channels_connect.py                  22 passed
```

## Vitest

```
components/platform/webchat-panel/webchat-panel.test.tsx   4 passed (new - AC-WEB-53)
components/platform/webchat-panel/prechat-step.test.tsx    5 passed (regression, unedited)
hooks/use-visitor-chat.test.ts                              8 passed (regression, unedited)
```

`npx eslint components/platform/webchat-panel/webchat-panel.tsx
components/platform/webchat-panel/webchat-panel.test.tsx` - clean, 0 errors/warnings.

## Screenshot - offline greeting, live, 375px (`offline-greeting-375.png`)

The admin+visitor trios stay MOCK-bound per S4's own decision (the official swap is
S6/AC-WEB-63) - `webchat-visitor-service.ts` was temporarily flipped to
`realWebchatVisitorService` for this ONE recorded run (mirroring S4's own commit-body
precedent exactly), rebuilt, screenshotted against the live :8014 backend with the demo
default workspace's business hours set to all-closed, then reverted (`git diff` on the
file is empty) and rebuilt back to the mock-bound state before finishing this slice.

Steps: set `chn-demo-web`'s workspace business hours to all-day-closed via
`PUT /omnichannel/workspaces/{id}/business-hours` -> `agent-browser --session s34` open
`http://localhost:3012/public/webchat/wk_demo00000000000000000000000000` at 375x812 ->
click "Open chat" -> page text shows "We're offline right now - leave a message and
we'll reply." (the channel's `offlineGreeting`, not the online `greeting`) on the
pre-chat step (askName/askEmail on for this seeded channel) -> screenshot -> business
hours deleted again (restored to unconfigured, `online` back to `true`).

Zero console errors/warnings during the run (`agent-browser console` empty).
