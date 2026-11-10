# Plan 32 (A7a) - Slice S0 agent-browser evidence

Run date: 2026-09-07. Session `s32c`, real clicks from `/` (login, sidebar, buttons); a
motion-wrapped sidebar/breadcrumb `<a>` needed the trusted-pointer-event sequence
(`pointerdown -> mousedown -> pointerup -> mouseup -> click`) dispatched via `agent-browser eval`
- plain `click @ref` silently no-ops on those links per the known plan-23 motion-wrapper gotcha.
Plain buttons (`Connect channel`, dropdown options, dialog buttons) worked with normal
`agent-browser click @ref`.

Lane: backend `http://localhost:8013` (DB `foundryx_service_s32`), frontend `http://localhost:3011`
(`npx next start -p 3011`, fresh `rm -rf .next && npm run build`). Logged in as
`demo@example.com` / `demo1234` (tenant `default`).

## Scope of this run (S0 = frontend on mocks; no Messenger/Instagram backend yet)

`channelService` / `conversationService` / `onboardingService.completeOnboarding` /
`manualConnect` are already real-bound in this codebase (WhatsApp shipped past Phase A in
earlier plans). Plan 32 S0 adds NEW mock-only pieces: `onboardingService.listMetaPages` /
`connectMetaChannel` (S0 MOCK, swapped to real in S6 per AC-CHN-59) and the
`channel-service.mock.ts` / `conversation-service.mock.ts` seed data used by vitest
(`AC-CHN-10`). This run demonstrates everything that is live-clickable today:

- the wizard's new channel-type step and the Messenger/Instagram page-selection step (driven by
  the mock `listMetaPages`/`connectMetaChannel`, which run regardless of what the real backend
  returns for the channel list);
- the channels list "Type" column/badge, and the WhatsApp channel form's unchanged 4 tabs;
- the real inbox/composer against the real seeded WhatsApp demo thread (no regression from the
  new `capabilities`/`humanAgentWindowOpen` props, which default to the WhatsApp record).

What this run does NOT show live (backend gap is by design until S1/S3/S4/S6 land, not a defect):
a Messenger/Instagram channel PERSISTING into the real channels list after "Done" (the mock
channel exists only in the frontend server's in-memory mock store); the Messenger/Instagram
channel form's tab filtering against a REAL channel; the composer's three window states against a
real Messenger/Instagram thread. All of these are covered by vitest instead (see the coder's
report) and are the explicit target of the S6 mock-to-real swap + the AC-CHN-62 E2E run.

AC-CHN-11 (permission gating: `channels.manage`/`channels.read`) is unchanged by this slice
(no new permission key) and was not re-verified live with a second constrained user in this
smoke run - it rides the existing `useCan()`/backend-gate pattern used everywhere else.

## Screens (paired 1280px / 375px where the same state was captured at both)

1. `01-channels-list-1280.png` - Channels list with the new **Type** column (WhatsApp badge) next
   to the existing Status/Connected columns, Resource shell unchanged.
2. `02-wizard-type-step-1280.png` - Connect wizard intro: **Channel type** `SearchSelect`
   (defaulted to WhatsApp) + **Attach to workspace** `SearchSelect` (both replace the old bare
   `<Select>`), "Set up manually" link (WhatsApp-only).
3. `03-wizard-type-options-1280.png` - Channel type dropdown open: exactly WhatsApp / Messenger /
   Instagram offered (foolproof-UI - no Douyin/Xiaohongshu).
4. `04-wizard-messenger-selected-1280.png` - Messenger selected: manual-connect link correctly
   gone (D-A7-14, OAuth-only for Messenger/Instagram).
5. `05-wizard-messenger-page-select-1280.png` - Simulated "Connect with Messenger" dialog (the
   SAME `MockEmbeddedSignupDialog` WhatsApp uses, extended type-aware): offers "Foundryx
   Concierge" and "Foundryx VIP Desk" - **"Foundryx Events Co." (`pg-701`) is correctly excluded**
   because it is already bound to the seeded sandbox `chn-fb-001` channel (AC-CHN-02).
6. `06-wizard-connected-1280.png` - "Sandbox channel created" success state after Authorize.
7. `07-channel-form-whatsapp-tabs-1280.png` - existing WhatsApp channel (`chn-demo`) detail form:
   Configuration / Templates / Profile / Webhooks - all 4 tabs present and unchanged (AC-CHN-05
   only filters Templates+Profile for FACEBOOK/INSTAGRAM, never WhatsApp).
8. `08-channel-form-whatsapp-375.png` - same page at 375px: tabs + form rows reflow, no clipping,
   no horizontal scroll.
9. `09-channels-list-375.png` - Channels list at 375px: Type badge collapses into the row
   subtitle (existing responsive pattern), Connect button + search + segmented control all
   reachable.
10. `10-wizard-type-step-375.png` - wizard intro at 375px, both SearchSelects full-width, no
    overlap.
11. `11-wizard-instagram-page-select-375.png` - simulated "Connect with Instagram" dialog at
    375px: offers `foundryx.concierge` ("Linked to Foundryx Concierge") - `foundryx.events`
    (`ig-701`) is excluded (already bound to seeded `chn-ig-001`); the option row carries the
    account username + linked-page caption, matching AC-CHN-02's Instagram rule (D-A7-14).
12. `12-wizard-instagram-connected-375.png` - Instagram sandbox-connected success state at 375px.
13. `13-inbox-whatsapp-thread-1280.png` - Inbox against the real seeded WhatsApp demo data:
    thread-list rows carry the new channel-type icon chip (small badge, bottom-right of the
    avatar, AC-CHN-09) and the composer (capabilities defaulted to WhatsApp) is fully functional -
    attach menu, emoji, quick replies, mic, all present exactly as before.
14. `14-inbox-whatsapp-thread-375.png` - same thread at 375px: header, tabs, bubbles, composer all
    reflow without horizontal scroll. (Pre-existing, unrelated to this slice: the composer
    placeholder text wraps to a 3rd line and its last word clips at this width - present before
    plan 32 too, not introduced by the `capabilities` prop change; not filed as a plan-32 defect.)

## Console

`agent-browser console` was checked after every navigation across the whole run (login, channel
list, both wizard flows at both viewports, WhatsApp channel form, inbox thread open) - zero
console errors or warnings at any point (one earlier `NextAuth CLIENT_FETCH_ERROR` was a stale
message from before `.env.local` picked up `NEXTAUTH_URL`/`NEXTAUTH_SECRET` for port 3011; cleared
and confirmed clean afterward).

## Note on the shared in-memory mock store

The Messenger connect flow (screenshot 5) was run once against a freshly-started frontend
process; the subsequent Instagram flow (screenshots 11-12) required a `.next` restart to reset
the mock module's in-memory state, because a mid-session Messenger "Authorize" on `pg-702`
mutates the SAME process-wide `channel-service.mock.ts` store `mockMetaPageOptions` reads (the
already-connected filter is doing exactly its job - it also marks the page just consumed as
unavailable on the next `/pages` read within the same process, mirroring the real backend's
eventual behaviour). Not a bug; noted for whoever runs the S6 recorded E2E so they seed/restart
between scripted flows that must see a specific page list.
