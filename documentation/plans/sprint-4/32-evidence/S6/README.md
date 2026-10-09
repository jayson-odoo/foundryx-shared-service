# Plan 32 (A7a) Slice S6 - evidence run log

Recorded `agent-browser` runs against the live s32 lane (backend `:8013`, DATABASE_URL =
`postgresql://foundryx:foundryx@localhost:5432/foundryx_service_s32`; frontend `:3011`, prod build
via `npx next start -p 3011`), tenant `default`, `demo@example.com` / `demo1234`.

Primary session `s32c2` (steps 1-9), continuation session `s32c3` (step 10, after `s32c2`'s daemon
became unresponsive - a `resource temporarily unavailable` CLI-side hang, not an app bug; noted so
the ref numbering below resets once).

## Setup calls (verbatim)

```
lsof -ti :8013 | xargs kill -9   # stale S0-era process owned by this lane
cd service_backend && DATABASE_URL=postgresql://foundryx:foundryx@localhost:5432/foundryx_service_s32 \
  CORS_ORIGINS="http://localhost:3001,http://localhost:3002,http://localhost:3011" \
  CORS_ORIGIN_REGEX='http://[a-z0-9-]+\.localhost:(300[0-5]|3011)' \
  .venv/bin/uvicorn app.main:app --port 8013

lsof -ti :3011 | xargs kill -9
cd service_frontend && rm -rf .next && npm run build && npx next start -p 3011
```

`.env` is symlinked from main (shared across worktrees) - `CORS_ORIGINS`/`CORS_ORIGIN_REGEX` are
passed as process env vars on every uvicorn start rather than edited into the shared file, per the
lane brief ("on every restart").

## Run log

1. **01-channels-list-1280.png** - login (sidebar Omnichannel -> Settings -> Channels via real
   clicks, never a typed URL) - the Channels list already carries seeded Messenger/Instagram rows
   (`chn-demo-fb`, `chn-demo-ig`) with Type-column badges, plus one residue row
   (`Foundryx Concierge`, `pg-702`) from an earlier E2E pass on this SAME lane today - left as
   real prior-run data (F7: no fresh tenant needed, this is the seeded sandbox scenario).
2. **02-messenger-page-picker-1280.png** - Connect channel -> type `Messenger` (manual-connect
   affordance disappears, WhatsApp-only) -> "Connect (sandbox)" (simulated authorize, no Meta env)
   -> the wizard's OWN real page-selection step (`Choose a Page`, backed by the REAL
   `/onboarding/meta/pages` + `/onboarding/meta/connect` routes against the dev-safe adapter's
   canned pages) -> `pg-702` (already connected) correctly excluded, only `pg-701`/`pg-703` offered
   -> picked `Foundryx VIP Desk` (`pg-703`).
3. **03-messenger-connected-1280.png** - "Sandbox channel created" -> list shows
   `Foundryx VIP Desk` with a Messenger type badge.
4. **04-messenger-detail-no-templates-no-profile-1280.png** /
   **04-messenger-detail-375.png** - opened the new Messenger channel: tabs are
   `Configuration, Webhooks` only - **no Templates, no Profile tab** (D-A7-17). Hit + fixed a real
   bug here - see "Bug found and fixed" below.
5. **05-instagram-connected-1280.png** / **05-instagram-detail-375.png** - repeated for Instagram:
   type `Instagram` -> "Connect (sandbox)" -> "Choose a professional account" (only
   `foundryx.events`, `pg-702`'s linked IG account `foundryx.concierge` correctly excluded as
   already-connected) -> connected -> list badge "Instagram" -> detail tabs
   `Configuration, Webhooks` only, same as Messenger.
6. **06-fb001-send-1280.png** - Inbox -> `Jordan Lee` (`cnt-fb-001`, Messenger, standard window
   open) - composer enabled, sent "S6 E2E: Messenger send test", bubble landed with a single grey
   check (sent).
7. **07-fb001-badge-fixed-1280.png** - re-verify after the badge fix (below): header now reads
   "Messenger" with the Messenger icon, and the gateway `psid:` send from the curl block below is
   visible in the same thread.
8. **08-ig002-locked-1280.png** / **08-ig002-locked-375.png** - Inbox -> `Priya Nair`
   (`cnt-ig-002`, Instagram, both windows expired) - badge "Instagram"; composer LOCKED, banner
   **"The messaging window has closed."** (no WhatsApp wording, no "Choose template" button -
   `capabilities.template=false` for Instagram, D-A7-17/AC-CHN-29 already correct since S2).
9. **09-fb002-human-agent-1280.png** / **09-fb002-human-agent-sent-1280.png** - Inbox ->
   `Alex Tan` (`cnt-fb-002`) - standard window backdated 1h (see note below) to exhibit the
   extended-only state: composer shows the amber banner **"The standard messaging window has
   closed."** but stays UNLOCKED (no lock icon on the input, `extendedOpen=true`); sent
   "S6 E2E: human-agent window send" successfully.
10. **10-workflow-canvas-added-1280.png** / **11-workflow-channeltype-filter-1280.png**
    (session `s32c3`, same tenant) - Workflows -> New workflow -> searched "Incoming omnichannel"
    in the real palette -> placed the trigger -> the live config drawer shows BOTH `Channel`
    ("All channels") and the NEW `Channel type` field ("All types" default, SearchSelect) ->
    selected "Messenger" -> `channelType: 'FACEBOOK'` written to the node config (matches the
    vitest assertion in `node-config-drawer.omnichannel-ai.test.tsx`).

## Gateway curl evidence (AC-CHN-53/54/55/56, run against the same live `:8013`)

```
$ curl -X POST http://localhost:8013/api/v1/omnichannel/messages -H "Authorization: Bearer $KEY" \
    -d '{"to":"psid:psid-demo-1","channelId":"chn-demo-fb","type":"text","text":{"body":"gateway psid test"}}'
{"id":"2794c200-...","status":"queued","idempotencyReplay":false}   HTTP 202

$ curl ... -d '{"to":"+60123456789","type":"text","text":{"body":"gateway phone->WhatsApp test"}}'
{"id":"32a82baf-...","status":"queued", ...}   HTTP 202   # verified landed on the WHATSAPP channel

$ curl ... -d '{"to":"igsid:no-such-igsid","channelId":"chn-demo-ig","type":"text","text":{"body":"x"}}'
{"error":{"code":"invalid_recipient","message":"No contact found for that identity on the selected channel."}}   HTTP 422

$ curl ... -d '{"to":"igsid:igsid-demo-2","channelId":"chn-demo-ig","type":"text","text":{"body":"x"}}'
# cnt-ig-002's identity - both windows expired
{"error":{"code":"messaging_window_closed","message":"The messaging window has closed."}}   HTTP 409
```

Note: the plan's brief text said "201" for the send responses; the actual, documented (guide §4)
and tested contract is `202 Accepted` (message queued, not yet delivered) - unchanged by this
slice, reported here as actually observed.

## Bug found and fixed during this run

1. **Channel detail page 404'd for EVERY non-WhatsApp channel** (`use-channel-form.tsx`) -
   `Promise.all([channelService.get(id), channelService.getProfile(id)])` failed the whole page
   the instant `getProfile` returned its EXPECTED `409 channel_type_unsupported` for a
   Messenger/Instagram channel (D-A7-17), rendering "Channel not found" even though the channel
   fetch itself succeeded (verified via `network requests`: `GET .../channels/{id}` 200,
   `GET .../channels/{id}/profile` 409, followed by the page's fallback UI). This blocked
   AC-CHN-62's "open it and confirm no Templates and no Profile tab" step outright - the page never
   rendered at all. Fixed: the profile fetch now runs independently and degrades to `profile: null`
   on ANY error (never flips `notFound`); only the channel fetch failing is a real 404. The
   pre-existing tab-filtering logic (`isWhatsApp` gating Templates/Profile) was already correct
   once the page could render. Reproduced on the SEEDED `chn-demo-ig` channel too (not new to the
   channel I connected in this run), so it predates this slice - filed as **BL-SS-150** below with
   a fix already merged in this commit (screenshots 04/05 above are POST-fix).
2. **Conversation drawer header badge always read "WhatsApp"** (`conversation-drawer.tsx`) -
   hardcoded `<Badge>WhatsApp</Badge>` regardless of `thread.channelType` (exactly the S0-S5
   handoff note's known gap - the wire didn't carry the per-identity fields until this slice, and
   the ONE remaining consumer of `channelType` for display had not been updated). Fixed: reads
   `CHANNEL_CAPABILITIES[thread.channelType]` for both the icon and the label, same pattern the
   channels list Type column and the composer window logic already used. Screenshot 06 shows the
   bug (Jordan Lee - Messenger contact - badge reads "WhatsApp"); screenshot 07 shows the fix
   (badge reads "Messenger").

## Deliberate evidence-only DB tweak

`cnt-fb-002`'s `contact_channel_identities.window_expires_at` was moved 1h into the past (leaving
`human_agent_expires_at` ~7 days out) to exhibit the "standard window closed, human-agent window
open" state for screenshot 09 - the dev seed stamps both windows from the SAME inbound timestamp
(`stamp_inbound_window`), so a freshly-reseeded lane never naturally sits in the extended-only
state at arbitrary wall-clock read time. This is a single-row, reversible, non-destructive
timestamp edit on the SHARED dev tenant's seeded demo contact (not a fresh tenant per F7 - this
IS the seeded sandbox scenario the plan calls for); flagging the deviation from "provision a
dedicated tenant when mutating shared state" since this mutated a shared seed row in place rather
than a fresh id. No other lane data was touched.

## Deferred (not covered by this run, tracked below)

- A user without `channels.manage` seeing no Connect control - not verified live (no ready
  non-admin login in this lane); the gate itself (`RequirePermission` / `editPermission:
  "channels.manage"` on the wizard) is unchanged pre-existing code, not new to this slice.
- `message_received` trigger with `channelType: Messenger` firing for a Messenger webhook and
  NOT for a WhatsApp one, verified via the workflow Logs tab - the FIELD renders live and writes
  the correct config (screenshot 11), but the full publish -> real Messenger webhook -> Logs round
  trip was not run live; the refine/context logic is pytest-covered
  (`tests/test_omnichannel_gateway_channel_selector.py`,
  `test_message_received_channel_type_filter_matches_only_that_type` +
  `test_inbound_service_stamps_channel_type_on_the_dispatched_extra`).
- The `s32c2` agent-browser session's daemon became unresponsive mid-run (CLI-side
  `Resource temporarily unavailable` after ~20 min of continuous use) - continuation ran on a
  fresh `s32c3` session; the stale `s32c2` browser process was left running (not `close --all`,
  per house rule) rather than force-killed.
