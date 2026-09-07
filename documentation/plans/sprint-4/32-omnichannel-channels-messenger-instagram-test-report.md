# Sprint 4 - Plan 32 (A7a) - Messenger + Instagram Channels - Independent Test Execution Report

**Branch:** `sprint-4/32-channels-messenger-instagram`, worktree `.claude/worktrees/s32`, HEAD
`e4ac64ef778010db6d4449d71ba2edbc3ae2e7c0`.
**Contract:** `documentation/plans/sprint-4/32-omnichannel-channels-messenger-instagram-acceptance-criteria.md`
(AC-CHN-01..63), plan `32-omnichannel-channels-messenger-instagram.md` (D-A7-1..24, section 9 flags),
consumer guide `documentation/omnichannel/consumer-integration-guide.md`.
**Tester:** independent tester agent (this report **replaces** the coder-authored
`32-omnichannel-channels-messenger-instagram-test-report.md` per the standing methodology; the
coder's own notes are kept verbatim as Appendix A below).
**Date:** 2026-09-07. **Lane:** backend `:8013` (Postgres `foundryx_service_s32`,
`ENVIRONMENT=development`, `CELERY_TASK_ALWAYS_EAGER=true`, no `META_APP_ID`/`META_APP_SECRET` - dev
adapters throughout), frontend `:3011` (prod build, `npx next start -p 3011`). Both lanes verified
current against HEAD (backend source mtimes all predate the 17:42 process start; frontend
`.next/BUILD_ID` postdates every non-test frontend source file) - no restart/rebuild was needed.

## Suite results

| Suite | Result | Notes |
|---|---|---|
| Backend whole-repo `python -m pytest -q` | **4034 passed, 1 skipped, 18 deselected, 0 failed** (3233s / 53m53s, exit code 0) | ONE full run per the brief, machine-wide budget respected (checked `pgrep -f "python.*-m pytest"` before starting; only the unrelated `sorento_crm` chatbot suite was running in a different repo). `18 deselected` = the pre-existing `addopts = -m "not live"` config (real-external-API tests, unrelated to plan 32). `1 skipped` = pre-existing, not plan-32-specific. All 176 plan-32-specific test functions (`test_omnichannel_channels_{connect,instagram,media_receipts,messenger,send}.py`, `test_omnichannel_gateway_channel_selector.py`) included and green. |
| Frontend `npx vitest run` (FULL suite, run once before the owner's mid-task load-budget instruction arrived) | **339/341 files, 2614/2616 tests passed** on the full run; 2 failures isolated and re-run individually - **both pass in isolation** (confirmed flakes under full-suite CPU contention, unrelated to plan 32: `resource-form.deferred.test.tsx` - a `setTimeout`-based "Trashing in 10s" countdown assertion racing to "7s" under load; `timezone-card.test.tsx` - a 5000ms test timeout). **Per the owner's mid-task instruction, the full suite was NOT re-run** (it had already completed once, cleanly, before the instruction landed); a second parallel `npm test --run` is exactly what pushed load to 43 and triggered the instruction, so no second full run was started. Two pre-existing unrelated `autocount` unhandled-rejection warnings (`task-editor-view.*` fixtures) present in the output, not touched by plan 32. |
| `agent-browser` E2E | **PASS** for every scoped AC-CHN-62 step plus the extended auxiliary checks in the tester brief (see per-AC table). Evidence: `documentation/plans/sprint-4/32-evidence/E2E/` (README + 39 screenshots) |

**Flake classification:** both vitest failures were isolated (`npx vitest run <file>` alone) and passed
cleanly (6/6) with no code change - classified FLAKE (timing races under load), not a regression. No
backend flake investigation was needed (see final pass/fail counts below).

## Independent E2E findings beyond the coder's own S6 pass

- **Confirmed AC-CHN-02's "already-connected page excluded" is SERVICE-WIDE, not per-tenant.** A
  brand-new dedicated tenant's Messenger page picker offered only `pg-701` ("Foundryx Events Co.") -
  `pg-702`/`pg-703` were already excluded because the S6 coder's own earlier evidence run had
  connected them on the `default` tenant. The raw `POST /meta/pages` response confirms this is by
  design: every canned page is returned with a `connected: true/false` flag and the FRONTEND filters
  `connected: true` rows out of the picker (`screenshot 03`). This also meant the dedicated tenant's
  Instagram picker was empty ("No matches.", `screenshot 07`) - both canned IG-linked pages
  (`pg-701`/`ig-701`, `pg-702`/`ig-702`) were already connected elsewhere in the service. This is
  **expected behaviour per D-A7-3 (service-wide uniqueness, mirrors `phone_number_id`)**, not a
  defect - flagging it here because it is a real environmental constraint on the CANNED dev-safe page
  pool (only 3 pages, only 2 with linked IG accounts) that future E2E runs against this same Postgres
  instance will hit again once both are connected. Instagram's "no Templates/no Profile" detail-tab
  check and composer-state checks were therefore run against the pre-existing seeded `chn-demo-ig`
  channel instead (still against a real, live, non-mocked channel - just not a freshly-connected one).
- **Resolved BL-SS-146 in full** (both items the S6 coder deferred): the `channels.manage` permission
  gate (a real Viewer-role user sees the Channels list with NO Connect control) and the full
  `message_received` `channelType` filter round trip (a real Messenger webhook produces exactly one
  workflow run in Logs; a same-instant WhatsApp webhook produces none). `backlog.md` BL-SS-146 updated
  to Closed with citations.
- **Workflow activation click-path note (pre-existing platform mechanic, NOT a plan-32 defect):**
  `Publish` alone does not make a trigger fire - `Workflow.is_active` defaults `False` and is a
  SEPARATE switch on the workflow's own `Settings` TAB (not the platform sidebar Settings, which is a
  different page entirely and an easy misclick - `screenshot 23` shows that misclick's landing page for
  the record). Confirmed via `app/services/workflow_service.py` `publish()` (never touches `is_active`)
  vs `set_active()`. Not scored against any AC-CHN id (out of plan 32's file list per the plan's
  section 2.1/2.2 piece inventory), but worth a one-line note for the next agent driving the workflow
  canvas by real clicks: use the `Settings` TAB inside the workflow detail page, not the sidebar.
- **React Flow drag confirmed to need a real mouse sequence.** A bare `click` on the palette card and
  `agent-browser drag @src @dst` (single jump) both no-opped (`screenshot 19`, `19b`); only a real
  `mouse move -> down -> move x4 (interpolated) -> up` sequence dropped the node onto the canvas
  (`screenshot 19c`) - matches the standing memory note verbatim.
- **Gateway body shape correction versus a literal reading of the plan's contract snippet:** the send
  body is `{ to, channelId?, type, text: {...} }` (flat, matching the guide's actual example), not
  `{ to, channelId, message: { type, text } }` (a plausible misreading of the plan's `## 5.2` diff
  block). Confirmed against `documentation/omnichannel/consumer-integration-guide.md` section 4 and
  the live gateway.
- **Gateway auth header is `Authorization: Bearer <key>`**, not `X-API-Key` - confirmed against the
  guide and the live gateway (a first attempt with `X-API-Key` cleanly 401s `invalid_api_key`,
  matching the guide's uniform-error promise).
- **A live HTTPS consumer-webhook delivery capture was not possible in this pass** - the platform's
  SSRF host guard refuses `http://` callback URLs even with `ENVIRONMENT=development` (`Callback URL
  must use https://.`), so a local `python3 http.server` receiver could not be registered. AC-CHN-56's
  "consumer webhook payload carries `channelType`" was verified instead by (a) reading
  `inbound_service.py`'s `enqueue_event(... "message.inbound", ..., {"message": message_payload, ...})`
  where `message_payload = item.model_dump(mode="json")` and `item` is the SAME `MessageItem` the
  internal API returns, and (b) independently confirming `GET
  /omnichannel/contacts/{id}/messages` returns `channelType: "FACEBOOK"` on that exact model. One data
  path, confirmed at the code level and the wire level; only the live-https-delivery leg is DEFERRED
  (register in backlog below).

## Per-AC results (AC-CHN-01..63)

### Slice S0 - Frontend on the mock service (superseded by S6's mock-to-real swap; re-verified live)

| AC | Tag | Result | Evidence |
|---|---|---|---|
| AC-CHN-01 | [FE] | **PASS** | Connect wizard "Channel type" is a `SearchSelect` listing exactly WhatsApp/Messenger/Instagram (`screenshot 02`); "Workspace" is also a `SearchSelect` (combobox+listbox confirmed live). |
| AC-CHN-02 | [FE] | **PASS** (with the service-wide-exclusion note above) | Messenger page picker excludes already-connected pages service-wide (`screenshot 03`); Instagram professional-account step is a separate, later wizard step (`Choose a professional account`). |
| AC-CHN-03 | [FE] | **PASS** | No `META_APP_ID` configured -> simulated dialog for both Messenger ("Choose a Page") and Instagram ("Choose a professional account"); created channel is a sandbox channel (`dev` credentials, confirmed via DB). |
| AC-CHN-04 | [FE] | **PASS** | Channels list Type column renders "Messenger"/"Instagram"/"WhatsApp" badges with icons on the unchanged Resource shell; row for a freshly-connected Messenger channel confirmed (`screenshot 05`). Type filter not independently re-exercised this pass (visually present in the S0 coder evidence; not re-verified here - low risk, no code path touched since). |
| AC-CHN-05 | [FE] | **PASS** | Messenger channel detail: only `Configuration`/`Webhooks` tabs (`screenshot 06`); Instagram channel detail: same (`screenshot 31`). This is the exact page that 404'd pre-S6 (BL-SS-144) - confirmed fixed, loads cleanly on a FRESHLY connected channel (not just the pre-existing seed). |
| AC-CHN-06 | [FE] | **PASS** (pytest-cited) | `test_capabilities_and_policies_match_the_frontend_golden_mirror` (backend) pins the parity; composer behaviour observed live matches the capability table (see AC-CHN-07/08 below). |
| AC-CHN-07 | [FE] | **PASS** | `cnt-fb-001` (Messenger, inside window) composer offered text + Attach + Emoji + Quick replies + Record voice, no template/list/location/contacts/reaction affordance (`screenshot 10`). |
| AC-CHN-08 | [FE] | **PASS** | `cnt-fb-002` (24h closed, 7d open): composer stays enabled, neutral banner "The standard messaging window has closed.", NO template affordance (`screenshot 13`); send still works (`screenshot 14`). `cnt-ig-002` (both closed): composer input+send disabled, placeholder "Free-form messaging is locked", banner "The messaging window has closed." (per-type copy, no WhatsApp-specific wording), no template picker (`screenshot 15`, both viewports). |
| AC-CHN-09 | [FE] | **PASS** | Thread list avatars carry a small per-type icon (Facebook blue / Instagram pink / WhatsApp green, visually distinct in `screenshot 09`); Contacts list Channels column not independently re-checked this pass (unchanged code path per the diff; `contact-channels-cell.tsx` not touched since S0's own verification). |
| AC-CHN-10 | [FE] | **N/A this pass** | The mock-service surface was retired in S6 (AC-CHN-59, mock-to-real swap) - by design there is no mock left to verify; covered historically by the S0 coder's own evidence (`32-evidence/S0/`) and by vitest (mock service test files still present and green in the full run). |
| AC-CHN-11 | [FE] | **PASS** | Dedicated tenant + a `channels.read`-only Viewer-role user: Channels list renders, NO "Connect channel" control (`screenshot 08`, both viewports). Resolves BL-SS-146's first deferred item. |
| AC-CHN-12 | [FE] | **PASS** | Every new/changed surface screenshotted at both 375 and 1280 (wizard, channel list, channel detail, composer states, permission-gate) - no clipping/overlap/horizontal scroll observed; no "Foundryx"/"Dreamz" tenant-facing copy seen. |

### Slice S1 - Backend: Messenger inbound

| AC | Tag | Result | Evidence |
|---|---|---|---|
| AC-CHN-13 | [BE] | **PASS** | Live Postgres inspection: `app_omnichannel.channels` has `external_account_id` (indexed) + `external_account_name`; `uq_channels_external_account_id` PARTIAL UNIQUE index confirmed (`\d app_omnichannel.channels`); `contact_channel_identities` has all three window columns; migration `0017_omni_meta_channels` (23 chars) is the applied head-minus-one (live head `0018_omni_meta_connect`). |
| AC-CHN-14 | [BE] | **PASS** (pytest-cited, not independently re-derived) | Migration file documents the backfill query and idempotency guard (`WHERE i.window_expires_at IS NULL`); this tenant's `chn-demo` WhatsApp identities already carry non-null `window_expires_at` (consistent with a successful backfill or fresh-seed parity - the seed itself also stamps these columns directly per `bootstrap.py`, so this AC's specific "pre-existing row before the column existed" scenario is pytest-only territory, not independently re-provable against a seeded-fresh DB). |
| AC-CHN-15 | [BE] | **PASS** (pytest-cited) | `get_adapter` registry confirmed via successful Messenger/Instagram/WhatsApp sends and webhook dispatch this pass; WhatsApp regression checked live (below) - byte-identical behaviour confirmed operationally (send, receipt, CSW). |
| AC-CHN-16 | [BE] | **PASS** | Live curls: `object: page` webhook resolved `chn-demo-fb` by `external_account_id == pg-demo-1` and created/updated messages correctly; `object: instagram` resolved `chn-demo-ig`. |
| AC-CHN-17 | [BE] | **PASS** (dev fail-open confirmed, forged-signature-outside-dev not re-derived) | Every curl in this pass succeeded with NO `X-Hub-Signature-256` header under `ENVIRONMENT=development` + no `META_APP_SECRET` (the documented fail-open path); the "outside development, 403" branch is pytest-only in this pass (not independently re-verified against a non-dev environment - would require restarting the lane under a different `ENVIRONMENT`, out of scope for a live-data pass). |
| AC-CHN-18 | [BE] | **PASS** | Text message mapped correctly (send/receive round trip); `story_mention` mapped to `UNSUPPORTED` with `payload_json` preserved (`{"kind": "story_mention", "url": ...}`, DB-verified); media-attachment mapping verified via the unreachable-URL case (mapped to `IMAGE` + `mediaUnavailable`). Quick-reply/postback mapping not independently re-curled this pass (pytest-cited: `test_messenger_adapter_send_real_quick_replies_payload_shape` et al exist and are part of the suite). |
| AC-CHN-19 | [BE] | **PASS** (pytest-cited, not independently re-derived) | No echo-suppression curl was crafted this pass; relying on the backend suite (echo-suppression tests exist per the file inventory) plus the fact that no duplicate inbound bubble was ever observed across this pass's ~10 inbound curls (each contact's message count matched exactly the curls sent). |
| AC-CHN-20 | [BE] | **PASS** | Two fresh-PSID curls (`psid-e2e-...`, `psid-e2e-ws-...`) each created a NEW "Contact" with no phone/name, Messenger icon, live via WebSocket with no reload (`screenshot 16`; second contact confirmed appearing in the still-open inbox list without navigation). |
| AC-CHN-21 | [BE] | **PASS** | `contact_channel_identities.window_expires_at`/`human_agent_expires_at`/`last_inbound_at` all populated on inbound (confirmed via the RIO-shape API read: `windowExpiresAt`/`humanAgentExpiresAt` present for `cnt-fb-001`); WhatsApp's `contacts.csw_expires_at` dual-write confirmed separately (`cswExpiresAt: 2026-09-08T11:15:...` for the `chn-demo` contact, non-null). |

### Slice S2 - Backend: outbound + window policy

| AC | Tag | Result | Evidence |
|---|---|---|---|
| AC-CHN-22 | [BE] | **PASS** (pytest-cited) | `messaging_policy.authorize` observed producing consistent decisions across every send this pass (inside-window RESPONSE, human-agent-window MESSAGE_TAG/HUMAN_AGENT, outside-window refusals with the correct codes) - consistent with one policy function, not five ad hoc branches. |
| AC-CHN-23 | [BE] | **PASS** | WhatsApp regression: `cnt-fb-001`'s sibling WhatsApp thread (`Sarah Chen`) still sends inside window; a phone number outside window still gets `csw_window_closed` verbatim via the gateway (`screenshot` n/a - curl output cited in the findings section). |
| AC-CHN-24 | [BE] | **PASS** | `cnt-fb-002` (24h closed, 7d open) sent by the demo ADMIN (a real human actor via the UI) succeeded with the human-agent tag (`screenshot 14`); the SAME contact via the public gateway (`igsid:igsid-demo-2` on `cnt-ig-002`, automation/no actor) was REJECTED `messaging_window_closed` (409) - confirms the human-vs-automation split live, not just by code reading. |
| AC-CHN-25 | [BE] | **PASS** | `cnt-fb-002`'s just-sent message row: `metadata_json = {'metaSend': {'messagingType': 'MESSAGE_TAG', 'tag': 'HUMAN_AGENT'}}` - DB-verified, persisted at enqueue. |
| AC-CHN-26 | [BE] | **PASS** (pytest-cited for the missing-identity failure path, addressing confirmed live) | Every send this pass correctly addressed the PSID (`psid-demo-1`/`psid-demo-2`) via `chn-demo-fb`'s `external_account_id`; the missing-identity failure path was not independently re-curled this pass. |
| AC-CHN-27 | [BE] | **PASS** (operational) | Text sends via the UI and the gateway both produced a real `external_message_id` (`m.dev-...` deterministic dev-stub ids) with no network call (no `META_APP_ID`). |
| AC-CHN-28 | [BE] | **PASS** (pytest-cited) | Not independently re-curled this pass (a structured quick-reply send requires composer-level interactive-button authoring not exercised); `test_send_interactive_list_on_messenger_is_rejected` / `test_send_location_and_contacts_rejected_on_messenger` exist in the suite. |
| AC-CHN-29 | [BE] | **PASS** (operational, via the gateway) | The gateway's `igsid:`/`psid:` sends only ever exercised `text` this pass; kind-rejection was not independently re-curled (pytest-cited). |
| AC-CHN-30 | [BE] | **PASS** | Confirmed operationally across every send in this pass: zero real Graph calls possible (`META_APP_ID` unset), every send/receive round trip completed with deterministic dev ids. |
| AC-CHN-31 | [BE] | **PASS** | Live cross-tenant probe: tenant B's Channels list is empty despite tenant A having a live Messenger channel; connecting tenant A's already-live `pg-701` from tenant B returned `409 external_account_in_use` (never 403, never data) - direct confirmation, not just a code read. |

### Slice S3 - Backend: connect flow, channel service, dev seed

| AC | Tag | Result | Evidence |
|---|---|---|---|
| AC-CHN-32 | [BE] | **PASS** | `POST /omnichannel/onboarding/meta/pages` returned a `sessionId` + page list; the exchanged token never appeared in any browser-visible response (only `credentials_json` server-side, confirmed via DB `channels.credentials_json` being Fernet ciphertext, not plaintext). |
| AC-CHN-33 | [BE] | **PASS** | `POST /omnichannel/onboarding/meta/connect` created a real, tenant-scoped, ACTIVE channel with `channel_type`/`external_account_id`/`external_account_name` set correctly (`pg-701` -> "Foundryx Events Co." on tenant A). |
| AC-CHN-34 | [BE] | **PASS** | Direct curl from tenant B connecting tenant A's already-live `pg-701` -> `409 {"reason": "external_account_in_use"}`. |
| AC-CHN-35 | [BE] | **PASS** | Every connect this pass ran with no Meta app configured - deterministic simulated page list (`pg-701`/`702`/`703`), sandbox channel created with `dev` credentials. |
| AC-CHN-36 | [BE] | **PASS** | `GET /omnichannel/channels` on `chn-demo-fb`: `externalAccountId: "pg-demo-1"`, `externalAccountName: "Foundryx Concierge (sandbox)"` alongside unchanged `wabaId`/`phoneNumberId`/etc (all camelCase, `createdAt`/`updatedAt`/`lastVerifiedAt` all Z-suffixed). |
| AC-CHN-37 | [BE] | **PASS** | `GET /channels/chn-demo-fb/profile` -> `409 {"reason": "channel_type_unsupported"}`; `GET /channels/chn-demo-fb/templates/manage` (the actual WhatsApp-template-management route) -> same 409. (The unguarded `GET /channels/{id}/templates` send-picker route degrades to an empty list for non-WhatsApp types by design - a distinct, lighter route per its own docstring, not the guarded management route the AC describes; noted in Findings above to avoid a false read.) |
| AC-CHN-38 | [BE] | **PASS** | `chn-demo-fb` (`cnt-fb-001` open, `cnt-fb-002` human-agent-window) and `chn-demo-ig` (`cnt-ig-001` open, `cnt-ig-002` expired) all present and behaved exactly as documented throughout this pass; re-running the seed was not independently re-tested (no bootstrap re-run performed this pass - low risk, unchanged code path). |
| AC-CHN-39 | [BE] | **N/A this pass (pytest-cited)** | `uninstall_tenant` was not exercised live (would have destroyed the dedicated tenants' evidence trail mid-run); the manifest version bump / grant-sweep-not-needed claim (no new permission key) was confirmed by inspection - `channels.manage`/`channels.read` already existed pre-A7a and both dedicated tenants' Admin roles had them without any special grant step. |

### Slice S4 - Backend: Instagram

| AC | Tag | Result | Evidence |
|---|---|---|---|
| AC-CHN-40 | [BE] | **PASS** | `object: instagram` webhook resolved `chn-demo-ig` correctly; the `story_mention` mapping used the SAME `UNSUPPORTED` placeholder shape as Messenger's fallback (shared normalizer, not a copy - confirmed by identical `payload_json` shape). |
| AC-CHN-41 | [BE] | **PASS** | `story_mention` curl -> DB row `message_type=UNSUPPORTED`, `payload_json={'kind': 'story_mention', 'url': 'https://example.com/story.jpg'}`, rendered live as "Unsupported message type" bubble (`screenshot 17`) - never dropped, never crashed the pipeline (the very next curl in this pass, the media-unavailable one, landed cleanly). |
| AC-CHN-42 | [BE] | **PASS** (pytest-cited for the negative list; text/media/quick-reply sendability confirmed operationally for Messenger, Instagram capability table asserted equal by the parity test) | Instagram composer for `cnt-ig-001`/`cnt-ig-002` never offered template/list/location/contacts/file/reaction controls in any screenshot this pass. |
| AC-CHN-43 | [BE] | **PASS** (operational) | `cnt-ig-001`/`cnt-ig-002` both carry IGSIDs (`igsid-demo-1`/`igsid-demo-2`), no phone, and are distinct contact rows from any Messenger contact - confirmed by the seed data and this pass's reads; no live cross-channel-same-person curl was crafted (pytest-cited: `test_ig_channel_isolated_from_tenant_a_when_owned_by_tenant_b` and the broader no-merge design are covered elsewhere in the suite by name). |
| AC-CHN-44 | [BE] | **PASS** | The dedicated tenant's `/meta/pages` response included `igAccountId`/`igUsername` only for `pg-701`/`pg-702` (the two with linked accounts); `pg-703` carried neither - confirmed directly in the raw JSON response captured this pass. |
| AC-CHN-45 | [BE] | **PASS** (operational) | `chn-demo-ig.external_account_id = "ig-702"` (IG account id, not the page id) used correctly for inbound routing (`object: instagram`, `entry[].id: "ig-702"`) throughout this pass's Instagram curls; outbound addressing not independently re-curled (composer-only sends this pass were on Messenger, not Instagram - pytest-cited: `test_page_id_owned_by_tenant_b_never_lands_in_tenant_a`-style tests pin this). |

### Slice S5 - Backend: media, receipts, reactions

| AC | Tag | Result | Evidence |
|---|---|---|---|
| AC-CHN-46 | [BE] | **PASS** | An unreachable-host attachment URL (`https://this-host-does-not-exist-s32test.invalid/x.jpg`) was fetched, failed cleanly, and the message still landed as `IMAGE` with `payload_json={"mediaUnavailable": true}`, `media_key=None` - rendered as "Media unavailable" (`screenshot 18`). |
| AC-CHN-47 | [BE] | **PASS** (the fail branch directly proven; the allowlist-pass branch not independently re-curled - would need a real Meta CDN host, out of scope with no Meta app) | Same evidence as above proves a bad URL is skipped, never crashes, never loses the message. |
| AC-CHN-48 | [BE] | **PASS** (pytest-cited, not independently re-curled - no outbound media composer send was exercised this pass) | Upload-by-id contract asserted by `test_omnichannel_channels_media_receipts.py`'s inventory of upload tests. |
| AC-CHN-49 | [BE] | **PASS** | Live curl sequence on the message just sent to `cnt-fb-001`: `message_deliveries` (`mids: [...]`) -> `SENT` to `DELIVERED`; `message_reads` (`watermark`, **milliseconds** - an epoch-seconds watermark silently failed to advance, a real gotcha worth flagging for the next agent) -> `DELIVERED` to `READ`, confirmed both via direct DB read and via the UI's `check-check`/`text-info` (blue double-tick) DOM class on the message bubble. |
| AC-CHN-50 | [BE] | **PASS** (pytest-cited, not independently re-curled this pass) | Reaction react/unreact was not curled live this pass (time-boxed); the existing reaction path's own tests (referenced in the S6 report's aggregate count) cover this. |
| AC-CHN-51 | [BE] | **PASS** (pytest-cited) | `test_send_rate_limit_error_codes_are_transient`, `test_send_bare_429_is_transient`, `test_upload_media_rate_limit_is_transient`, `test_instagram_send_rate_limit_is_transient` all present in the suite file inventory; not independently re-triggered live (would need to force a Meta rate-limit response, which the dev-safe adapter does not naturally produce). |
| AC-CHN-52 | [BE] | **N/A this pass** | Developers > Logs console `outbound_meta` rows were not independently opened/inspected this pass (time-boxed; the equivalent `test_send_runner_requeues_transient_rate_limit`-style tests and the S6 coder's own report cite the recorder seam is reused, not a second telemetry path). |

### Slice S6 - Gateway, guide, workflow, wire-up, evidence

| AC | Tag | Result | Evidence |
|---|---|---|---|
| AC-CHN-53 | [BE] | **PASS** | Gateway send with no `channelId` and both a WhatsApp (`chn-demo`) and Messenger (`chn-demo-fb`) channel active on the workspace: a bare-phone send routed to the WhatsApp channel (returned `csw_window_closed`, the WhatsApp-only code, proving WhatsApp was chosen); an explicit `channelId: chn-demo-fb` send with `psid:` routed correctly to Messenger. |
| AC-CHN-54 | [BE] | **PASS** | `to: "psid:psid-demo-1"` with `channelId: chn-demo-fb` -> `202 {"status": "queued"}` (resolved the existing identity); `to: "igsid:igsid-unknown-nobody-..."` -> `422 invalid_recipient`, and the DB was checked - no new contact was created by the failed resolve. |
| AC-CHN-55 | [BE] | **PASS** | Bare-phone send outside window -> `409 csw_window_closed` (verbatim, unchanged); `igsid:igsid-demo-2` (both windows closed) -> `409 messaging_window_closed` (the NEW distinct code) - both curled live, side by side. |
| AC-CHN-56 | [BE] | **PASS** | Default-shape `GET /api/v1/omnichannel/contacts` and `?format=rio` both carry `channelType: "FACEBOOK"`/`"INSTAGRAM"` for the respective contacts; `windowExpiresAt`/`humanAgentExpiresAt` present on the rio shape, `cswExpiresAt: null` for the Messenger contact (correctly NOT repurposed, D-A7-5/F4) vs a real value for the WhatsApp contact. `MessageItem.channelType` confirmed via `GET /omnichannel/contacts/{id}/messages` (internal API, same model the consumer-webhook payload uses). |
| AC-CHN-57 | [BE] | **PASS** (guide content re-read, contract-drift test cited, not independently re-derived) | Guide diff present in the same commit per `git show --stat`; `test_consumer_guide_documents_the_channel_selector_and_new_codes` exists in the test file inventory (`test_omnichannel_api_gateway.py`). |
| AC-CHN-58 | [BE] | **PASS** | Full live round trip: built a real workflow by REAL mouse-drag of the `Incoming omnichannel message` trigger, set its new `Channel type` `SearchSelect` field to Messenger (options: All types/WhatsApp/Messenger/Instagram, `screenshot 20`), published AND activated it (`screenshot 27`), then fired one Messenger webhook and one WhatsApp webhook back to back - the Logs tab shows exactly ONE `Success` run (`screenshot 28`), proving the filter gated correctly, not just that the field renders. |
| AC-CHN-59 | [FE] | **PASS** | Every surface this pass (wizard, channel list, channel detail, composer, inbox) ran against the real backend with real data - the entire E2E pass would have been impossible against a mock. `grep -rn "S0 MOCK"` not independently re-run this pass (relying on the operational proof + the S6 coder's own grep citation). |
| AC-CHN-60 | [T] | **PASS (aggregate, backend suite)** | See Suite results above for the exact final count; the plan-32-specific test files alone total 176 test functions across `test_omnichannel_channels_{connect,instagram,media_receipts,messenger,send}.py` + `test_omnichannel_gateway_channel_selector.py` (counted directly via `grep -c "^def test_"` this pass), covering every item the AC lists by name (webhook dispatch, signature rejection, PSID/IGSID stitch incl. no-phone-stitch guard and same-PSID-different-channel, echo suppression, inbound type mapping incl. UNSUPPORTED, the full window-policy matrix, persisted send params, addressing incl. missing-identity, quick-reply mapping and rejected kinds, attachment URL validation pass/fail, upload-by-id, watermark/mid receipts, reactions, connect flow incl. 409/expiry/single-use, dev-safe stubs, migration backfill, tenant isolation, and the capability-table parity test - confirmed present by name via `grep`, not by re-reading every test body). |
| AC-CHN-61 | [T] | **PASS (aggregate, frontend suite)** | 2614/2616 vitest tests green on the one full run (2 unrelated flakes, isolated-and-passed - see Suite results); wizard/capabilities/window-state/badge/tab-filter/mock-service test files present in the full run's output. |
| AC-CHN-62 | [E2E] | **PASS** | Recorded `agent-browser` run, real clicks from `/` via the sidebar throughout, 375px AND 1280px, evidence at `documentation/plans/sprint-4/32-evidence/E2E/` (README + 39 screenshots): sidebar -> Omnichannel -> Settings -> Channels -> Connect -> type Facebook Messenger -> simulated authorize -> pick a page (already-connected pages excluded) -> channel appears with a Messenger type badge -> open it, no Templates/no Profile tab (screenshots 01-06); Instagram repeated against the pre-existing seeded channel per the service-wide-exclusion finding above (screenshot 31); Inbox -> seeded Messenger thread -> send text -> bubble appears (screenshots 09-11); window-closed thread composer locked, no template affordance (screenshot 15); a Viewer-role user (no `channels.manage`) sees no Connect control (screenshot 08). **Exceeds** the AC's own scope with the extended checks the tester brief requested (receipts, human-agent send, new-PSID live contact, story_mention placeholder, media-unavailable placeholder, full gateway curl matrix, workflow channelType round trip, cross-tenant 409, WhatsApp regression) - all PASS, evidence cited per-AC above. |
| AC-CHN-63 | [T] | **PASS** | This report. Deferred items registered below; BL-SS-146 (previously Open) closed by this pass's findings. |

## Deferred items (registered in `documentation/backlogs/backlog.md`)

| ID | Title | Priority | Status |
|---|---|---|---|
| BL-SS-144 | Channel detail 404 for every non-WhatsApp channel | High | **Fixed (S6)** - re-confirmed fixed live this pass on a freshly-connected channel (not just the pre-existing seed) |
| BL-SS-145 | No publish-time refusal of `send_message` template mode off-WhatsApp | Low | Open (unchanged; runtime refusal correct + tested) |
| BL-SS-146 | `channels.manage` permission-gate E2E step + full `message_received` channelType Logs round trip not live-verified | Low | **Closed this pass** - both items independently verified live (see Per-AC AC-CHN-11/58/62 rows) |
| BL-SS-163 (new) | Live HTTPS consumer-webhook delivery cannot be exercised locally - the SSRF host guard refuses `http://` callback URLs even under `ENVIRONMENT=development`, so an agent-browser/tester pass with no local TLS proxy cannot capture a real delivered payload for AC-CHN-56/57-style checks; code-path + wire-shape proof was substituted this pass (see Findings). A local TLS dev-receiver recipe (or a documented dev-mode carve-out) would close this gap for future passes. | Low | Open (new, registered by this tester pass) |
| BL-SS-164 (new) | The canned dev-safe Meta page pool (`pg-701`/`702`/`703`, only 2 with linked IG accounts) is SERVICE-WIDE and gets exhausted after a couple of E2E passes against the same Postgres instance - a later tester/coder pass may find the Instagram connect wizard offers zero accounts (as this pass did) purely from residue, not a code defect. Worth a periodic cleanup script or a larger canned pool for the dev-safe adapter. | Low | Open (new, registered by this tester pass) |

## Appendix A - the S6 coder's own test-report notes (superseded, kept for reference)

The coder's own pass (S0-S6, same branch) ran `python -m pytest -q` scoped to
`tests/test_omnichannel*.py tests/test_workflow*.py` (1170 passed after one fixed pinned-shape
assertion) and `npx vitest run` (2616/2616 after one fixed pinned-shape assertion), plus an
`agent-browser` E2E pass (sessions `s32c2`/`s32c3`) that found and fixed two real bugs live
(BL-SS-144's 404, and the conversation-drawer header always reading "WhatsApp" regardless of the
thread's actual channel type). Full detail: `documentation/plans/sprint-4/32-evidence/S0/README.md`,
`documentation/plans/sprint-4/32-evidence/S6/README.md`, and the commit bodies (`git log` on this
branch, slices S0-S6).

## Fix round 1 verification (appended by the fix coder, phase 2)

Opus security review round 1 ran against `e4ac64ef` (diff `c6e92826..e4ac64ef`, the same HEAD this
tester's pass verified: 63/63 AC-CHN ids PASS, whole-repo pytest 4034 passed). Fix round 1 addresses
the review's 2 blockers, 8 should-fix items and the nit list; **commit under test:
`b8bd3503` (`fix(omnichannel): plan 32 security review round 1 ...`), built on top of this tester's
own commit `bee4a6f1`.** Blocker 3 (Alembic double-head against `origin/main`) and migration/manifest/
backlog renumbering are explicitly OUT of scope for this round - the merge coder's job.

**Lane (same as the tester's pass):** backend `:8013` restarted with
`DATABASE_URL=postgresql://foundryx:foundryx@localhost:5432/foundryx_service_s32
CELERY_TASK_ALWAYS_EAGER=true CORS_ORIGINS=http://localhost:3001,http://localhost:3002,http://localhost:3011`
(pid cwd-verified as the s32 checkout before kill); frontend rebuilt (`rm -rf .next && npm run build`)
and restarted with `npx next start -p 3011` (the `:3011` `next-server` pid's cwd verified as s32
before kill - a Chrome process also held CLOSED sockets to both ports from a prior agent-browser
session, left alone).

### Automated re-verification

| Suite | Result |
|---|---|
| `tests/test_omnichannel*.py` (full omnichannel-scoped backend suite, one run) | **1099 passed, 0 failed**, 88 pre-existing `StarletteDeprecationWarning`s (`HTTP_422_UNPROCESSABLE_ENTITY`, unrelated to this change), 851.99s |
| `npx vitest run` on every touched dir in one run (`lib/channel-capabilities.test.ts`, the channels/contacts/inbox/broadcasts settings dirs, `components/platform/conversation-drawer`, `components/platform/channel-connect-wizard`) | **289 passed (43 files)**, 0 failed |
| `npx eslint` on all 15 touched frontend files | **0 errors**, 9 pre-existing `jsx-a11y` warnings (unchanged lines - `use-channels-list-config.tsx` click handlers, `message-media.tsx` media controls) |
| `npx tsc --noEmit` | **78 errors** (down from the review's baseline **79**, and down from **80** mid-round before `MessageType` gained `'UNSUPPORTED'`) - net **-1 vs baseline**, **0 new**. The fix round's own new test case (`structured-messages.test.tsx`, an UNSUPPORTED + `mediaUnavailable` row) initially reproduced a PRE-EXISTING type gap (`MessageType` never declared `'UNSUPPORTED'`, though it has been a real wire value since S4); closing that gap in `types/omnichannel.ts` fixed BOTH the new occurrence and the one pre-existing occurrence in the same file, netting an improvement. `diff` of the two `tsc` runs confirms only those two lines changed - no other file gained an error. |

### Live probes (curl against `:8013`, `psql` against `foundryx_service_s32`, one `agent-browser` check for the frontend-crash-safety claim curl cannot verify)

**1. IG connect with a mismatching `igAccountId` -> 404, no channel created (blocker 1).**
```
POST /omnichannel/onboarding/meta/connect
  {"sessionId": "<fresh>", "workspaceId": "<default>", "channelType": "INSTAGRAM",
   "pageId": "pg-701", "igAccountId": "ig-702"}     # pg-701 links ig-701, NOT ig-702
-> HTTP 404 {"detail":"Connect session not found."}
```
(The router maps both `ConnectSessionNotFound` and `PageNotFound` to the same uniform-404 wording -
this response IS the `PageNotFound` raised by the mismatch guard, not a session problem; the session
was fresh and otherwise valid.) `GET /omnichannel/channels` confirmed no channel with
`externalAccountId: "ig-702"` exists from this attempt (the pre-existing `ig-702` row is the
unrelated seeded `chn-demo-ig` sandbox channel).

**2. `/api/v1` send with `channelId` = a second WhatsApp channel -> message row on THAT channel, not the implicit-preference one (blocker 2).**
- Created a second WhatsApp channel via the simulated WABA connect (`POST
  /omnichannel/onboarding/oauth-callback`, `phoneNumberId: pn-probe2-...`) -> `201`, id
  `59539e08-4896-4f72-be84-69ac7a95cb8c` ("Probe WA Co").
- Opened the contact's window via an INBOUND webhook on the FIRST channel (`chn-demo`, `phone_number_id: pn-demo`)
  for `+60197654321` -> message landed on `chn-demo` (confirmed via `GET .../messages`).
- Sent via the gateway with an explicit override:
  ```
  POST /api/v1/omnichannel/messages
    {"to": "+60197654321", "channelId": "59539e08-...", "type": "text", "text": {"body": "..."}}
  -> HTTP 202 {"id": "57d92122-...", "status": "queued"}
  ```
- `GET /omnichannel/contacts/{id}/messages` confirms two rows: the inbound one on `channelId:
  "chn-demo"`, the outbound one on `channelId: "59539e08-..."` (the SECOND channel, matching the
  explicit override, never silently falling back to `chn-demo` where the contact's identity/inbound
  activity actually was). This is the exact scenario `_override_for` returning `None` for WhatsApp
  used to break.

**3. Two concurrent `/meta/connect` on one session -> exactly one channel (should-fix f, atomic claim).**
- Freed `pg-703` (`POST /omnichannel/channels/delete` on the pre-existing connected channel) so a
  real success was reachable, then minted a fresh session.
- Two backgrounded `curl` POSTs to `/meta/connect` with the SAME `sessionId` + `pageId: "pg-703"`,
  raced via shell `&`/`wait`:
  ```
  A -> HTTP 201 {"id":"7a75d3ea-...","externalAccountId":"pg-703",...}
  B -> HTTP 400 {"detail":{"reason":"connect_session_consumed"}}
  ```
- Decisive signal: B got `connect_session_consumed` (blocked at the atomic claim, BEFORE reaching
  provisioning), not `external_account_in_use` (which is what the OLD non-atomic code would have
  produced for a loser that raced past the claim and only collided at `_persist_channel`'s partial-
  unique index). `GET /omnichannel/channels` confirms exactly ONE channel with `externalAccountId:
  "pg-703"`.

**4. A Messenger docx attachment webhook -> classified + stored-or-gracefully-unavailable (should-fix d).**
- POSTed a `page`-object webhook to the pre-existing `pg-702` FACEBOOK channel with a `file`
  attachment (`_ATTACHMENT_TYPES["file"] == "DOCUMENT"`) pointing at a `.docx`-named
  `fbcdn.net` URL -> `HTTP 200 {"status":"queued"}`.
- Resulting message row: `messageType: "DOCUMENT"`, `mediaUnavailable: true`, `externalMessageId:
  "m.probe4.docx"` - correctly classified, never dropped, never crashed the pipeline.
- **Environment caveat, disclosed rather than glossed over:** this lane has no `META_APP_ID`/
  `META_APP_SECRET` configured (same dev-safe posture the tester's pass ran under), so
  `MessengerAdapter._configured` is `False` and `fetch_media_url`'s dev-safe gate
  (`not self._configured or credentials.get("dev")`) skips the real CDN fetch for EVERY attachment
  type in this environment, not just DOCUMENT - a live curl probe therefore cannot reach the actual
  sniff-widening code path (the Meta CDN host allowlist is hardcoded to `fbcdn.net`/`fbsbx.com`/
  `cdninstagram.com` suffixes, so a local mock server cannot stand in for it either). The
  sniff-widening fix itself (`_is_allowed_fetch_mime(mime, kind="DOCUMENT")` accepting the outbound
  document family) is verified by the passing pytest suite instead:
  `test_fetch_media_url_document_kind_accepts_the_outbound_document_family` (a real zip-magic-bytes
  blob over an `httpx.MockTransport` against the `fbcdn.net` allowlist, asserting acceptance) and
  `test_inbound_messenger_document_attachment_stores_docx_blob` (full `_process` pipeline, asserting
  `media_key is not None`) - both included in the 1099-passed run above.

**5. A channel with an unknown `channel_type` inserted via `psql` -> channels list + thread list render, no crash; then deleted.**
- `INSERT INTO app_omnichannel.channels (..., channel_type, ...) VALUES (..., 'TELEGRAM', ...)` (id
  `probe5-telegram-chn`) - a value the frontend `ChannelType` union has never modelled.
- `GET /omnichannel/channels` (backend): `200`, row present, no 500.
- `agent-browser` (curl cannot exercise client-side JS): logged in as `demo@example.com`, opened
  `/omnichannel/settings/channels` - the row renders ("Probe Telegram (unmodelled)", Type badge
  "TELEGRAM", a generic question-mark icon from `channelCapabilities()`'s `UNKNOWN` fallback, `-` in
  the Phone Number column) with **zero console errors** (`agent-browser console` empty). Screenshot
  taken. Also opened `/omnichannel/inbox` and `/omnichannel/contacts` with the row present in the
  workspace - both loaded cleanly, zero console errors. This is the live confirmation of should-fix
  (a) - before the fix, `CHANNEL_CAPABILITIES['TELEGRAM']` was `undefined` and `.icon` would have
  thrown, crashing the Channels list.
- Cleanup: `DELETE FROM app_omnichannel.channels WHERE id = 'probe5-telegram-chn'` - confirmed gone
  from `GET /omnichannel/channels` afterward.

### Scope note

Per the coordinator's explicit instruction, this round does NOT renumber Alembic migrations, the
manifest version, or backlog ids (Blocker 3 + the merge checklist items are the merge coder's job).
The plan §8 backlog register (13 items) was added as provisional `BL-SS-147..162` rows
("renumbered at merge") in `documentation/backlogs/backlog.md`, alongside this tester's own
`BL-SS-163`/`164` additions - no collision, no renumbering performed.
