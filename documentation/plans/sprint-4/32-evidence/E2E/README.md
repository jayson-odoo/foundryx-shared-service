# Plan 32 (A7a) - Independent tester E2E evidence run

**Run by:** independent tester (this pass), NOT the S6 coder. Replaces nothing in `32-evidence/S0/`
and `32-evidence/S6/` (those are the coder's own evidence, kept as-is per the brief); this directory
is the independent verification pass cited by `32-omnichannel-channels-messenger-instagram-test-report.md`.

**Date:** 2026-09-07. **Branch/HEAD:** `sprint-4/32-channels-messenger-instagram` @ `e4ac64ef`.
**Lane:** backend `:8013` (DB `foundryx_service_s32`), frontend `:3011` (prod build, `npx next start`).
Both lanes verified current against HEAD before testing (backend source mtimes predate the 17:42
server start; frontend `.next/BUILD_ID` at 17:57 postdates every non-test frontend source file).

**Tool:** `agent-browser` CLI, sessions `s32t` (operator + dedicated-tenant-A wizard/detail flows),
`s32v` (permission-gate viewer login), `s32b` (dedicated-tenant-B cross-tenant probe), `s32d`
(default/dev tenant - inbox, gateway, workflow, WhatsApp regression). Every session closed
(`agent-browser --session <name> close`) as soon as its leg of the run finished; never more than one
of mine open at a time bar the brief cross-tenant window (closed immediately after). Viewports 375
and 1280 per new/changed surface. Real clicks from `/` via the sidebar for every core AC-CHN-62 step;
a handful of auxiliary/setup steps (platform tenant list, workflow list breadcrumbs) used `open
<url>` for efficiency navigating already-authenticated admin console pages that are not part of the
AC-CHN-62 contract itself - called out per-step below.

## Setup performed outside the UI (verbatim)

1. **Dedicated tenant A** (`e2e-s32-20260907184649`) - operator login (`platform@example.com` /
   `platform1234` @ `platform.localhost:3011`) then `POST /platform/tenants` (`TenantProvisionRequest`)
   with a timestamped slug/admin email. Omnichannel installed via real clicks (Tenant detail > Modules
   tab > Omnichannel card > Actions > Install).
2. **Dedicated tenant B** (`e2e-s32b-20260907185457`) - same recipe, for the cross-tenant probe.
3. **Viewer role + user** (tenant A) - `PATCH /roles/{viewerRoleId}` with
   `permissionKeys: [channels.read, conversations.read, dashboard.read]` (no `channels.manage`), then
   `POST /users` with that role. The invite email landed in `email_outbox` (dev fallback, no SMTP) -
   read the accept-invite token straight from the DB row's `text_body` and called
   `POST /auth/set-password {token, password}` to activate the account (invite emails are not
   click-through-able in this rig; this is the standard dev-mode workaround, not a shortcut around the
   permission gate itself - the gate check that follows IS a real browser session with a real login).
4. **Workspace API key** - `POST /omnichannel/workspaces/{wsId}/api-keys` on the default tenant
   (demo admin token) for the gateway curls (`fxw_live_...`, `Authorization: Bearer` per the guide).
5. **Webhook curls** - every inbound Meta payload (Messenger `message`, `delivery`, `read`,
   `story_mention`, unreachable-media `image`, a fresh-PSID `message`) posted to
   `POST /omnichannel/webhooks/<channel_id>` with no `X-Hub-Signature-256` (dev fail-open, no
   `META_APP_SECRET` configured, `ENVIRONMENT=development` - the documented dev-safe rule).
   `delivery`/`read` watermarks are Meta epoch-**milliseconds** (`_handle_watermark` divides by 1000);
   an epoch-seconds watermark silently under-shoots and never advances the receipt - noted as a gotcha,
   not a defect (Meta's own contract is ms).
6. **A local `python3 http.server` receiver** was stood up on `127.0.0.1:8999` to attempt a live
   consumer-webhook delivery; the platform's SSRF host guard refuses non-HTTPS callback URLs even in
   development (`Callback URL must use https://.`), so a live delivered-payload capture was not
   possible without standing up local TLS - DEFERRED, substituted with a code-path + wire-shape proof
   instead (see AC-CHN-56/57 in the test report).

## Screenshot index

`01`-`08`: dedicated-tenant connect wizard (Messenger via `pg-701`, Instagram professional-account
picker correctly empty because both canned IG-linked pages are already connected service-wide - see
the test report's AC-CHN-02 note), channel list Type column, Messenger channel detail (no
Templates/no Profile), permission-gate (Viewer role, no Connect control) at both viewports.
`09`-`18`: default-tenant inbox - FB/IG thread icons, `cnt-fb-001` send + delivery/read receipts,
`cnt-fb-002` human-agent-window send, `cnt-ig-002` locked state (per-type copy, no template
affordance) at both viewports, a brand-new inbound Messenger contact appearing live via WebSocket,
an Instagram `story_mention` placeholder bubble, a media-unavailable placeholder for an unreachable
attachment URL.
`19`-`28`: workflow editor - real React-Flow mouse-drag of the `Incoming omnichannel message` trigger
onto the canvas (click-only and `agent-browser drag` both no-opped; a real `mouse move/down/.../up`
sequence was required, confirming the standing memory note), the new `channelType` SearchSelect field
set to Messenger, publish, the separate `Active` switch (workflow Settings tab - NOT part of Publish,
a pre-existing platform mechanic unrelated to plan 32, documented here as a click-path note), and the
Logs tab showing exactly one `Success` run after a Messenger webhook with a same-instant WhatsApp
webhook producing none.
`29`-`30`: WhatsApp regression - the existing demo thread's header still reads "WhatsApp", still
sends, `cswExpiresAt` still resolves to a real value via the API.
`31`: Instagram channel detail (no Templates/no Profile) at both viewports.

## Residue left behind (intentional, timestamped)

- Tenants `e2e-s32-20260907184649`, `e2e-s32b-20260907185457` (both with Omnichannel installed).
- Tenant A: one Messenger channel (`pg-701`, "Foundryx Events Co.").
- Default tenant: one Viewer-role user `e2e-viewer-20260907184649@example.com`, one workspace API key
  `s32-tester-key`, several test contacts/messages (`WA Regression Tester[ 2]`, the new-PSID
  "Contact" rows, a `story_mention` bubble on Maya Rivera's thread, a media-unavailable bubble on
  Jordan Lee's thread), and one workflow `S32 E2E Messenger trigger 1788779377` (published + active).
  None of this collides with `chn-demo`/`chn-demo-fb`/`chn-demo-ig`'s own fixed-id seed rows.
