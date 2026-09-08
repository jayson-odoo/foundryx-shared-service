# Plan 34 (A7b) - Slice S0 agent-browser evidence

Run date: 2026-09-07. Session `s34c`, real clicks from `/` (login, sidebar, dialog buttons,
SearchSelect popovers). Login was a form submit (real inputs), not credential vault; navigation
was via sidebar link clicks throughout, never a URL shortcut.

Lane: backend `http://localhost:8014` (DB `foundryx_service_s34`), frontend `http://localhost:3012`
(`npx next start -p 3012`, fresh `rm -rf .next && npm run build`). Logged in as
`demo@example.com` / `demo1234` (tenant `default`).

## Scope of this run (S0 = frontend on mocks; no `WEBCHAT` backend yet)

`channelService` / `conversationService` / `onboardingService` are already real-bound (WhatsApp /
Messenger / Instagram shipped past Phase A in earlier plans). Plan 34 S0 adds NEW mock-only
pieces: `webchatService` (S0 MOCK, tagged for swap to real in S6 per AC-WEB-63) and the
`channel-service.mock.ts` seed data (`chn-web-001`) used by vitest. This run demonstrates
everything that is live-clickable today against the mock-bound `webchatService`:

- the connect wizard's new Web chat option (AC-WEB-01), its reduced form - name + workspace +
  the reused `origins-editor.tsx` (AC-WEB-02) - and a full connect round-trip against the mock,
  including the reveal-once widget secret (AC-WEB-06/18 shape, mock data);
- the Channels list "Type" filter offering **Web chat** as a fourth checkbox option (AC-WEB-09),
  derived from the same `CHANNEL_TYPES` catalog as the wizard (no second hardcoded list);
- the existing WhatsApp channel's detail-form tabs (Configuration/Templates/Profile/Webhooks) and
  the real seeded WhatsApp inbox thread + composer - both UNCHANGED, proving the `reengageMode`
  bypass added to `composer.tsx` (AC-WEB-08) and the tab-filtering rule extended in
  `use-channel-form.tsx` (AC-WEB-03) do not regress the shipped channel types.

What this run does NOT show live (backend gap is by design until S1/S6 land, not a defect): a
`WEBCHAT` channel PERSISTING into the real channels list after "Done" (the mock channel exists
only in the frontend server's in-memory mock store, `channelService.list` is real-bound and reads
Postgres); the Widget tab (appearance/greeting/pre-chat/snippet/rotate-secret) and the
Configuration tab's widget-key/origins block against a REAL, navigable `WEBCHAT` channel record
(there is no such record in Postgres yet); the composer's neutral presence marker against a real
`WEBCHAT` thread. All of these are covered by vitest instead (channel-widget-tab.test.tsx,
composer.channels.test.tsx's new "Web chat has no messaging window" suite,
use-channel-form.channels.test.tsx's Web chat tab-filtering case) and are the explicit target of
the S6 mock-to-real swap + the AC-WEB-64/65/66 E2E runs. This mirrors exactly the same disclosed
gap plan 32 / A7a's S0 evidence run left for Messenger/Instagram, which S3/S4/S6 later closed.

Permission gating (`channels.manage`/`channels.read`) is unchanged by this slice (no new
permission key, D-A7B-28) and was not re-verified live with a second constrained user - it rides
the existing `useCan()`/backend-gate pattern used everywhere else.

## Screens

1. `00-logged-in-home-1280.png` - post-login dashboard, confirming the demo session.
2. `01-channels-list-1280.png` - Channels list, 3 existing sandbox channels (WhatsApp / Messenger
   / Instagram), unchanged Resource-shell chrome.
3. `02-wizard-intro-1280.png` - Connect wizard intro: **Channel type** defaulted to WhatsApp.
4. `03-wizard-type-options-1280.png` - Channel type dropdown open: **WhatsApp / Messenger /
   Instagram / Web chat** - exactly the four implemented types, sourced from the ONE
   `CHANNEL_TYPES` array (AC-WEB-01; no Douyin/Xiaohongshu, foolproof-UI).
5. `04-wizard-webchat-fields-1280.png` - Web chat selected: the Meta OAuth/page-selection steps
   are gone entirely, replaced by **Channel name** + the reused `OriginsEditor` in its controlled
   `bare` mode (AC-WEB-01/02); no "app not configured" warning and no "Set up manually" link
   (both Meta-only affordances, correctly absent for a channel with no external provider).
6. `05-wizard-webchat-valid-1280.png` - name filled, one origin added (chip + Remove control);
   **Connect** transitions from disabled to enabled the moment a name AND a valid origin are both
   present (AC-WEB-02).
7. `06-wizard-connected-secret-1280.png` - "Channel connected" success state: the mock-provisioned
   widget secret rendered once via the reused `CopyField`, matching AC-WEB-06's "reveal exactly
   once" contract (this is the connect-time reveal; the same reused component backs the Widget
   tab's rotate-secret dialog, covered by vitest).
8. `07-channels-type-filter-1280.png` - Channels list Filters panel, Type = "is any of": **Web
   chat is a fourth checkbox option** alongside WhatsApp/Messenger/Instagram (AC-WEB-09), same
   `CHANNEL_TYPE_LABELS` catalog the wizard and the list column already use.
9. `08-channel-form-whatsapp-tabs-1280.png` - existing WhatsApp channel (`chn-demo`) detail form:
   Configuration / Templates / Profile / Webhooks - all 4 tabs present and unchanged, proving the
   Widget-tab / Templates+Profile-filtering addition (AC-WEB-03) only fires for `channelType ===
   'WEBCHAT'`.
10. `09-inbox-whatsapp-thread-1280.png` - real seeded WhatsApp thread (Sarah Chen): composer fully
    functional (attach, emoji, quick replies unaffected), no presence marker rendered - confirms
    `composer.tsx`'s new `hasWindow`/presence-marker logic is a no-op for `reengageMode !== 'none'`.
11. `10-channels-list-375.png` - Channels list at 375px: no clipping, no horizontal scroll, Connect
    button/search/segmented control all reachable (unchanged responsive pattern).
12. `11-wizard-webchat-375.png` - Web chat connect step at 375px: Channel type, Attach to
    workspace, Channel name, origin input + Add, "No origins added yet.", Connect/Cancel - every
    field full-width, nothing clipped, nothing requiring horizontal scroll.

## Console

`agent-browser console` was checked after the full run (login, channels list, wizard open through
all four type options, Web chat fields, connect + secret reveal, the Filters panel's Type value
picker, an existing WhatsApp channel's tabs, a real WhatsApp inbox thread, a mobile-viewport pass
through the wizard) - **zero console errors**; the one warning present
(`Missing Description or aria-describedby for {DialogContent}`) is a pre-existing class already
present on this codebase's other reveal-once dialogs (e.g. `WebhookEndpointDialog`, confirmed via
its own passing vitest suite carrying the identical stderr line) - not introduced by this slice.

## Recovery note

The Channels list "Filters" panel's Type value-picker (a `MultiSelect` popover) did not dismiss on
`Escape` or a synthetic `body.click()` partway through this run (a pre-existing Radix/cmdk
interaction quirk unrelated to this slice's own code, since the SAME picker is reused verbatim
from `use-channels-list-config.tsx`'s pre-existing filter machinery); `agent-browser reload`
cleanly reset the page. Noted for whoever runs the S6 recorded E2E.
