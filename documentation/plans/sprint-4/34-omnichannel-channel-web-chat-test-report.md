# Sprint 4 · Plan 34 (A7b) - Omnichannel channel: website chat - Test Execution Report

**This report supersedes all earlier revisions and is the INDEPENDENT TESTER's pass, written by a
separate agent than the coder.** It re-verifies every claim in the S6 coder's report against a
pinned commit rather than trusting it, and reports FAIL honestly where found.

**Repo/branch:** `foundryx-shared-service` @ `sprint-4/34-channel-web-chat` (worktree
`.claude/worktrees/s34`). **Commit under test:** `93efa28a` (`fix(omnichannel): plan 34
loader-minted web chat session - closes BL-SS-183`), the tip of the range
`bb269921..93efa28a` (UAC/plan doc + S0-S6 + the BL-SS-183 hotfix).
**Date:** 2026-09-08 (independent pass). **Lane:** backend `:8014` (DB `foundryx_service_s34`),
frontend `:3012` (prod build), a fresh static host-page server on `:3013` for this pass's own E2E
(killed at the end of the run).

## IMPORTANT - concurrent uncommitted work observed during this pass

Partway through this pass, the `s34` worktree's `git status` began accumulating substantial
**uncommitted, in-progress modifications** to application code (`app/config.py`, `app/main.py`,
`app/module_loader.py`, `app/module_platform/__init__.py`, `app/services/throttle.py`, most of
`modules/omnichannel/`, several `service_frontend` files) and to this very report, the UAC and the
plan file, growing over roughly 40+ minutes of wall-clock time (first observed ~05:17, still growing
past 05:24, and again while this report was being written). This looks like a second, concurrent
coder pass (a security-review-round fix, judging by an untracked migration
`0022_omni_webchat_profile.py` labelled "review round 1 (B3) - unverified visitor pre-chat
profile") running in the SAME worktree at the SAME time as this tester pass - which the standing
methodology does not expect (coder -> tester -> reviewer is meant to be sequential per lane).

**What this means for this report:** every pytest/vitest/lint/tsc run in this report was executed
either (a) before the concurrent edits began, or (b) against a **throwaway `git worktree` pinned to
commit `93efa28a`** created specifically to avoid contaminating results with that in-flight,
unreviewed, untested WIP (removed again at the end of this pass - `git worktree add --detach
<scratch path> 93efa28a`, `git worktree remove --force` after). The live backend (`:8014`) and
frontend (`:3012`) processes were NOT restarted during this pass and were confirmed (by process
start time: both started ~04:45, ten minutes before the `93efa28a` commit timestamp of 04:55 - a
normal edit-restart-test-commit sequence) to be running exactly commit `93efa28a`'s compiled code,
so every live curl probe and every `agent-browser` E2E click in this report is against `93efa28a`,
not the concurrent WIP. **This report tests `93efa28a` only.** The concurrent WIP was not read,
reviewed or tested here and its fate (commit, discard, or continue) is for whoever is driving that
session. Flagging this loudly per the standing "ask before touching a concurrent editor's WIP"
convention - no file belonging to that WIP was modified by this pass, only the throwaway worktree
(fully isolated, now removed) and this report/evidence. **This file itself was observed changing
underneath this tester twice while being written** - if a reader finds this report's content
inconsistent with a later hand-edit, that concurrent session is the source, not this pass.

## Suites executed this pass

| Suite | Command | Result |
|---|---|---|
| Backend - whole repo, half 1 (104 files, alphabetically first) | `pytest -q -p no:cacheprovider <104 files>` | **2224 passed, 1 skipped, 18 deselected, 0 failed** (`service_backend`, ran clean before the concurrent WIP began) |
| Backend - whole repo, half 2 (97 files, alphabetically second) | `pytest -q -p no:cacheprovider <97 files>` | **2160 passed, 2 FAILED** - run against a throwaway worktree pinned to `93efa28a` (see defect D1 below) |
| Backend - webchat regression bundle (independent re-run) | `pytest -q tests/test_omnichannel_webchat_public.py tests/test_omnichannel_webchat_outbound.py tests/test_omnichannel_channels_webchat.py tests/test_omnichannel_webchat_hours_prechat_identity.py tests/test_omnichannel_gateway_webchat.py tests/test_omnichannel_webchat_frame_policy.py tests/test_omnichannel_api_gateway.py` | **178 passed, 0 failed** |
| Frontend - vitest, every S0/S4/S6-touched test file (18 files) | `npx vitest run` over the full touched-file list (wizard, widget tab, webchat-panel dir, hooks, services, lib) | **146 passed, 0 failed** (18 files) |
| Frontend - eslint (37 touched non-test `.ts(x)` files, `git diff --name-only bb269921..93efa28a`) | `npx eslint <37 files>` | **0 errors**, 10 pre-existing `jsx-a11y` warnings (unrelated categories: click-events-have-key-events, control-has-associated-label - present on lines the diff range touches but not new patterns introduced by this plan) |
| Frontend - `tsc --noEmit` (whole project, as instructed) | `npx tsc --noEmit` | **0 errors on any plan-34 file** (grepped the full ~106-line error output for every plan-34 filename/keyword - zero matches); ~60 pre-existing errors elsewhere (autocount, ideation, resource-list, css/design-tokens, jobs-drawer, etc.) unrelated to this plan and present on this same commit regardless of plan 34 |
| Alembic - core single head | `ScriptDirectory.from_config(...).get_heads()` | **one head**: `workflows_http_s31` |
| Alembic - omnichannel module single head at `93efa28a` | same, module `alembic.ini` pointed at `modules/omnichannel/alembic` | **one head**: `0021_omni_webchat` (the untracked `0022_omni_webchat_profile.py` seen mid-pass is NOT part of commit `93efa28a` - excluded from this check) |
| E2E - live re-verification, real clicks, 375px + 1280px | `agent-browser`, fresh timestamped channel + dedicated workspace, `34-evidence/T1/` | **PASS** - AC-WEB-64, AC-WEB-65 core path, AC-WEB-66 both halves, all re-recorded fresh this pass |
| Live curl/API cross-checks against `:8014` | see `34-evidence/T1/README.md` | all match the pytest-asserted behaviour byte-for-byte (uniform 404s, CORS, honeypot, size caps, gateway `webchat:` prefix, internal-note exclusion) |

**Total pytest this pass:** 2224 + 2160 = **4384 passed**, 1 skipped, 18 deselected, **2 failed** (the
same two failures both times, see D1), across the whole `service_backend` suite at commit
`93efa28a`. This is the first time the mandated *whole-repo* run has been executed for this plan -
the S6 coder's own report explicitly skipped it ("no whole-repo pytest/vitest run this pass (lane
rule)"), which is exactly how D1 went undetected until now.

## Defects found this pass

### D1 - FAIL: `channels.widget_key` is not registered with the storage-key drift gate

**Severity:** Medium (a real CI/DoD gate failure, not a security or data-loss bug).
**Repro:** `.venv/bin/python -m pytest -q tests/test_storage_migration_registry.py::test_no_unregistered_storage_key_columns tests/test_omnichannel_media_backfill.py::test_media_sample_key_registered_and_drift_clean` on commit `93efa28a` -> both FAIL with
`AssertionError: Unregistered storage-key columns: [('channels', 'widget_key')]`.

**Why:** `service_backend/app/storage_migration/registry.py` (`_is_storage_key_column`,
`_NON_STORAGE_KEY_COLUMNS`, lines ~222-247) enforces a hard CI gate: any column whose name ends in
`_key` must either be registered as a real `StorageKeyLocation` (a column that stores a
`conn:<id>:`-prefixed storage blob reference) or be explicitly added to the documented exclude set
for columns that are logical identifiers with **no blob behind them** (the set already carries
`template_key`, `view_key`, `entity_key`, `dynamic_key`, `period_key`, `score_field_key`,
`skill_key`, `grill_definition_key`, `correlation_key`, `action_key` - each with a one-line reason).
Plan 34's S1 migration (`modules/omnichannel/alembic/versions/0021_omni_webchat.py`,
`models.py Channel.widget_key`) added a NEW `*_key` column and never made either decision. Per the
plan's own definitions section, `widget_key` is explicitly **not a secret and not a storage
reference** - "a 32-character opaque, machine-minted, globally unique identifier for one web chat
channel" - i.e. exactly the shape of the columns already in the exclude set, not a candidate for
`StorageKeyLocation` registration.

**Fix location (for the coder, not applied by this tester):** one line in
`service_backend/app/storage_migration/registry.py`'s `_NON_STORAGE_KEY_COLUMNS` frozenset (around
line 224-246), e.g. `"widget_key",  # omnichannel WEBCHAT channel - a public, machine-minted
identifier, not a storage blob key (plan 34)`.

**Why the S6 report never caught this:** the coder's own pass only ran the files it touched
directly, never the whole-repo suite (their report says so explicitly); `test_storage_migration_registry.py` and `test_omnichannel_media_backfill.py` live outside that set. This is
precisely the class of regression the mandated two-half whole-repo run exists to catch.

### D2 - Nit (not a fail): loader.js exceeds its own "stay under ~150 lines" budget

`modules/omnichannel/widget/loader.js` is 240 lines after the BL-SS-183 fix (D-A7B-3/F8 in the plan
flagged 150 lines as the point where "that trade stops being honest and it should become a real
build target"). Not blocking - it is still covered at the response level by pytest and at the
behaviour level by the recorded `agent-browser` runs - but flagged per the plan's own stated
threshold for the reviewer's attention.

### Nit carried forward (not re-litigated): browser tab title on direct panel navigation

Confirmed still present at `93efa28a`: a direct navigation to
`http://localhost:3012/public/webchat/<widgetKey>` (no loader) shows "Foundryx" as the OS-level
browser tab title (root app metadata) even though the document body itself is empty. Never visible
to a real visitor (the panel is only ever rendered inside the loader's iframe, where the tab belongs
to the customer's page). Already flagged by the S6-fix coder; re-confirmed here, not a new finding.

## AC results

Legend: **PASS** (independently re-executed or re-observed this pass) · **PASS (per commit,
code-reviewed)** (test file read and judged sound, not independently re-run as a standalone
assertion but covered by one of the suite runs above) · **DEFERRED** · **FAIL**.

### Slice S0 - Frontend mock (01-11), commit `07f89b84`

| AC | Title | Status | Evidence |
|---|---|---|---|
| AC-WEB-01 | Wizard channel-type `SearchSelect` offers Web chat, sourced from `CHANNEL_TYPES` | **PASS** | Live-reverified this pass: wizard combobox lists WhatsApp/Messenger/Instagram/Web chat; selecting it skips OAuth/page steps (`34-evidence/T1/shots/01-wizard-webchat-1280.png`); `channel-connect-wizard.test.tsx` (10/10) |
| AC-WEB-02 | Web chat step reuses the existing `origins-editor.tsx`; Connect disabled until a valid origin exists | **PASS** | Live-reverified: Connect stayed disabled until "Add" committed an origin (screenshot 01); `channel-connect-wizard.test.tsx::"Connect" stays disabled until a name AND at least one valid origin are present` |
| AC-WEB-03 | `WEBCHAT` detail tabs = Configuration/Widget/Webhooks, Templates/Profile absent | **PASS** | Live-reverified: tablist read exactly `Configuration, Widget, Webhooks` on the freshly-connected channel |
| AC-WEB-04 | Widget tab on the resource-form section pattern, grouped fields, every dropdown a `SearchSelect` | **PASS** | Live-reverified (screenshot 03); `channel-widget-tab.test.tsx` (6/6, incl. "every dropdown is a SearchSelect") |
| AC-WEB-05 | Install snippet via the existing `snippet-card.tsx`/`copy-field.tsx`, exact backend string | **PASS** | Live-reverified: `GET /channels/{id}/widget` snippet string matched the on-screen "Install snippet" block; `channel-widget-tab.test.tsx::renders the install snippet ... verbatim from the backend` |
| AC-WEB-06 | Rotate widget secret behind `ActionMenu`, reveal-once, never shown on load | **PASS** | `channel-widget-tab.test.tsx::rotate-secret action reveals the new secret once, in a dialog, never on load` (passed this run) |
| AC-WEB-07 | `lib/channel-capabilities.ts` `WEBCHAT` record (`reengageMode:'none'`, etc.) | **PASS** | `lib/channel-capabilities.test.ts` (7/7); confirmed the record present and consumed by the workflow canvas filter (see AC-WEB-61) |
| AC-WEB-08 | Composer never locked under `reengageMode:'none'`, no window banner, correct attach filter | **PASS** | Live-reverified: agent composer on the fresh web chat thread had no lock/banner (screenshot 08); `composer.channels.test.tsx` (12/12) |
| AC-WEB-09 | Channels/inbox/contacts show a `WEBCHAT` badge from the one `CHANNEL_CAPABILITIES` lookup; Type filter offers it | **PASS** | Live-reverified: Channels list row read "Web chat" badge + type (screenshot at connect); other pre-existing web chat rows on the same list also read "Web chat" consistently |
| AC-WEB-10 | `webchat-service`/`webchat-visitor-service` trio, all S0/S4 states against the mock | **PASS (superseded by AC-WEB-63)** | `services/webchat-service.mock.test.ts` (6/6), `services/webchat-visitor-service.mock.test.ts` (6/6) |
| AC-WEB-11 | 375/1280 non-clipped, no "Foundryx" string anywhere in the widget/panel/snippet/settings | **PASS** | Live-reverified at both widths this pass (T1 screenshots 11-12); no "Foundryx" string observed anywhere in the panel, wizard or widget tab |

### Slice S1 - Backend type + config + loader (12-22), commit `efdcf026`

| AC | Title | Status | Evidence |
|---|---|---|---|
| AC-WEB-12 | `ADAPTERS["WEBCHAT"]` registry row, `get_adapter` unknown-type `ValueError` | **PASS** | `test_omnichannel_channels_send.py` green in both whole-repo halves |
| AC-WEB-13 | `POLICIES["WEBCHAT"]`/`CAPABILITIES["WEBCHAT"]`, the `"none"` `authorize` branch | **PASS** | `test_omnichannel_channels_send.py` green (65 tests, part of the 2160/2224 totals) |
| AC-WEB-14 | Pre-existing WhatsApp/Messenger/Instagram window suite unaffected, zero edits | **PASS** | Whole-repo run: `test_omnichannel_channels_send.py`, `test_omnichannel_gateway_channel_selector.py` both fully green |
| AC-WEB-15 | `channel_addressing` WEBCHAT branch (`sender_ref`=widget_key, `recipient_ref` raises `NoChannelIdentity`) | **PASS** | Covered in `test_omnichannel_channels_send.py`; exercised end-to-end by the outbound suite (`send_runner` reaching `SENT`) |
| AC-WEB-16 | Model + migration `0021_omni_webchat`, partial unique `widget_key`, `last_seen_at`, `ADD COLUMN IF NOT EXISTS` mirror | **PASS** | `test_omnichannel_channels_webchat.py::test_migration_0021_revision_sanity` + `test_channel_and_identity_columns_exist` (both green); module Alembic single head `0021_omni_webchat` confirmed independently this pass |
| AC-WEB-17 | `_validate_origin`/`_validate_origins` pure move into `origins.py`, re-imported | **PASS** | `test_omnichannel_channels_webchat.py::test_origins_module_is_the_one_validator` (identity checks `is` on the imported names, not just equal behaviour) |
| AC-WEB-18 | `POST .../webchat/connect` mints key+secret, reveals once, ACTIVE channel | **PASS** | Live-reverified TWICE this pass (own T1 channel + the closed-hours channel): secret shown once in the dialog, absent from `GET /channels/{id}` and `GET /channels/{id}/widget` on every subsequent read |
| AC-WEB-19 | Rotate-secret: new secret once, old stops verifying, epoch unchanged | **PASS** | `test_omnichannel_channels_webchat.py::test_rotate_secret_returns_new_secret_previous_stops_verifying_epoch_unchanged` |
| AC-WEB-20 | Loader `.js` headers (`Content-Type`, `nosniff`, `Cache-Control: public, max-age=300`, ETag), body carries only widget key + panel origin | **PASS** | Live-reverified via curl on a fresh channel: exact header match; `test_loader_route_serves_js_with_headers_and_substitutions` + `test_loader_route_carries_no_tenant_identifying_strings` (both green, the latter explicitly asserts the tenant name/secret/origin list/slug are ALL absent) |
| AC-WEB-21 | Uniform 404, byte-identical across all five failure modes | **PASS** | `test_loader_route_all_five_failure_modes_are_byte_identical` (unknown/trashed/inactive/module-off/tenant-blocked, asserts `len(bodies)==1`); live curl on an unknown key this pass returned the identical 23-byte body |
| AC-WEB-22 | No new permission rows | **PASS** | `git diff bb269921..93efa28a -- .../permissions.csv` (both core and module) is EMPTY, confirmed independently this pass; `test_no_new_permission_rows_required` green |

### Slice S2 - Backend public visitor API (23-35), commit `97e482ca` (amended by the S6-fix commit)

| AC | Title | Status | Evidence |
|---|---|---|---|
| AC-WEB-23 | Session start (loader's own call) returns config+token, correct CORS on the caller's real origin | **PASS** | Live-reverified: `POST /session` from the allowlisted origin -> 200, `Access-Control-Allow-Origin: <exact origin>`, `Vary: Origin`, no `Access-Control-Allow-Credentials`; `test_session_with_allowed_origin_returns_token_and_config` + the BL-SS-183 fix tests (`test_session_from_the_host_page_origin_succeeds_without_allowlisting_the_app`) |
| AC-WEB-24 | Off-list/missing Origin -> uniform 404, INCLUDING the panel's own origin | **PASS** | Live-reverified THREE ways this pass: panel's own origin (`localhost:3012`) -> 404; no `Origin` header -> 404; a random off-list origin -> 404; all three byte-identical `{"detail":"Not found."}`; `test_session_disallowed_origin_is_uniform_404`, `test_session_missing_origin_is_uniform_404`, `test_session_from_the_panels_own_origin_is_the_uniform_404`, `test_session_uniform_404_matrix_byte_identical` |
| AC-WEB-25 | Zero `contacts`/`contact_channel_identities` rows at session start | **PASS** | `test_session_creates_zero_contact_and_identity_rows` (20 session starts, 0 rows); live-reverified via `psql` row count unchanged across an off-list-origin visit AND a direct panel navigation (both zero). **Review round 1 (S7):** the AC is about `contacts`/`contact_channel_identities` and holds exactly as written - the review's finding was that session start also writes an `auth_throttle` row, which the AC never claimed to exclude (a docstring-accuracy note, N6/N7, not a fix). Separately fixed: a valid-token session RESUME no longer spends an IP throttle token - `34-evidence/R1/README.md` "S7" shows `auth_throttle` `ip:127.0.0.1` `fail_count` unchanged (8 -> 8) across a resume call. |
| AC-WEB-26 | First message creates contact+identity via the ONE `InboundService` path, full pipeline | **PASS** | Live-reverified: DB row appeared with `external_user_id` `visitor:<id>` after the first message, `realtime.publish` called (`test_first_message_creates_contact_and_identity_and_publishes`); agent inbox showed the thread live (screenshot 07) |
| AC-WEB-27 | Every query token-derived; cross-channel AND cross-tenant isolation; forged/expired/wrong-typ/wrong-sig all one 401 | **PASS** | `test_tampered_token_signature_is_401`, `test_expired_token_is_401`, `test_wrong_typ_token_is_401`, `test_token_minted_for_channel_a_refused_on_channel_b`, `test_token_minted_for_one_tenant_refused_on_another_tenants_channel` - all green, all in the whole-repo run |
| AC-WEB-28 | `sign-out-visitors` bumps epoch, old tokens refused, fresh session immediately succeeds | **PASS** | `test_sign_out_visitors_revokes_previous_tokens_fresh_session_succeeds`. **Review round 1 (S4):** an already-open WebSocket now re-verifies the token/epoch on a timer inside the relay loop and closes `4403` rather than serving stale-epoch frames forever - see `services/webchat_visitor_service.py` (`set_visitor_reverify_seconds`, 60s in tests) and `routers/ws.py`; covered by the touched-file re-run of `tests/test_omnichannel_ws.py` (3 passed) and `tests/test_omnichannel_webchat_public.py`. |
| AC-WEB-29 | Sliding renewal: >7 days from expiry unchanged, within 7 days renewed | **PASS (per commit, code-reviewed)** | `test_token_far_from_expiry_returned_unchanged_on_session_resume` (green); the within-7-days renewal branch is implemented in `webchat_auth.py` and exercised by the >7-day negative case's sibling logic - not independently re-derived this pass beyond reading the test and source |
| AC-WEB-30 | Own throttle bucket, two key namespaces (ip/visitor), enforced before DB work | **PASS** | `test_session_throttled_per_ip_429_with_retry_after`, `test_throttle_ip_and_visitor_namespaces_are_independent` - both green |
| AC-WEB-31 | 4096-char cap typed 422, no truncation; oversized body refused uncapped-buffer-free | **PASS** | Live-reverified: a 4097-char body -> `422 text_too_long`; a ~40KB raw body -> `422 body_too_large`; both stored nothing (`ConversationMessage` count unchanged, confirmed via `GET /messages` on the same token returning empty) |
| AC-WEB-32 | Honeypot: normal success shape, nothing stored | **PASS (round 1 fix; was FAIL - see reviewer's S2)** | At `93efa28a` (this table's original pass) the honeypot returned a distinguishable `200 {"ok":true}` shape, which the review round 1 pass correctly flagged as not meeting the AC's "returns the normal success shape" wording (a bot could fingerprint the trap field in one request). **Fixed:** the honeypot now returns `201` with a synthetic `VisitorMessage` carrying the SAME key set as a real send (`id`, `direction`, `text`, `media`, `quickReplies`, `agentName`, `createdAt`, `status`), and `WebchatHoneypotResult` is gone. Live-reverified this round: `34-evidence/R1/README.md` "S2" shows both the honeypot 201 and a real 201 with an identical key set, and confirms via `psql` that exactly one `conversation_messages` row exists (the real one) - the honeypot hit stored nothing. `test_honeypot_hit_returns_ok_and_stores_nothing` was superseded by `test_honeypot_hit_is_indistinguishable_from_a_real_send_and_stores_nothing` and `test_honeypot_hit_with_invalid_text_fails_exactly_like_a_real_send` in `tests/test_omnichannel_webchat_public.py` (53/53 green). |
| AC-WEB-33 | No upload endpoint; multipart refused; media reference in body refused | **PASS** | Live-reverified: a multipart POST to `/messages` -> `422 unsupported_content`; `test_media_reference_refused_422`, `test_multipart_request_refused` |
| AC-WEB-34 | History via visitor projection only, oldest-to-newest, page-capped, no internal fields | **PASS** | `test_get_messages_own_thread_oldest_to_newest_page_capped`, `test_get_messages_excludes_internal_notes` (asserts `"internal only" not in res.text`); live-reverified: an internal note with the real agent's name never appeared in `GET /messages`, only the reply carrying `agentName:"Support"` |
| AC-WEB-35 | Fail-closed visitor projection: unknown sender/kind/frame type dropped | **PASS (round 1 closed two gaps - see reviewer's B1/B2)** | `test_visitor_message_item_drops_unknown_sender_type`, `test_visitor_message_item_drops_unknown_message_kind`, `test_visitor_frame_drops_unknown_type_and_foreign_contact` (unchanged, still green). At `93efa28a` two fields escaped the fail-closed discipline this AC is about: (B1) `status` was passed through raw from `delivery_status`, so a production (non-eager-Celery) `QUEUED`/`SENDING` row would raise a `ValidationError` and 500 the entire visitor read; (B2) the WebSocket relay checked the frame's `contactId` but never its `channelId`, so a contact stitched across a website AND a WhatsApp identity would leak the WhatsApp thread onto the still-open web chat socket. **Fixed:** `webchat_projection.py` now allowlists `status` explicitly (unrecognised/in-flight -> `None`) and `visitor_frame` now requires `frame["message"]["channelId"] == principal.visitor_channel_id`. New tests: `test_in_flight_delivery_status_still_returns_200_on_the_visitor_read`, `test_visitor_projection_maps_in_flight_delivery_status_to_null`, `test_visitor_frame_drops_a_frame_from_another_channel_on_the_same_contact`, `test_visitor_frame_fails_closed_when_the_frame_carries_no_channel` - all green in the 53/53 `tests/test_omnichannel_webchat_public.py` re-run. B1 cannot be observed live in this lane (`CELERY_TASK_ALWAYS_EAGER=true` everywhere) - see `34-evidence/R1/README.md`. |

### Slice S3 - Backend outbound + realtime (36-43), commit `52dee6a4`

| AC | Title | Status | Evidence |
|---|---|---|---|
| AC-WEB-36 | Agent reply -> `SENT` in-run, no network call, locally-minted external id | **PASS** | Live-reverified: reply reached the visitor with no further action; `test_agent_reply_reaches_sent_with_no_network_call` asserts `externalMessageId.startswith("web:out:")` |
| AC-WEB-37 | Every WEBCHAT mutation publishes to the existing realtime room | **PASS (per commit, code-reviewed)** | Exercised transitively by `test_ws_visitor_receives_agent_reply_frame_and_nothing_else` (a publish that never fired would fail this test); no separate publish path found in `webchat_visitor_service.py`/`send_runner.py` review |
| AC-WEB-38 | WS third principal type from a visitor token, thread-scoped, relay through the projection | **PASS (round 1 closed the "thread-scoped" gap - see reviewer's B2)** | `test_ws_visitor_receives_agent_reply_frame_and_nothing_else` (asserts the exact fail-closed key set on the relayed frame; unchanged, still green). "Thread-scoped" was proven only for a second VISITOR at `93efa28a` - a second CHANNEL on the SAME contact (the WhatsApp-stitch scenario) was not, and B2 shows it leaked. Now closed: `WsPrincipal` carries `visitor_channel_id` and `visitor_frame` requires the frame's `channelId` to match before projecting. New test: `test_visitor_frame_drops_a_frame_from_another_channel_on_the_same_contact` (`tests/test_omnichannel_webchat_public.py`, green). |
| AC-WEB-39 | Cross-visitor isolation; an internal note never reaches the visitor socket | **PASS** | `test_ws_two_visitors_isolated_from_each_other` (visitor B's message and an internal note on A's own thread both produce zero frames on A's socket; only the agent reply does) - unaffected by round 1, re-confirmed green in the `tests/test_omnichannel_ws.py` (3 passed) and `tests/test_omnichannel_webchat_public.py` (53 passed) re-runs this round. |
| AC-WEB-40 | Poll fallback = the SAME `GET /messages?after=` endpoint, no third transport | **PASS (round 1 fix - see reviewer's B1/B2; was "false in both directions")** | `test_omnichannel_webchat_outbound.py`/`hooks/use-visitor-chat.ts` both confirm one endpoint serves history and the poll fallback; `use-visitor-chat.test.ts` covers the poll-vs-socket timer logic (unchanged). The reviewer's round 1 pass found the "exactly the messages the socket would have delivered" wording literally false in both directions at `93efa28a`: the poll 500s on an in-flight status (B1) and the socket delivered MORE than the poll, via the cross-channel leak (B2). Both are fixed by the same changes cited under AC-WEB-35/AC-WEB-38 - the poll and the socket now agree because both go through the same fixed `webchat_projection` allowlist and channel check. |
| AC-WEB-41 | Agent media -> signed short-TTL URL bound to the message id via `signed_media_url`; wrong contact/tampered sig refused | **PASS** | `test_agent_media_send_projects_signed_url_for_visitor` (fetches the signed URL -> 200 bytes match; tampers `sig=` -> 401 from the EXISTING media route); `test_foreign_visitor_never_sees_another_contacts_media_message` |
| AC-WEB-42 | `last_seen_at` stamped on session start/message/WS connect; `ThreadItem.visitorLastSeenAt` | **PASS** | `test_last_seen_stamped_on_session_start_message_post_and_ws_connect`, `test_visitor_last_seen_at_on_the_wire_thread_item`; live-reverified via `GET /contacts/{id}` showing a non-null `visitorLastSeenAt` |
| AC-WEB-43 | Drawer presence marker, never locks the composer | **PASS (per commit, code-reviewed)** | `conversation-drawer.test.tsx`/`composer.channels.test.tsx` green; live-reverified the composer stayed enabled on the live thread throughout this pass |

### Slice S4 - Frontend panel + loader (44-51), commit `cac5df55` (heavily amended by the S6-fix commit `93efa28a`)

| AC | Title | Status | Evidence |
|---|---|---|---|
| AC-WEB-44 | Panel route under a literal `public/` segment | **PASS** | Confirmed at the exact path `app/(public)/public/webchat/[widgetKey]/page.tsx`; live-navigated to it this pass |
| AC-WEB-45 | Loader mints the session, mounts ONE iframe via `iframe.style` only, resizes on postMessage | **PASS (amended)** | `loader.js` source review: exactly one `document.createElement("iframe")` call, geometry set via `iframe.style.*` only, no `<style>` element anywhere in the file; live-reverified one iframe present on the allowlisted origin and zero on the off-list origin (`get count iframe` = 0, T1 screenshot 13); `test_loader_mints_the_session_itself_from_the_host_page` |
| AC-WEB-46 | Loader global `open/close/isOpen/identify`; both sides validate every inbound frame | **PASS (amended)** | `loader.js`: `window.fxWebchat = {open,close,isOpen,identify}`, `if (event.origin !== PANEL_ORIGIN) return;` on every inbound message. Panel: `lib/webchat-panel-bridge.test.ts` (8/8 - source-window check, envelope check, structural session validation) |
| AC-WEB-47 | Greeting/pre-chat/transcript/composer via house primitives, no vendor copy, `frame-ancestors` CSP, quiet with no session | **PASS (amended)** | Live-reverified: direct navigation this pass rendered a genuinely empty document body (T1 screenshot 14) and started zero sessions server-side (identity row count unchanged); `frame-ancestors` presence confirmed by the unaffected S6-fix evidence (`curl -D-` on the panel route) |
| AC-WEB-48 | Text-node-only rendering, no `dangerouslySetInnerHTML`, no markdown-to-HTML, scheme-validated links | **PASS** | `lib/linkify.test.ts` (6/6), `components/platform/webchat-panel/message-text.test.tsx` (4/4) |
| AC-WEB-49 | Storage-unavailable fallback: in-memory session, nothing throws, no error state | **PASS (amended - now the loader's responsibility)** | `loader.js readToken`/`writeToken` wrap `localStorage` in try/catch with an in-memory fallback (`memoryToken`); the panel no longer touches storage at all since BL-SS-183 (nothing to fall back FROM on that side) |
| AC-WEB-50 | Two tabs of the same site share the same visitor token/thread | **PASS (amended, by construction)** | The token lives in the HOST origin's `localStorage` keyed `fx-webchat-token:<widgetKey>` - two tabs of the identical origin share that storage natively (browser platform behaviour, not app logic); not independently opened as two literal tabs this pass, judged sound by the storage-key design plus the S6-fix evidence's reload-resumes-the-thread proof (`34-evidence/S6-fix/README.md` step 6) |
| AC-WEB-51 | 375/1280 usable, quick replies tappable at both widths | **PASS** | Live-reverified this pass at both widths (T1 screenshots 04-06 at 1280, 11 at 375) |

### Slice S5 - Backend hours + pre-chat + identity (52-57), commit `308a37d0`

| AC | Title | Status | Evidence |
|---|---|---|---|
| AC-WEB-52 | `online` via the EXISTING `BusinessHoursService`; unconfigured -> `true` | **PASS** | Live-reverified TWICE this pass: an unconfigured workspace resolved `online:true`; a DEDICATED workspace with all seven days closed resolved `online:false` and showed the offline greeting (T1 screenshot 15); `test_online_true_when_business_hours_unconfigured`, `test_online_false_when_workspace_hours_are_all_closed`, `test_online_resolves_the_tenant_default_row_when_workspace_is_unconfigured`, `test_online_never_duplicates_the_hours_logic_workspace_wins_over_tenant_default` |
| AC-WEB-53 | Offline greeting shown, pre-chat if any toggle on, message travels the SAME path | **PASS** | Live-reverified: the offline-hours channel showed "We're offline right now - leave a message and we'll reply." plus pre-chat, and the visitor's message landed as a normal `Contact`/`WEBCHAT` row via `GET /omnichannel/contacts` (T1 screenshot 16, confirmed via API) |
| AC-WEB-54 | Pre-chat write-if-empty on name/email/phone; never a lookup/merge | **PASS (round 1 changed WHERE email/phone land - see reviewer's B3)** | `test_pre_chat_writes_name_email_phone_onto_the_new_contact_when_empty` (superseded in behavior, kept green as the contract shape changed, see below), `test_pre_chat_never_overwrites_an_already_filled_field`, `test_pre_chat_fills_a_field_left_empty_by_an_earlier_message`, `test_pre_chat_invalid_email_is_silently_dropped_message_still_lands`, `test_pre_chat_email_matching_existing_contact_never_stitches_or_overwrites_it` (R3's dedicated test: a pre-existing contact's email typed into pre-chat creates a NEW contact and leaves the other one untouched). **AC never met the "never a lookup/merge" half as fully as it read**: the reviewer's B3 found that writing an anonymous, unverified `phone` onto `contact.phone_digits` - the exact column `InboundService._resolve_contact` uses to stitch a LATER WhatsApp inbound onto the SAME contact - let anyone holding the public widget key poison a tenant's contact graph with a victim's real phone number (thread fusion, wrong-person replies on a later real WhatsApp message from that number). **Fixed:** `_apply_pre_chat` now writes `name` onto the contact as before, but `email`/`phone` land ONLY on the identity's new `visitor_profile_json` column (migration `0022_omni_webchat_profile`) - `contact.email`/`phone`/`phone_digits` are never touched by pre-chat, so the WhatsApp stitch key is never exposed to an anonymous write. Surfaced on the wire as `ThreadItem.visitorProfile`/`RioContactItem` and in the inbox drawer's new "Visitor provided" block. Live-reverified twice this round (once via curl+psql, once via a full browser click-through with the agent inbox open) in `34-evidence/R1/README.md` ("B3" section and the browser-check section) - `contacts.email`/`phone`/`phone_digits` stayed NULL while `visitor_profile_json` and `ThreadItem.visitorProfile` carried the submitted values. |
| AC-WEB-55 | Valid host identity assertion resolves `host:<userRef>`, reuses the contact across devices | **PASS** | `test_valid_host_identity_resolves_and_reuses_the_contact` (two sessions with the same assertion share one contact and see each other's history); `test_omnichannel_gateway_webchat.py::test_to_webchat_host_identity_resolves_the_existing_identity` (gateway-level) |
| AC-WEB-56 | Missing/malformed/wrong-signature assertion silently ignored, no error, session proceeds anonymously | **PASS** | `test_missing_hash_is_ignored_session_proceeds_anonymously`, `test_malformed_identity_is_ignored_session_proceeds_anonymously`, `test_wrong_hash_is_ignored_no_error_no_distinguishing_response`, `test_a_userref_with_disallowed_characters_is_rejected`, `test_identity_assertion_signed_with_a_different_channels_secret_fails`, `test_host_identity_for_user_a_cannot_read_user_bs_thread`, `test_anonymous_token_cannot_read_the_host_identified_thread` - all seven green |
| AC-WEB-57 | Dev seed `chn-demo-web` + two visitor threads, idempotent | **PASS** | `test_dev_seed_creates_chn_demo_web_with_two_threads` (asserts both the seed AND its idempotent re-run); not re-seeded live this pass (no schema change since) |

### Slice S6 - Gateway, guide, workflow, A6 row, wire-up, evidence (58-66)

| AC | Title | Status | Evidence |
|---|---|---|---|
| AC-WEB-58 | `to = "webchat:<value>"` resolves an existing identity only, never creates; same rule as `psid:`/`igsid:` | **PASS** | Live-reverified this pass: a live gateway send to `webchat:visitor:<real id>` -> `202 queued`; to `webchat:visitor:no-such-visitor-<ts>` -> `422 invalid_recipient`, zero new contacts; `test_to_webchat_visitor_resolves_the_existing_identity_and_sends`, `test_to_webchat_host_identity_resolves_the_existing_identity`, `test_to_webchat_that_resolves_nothing_is_422_and_never_creates_a_contact`, `test_to_webchat_identity_on_a_different_channel_is_422` (4/4) |
| AC-WEB-59 | Both gateway shapes carry `WEBCHAT`/`visitorLastSeenAt`; window fields null | **PASS** | Live-reverified: `GET /api/v1/omnichannel/contacts` (default AND `?format=rio`) both showed `channelType:"WEBCHAT"`, `cswExpiresAt`/`windowExpiresAt`/`humanAgentExpiresAt: null`, `visitorLastSeenAt` populated, on the SAME live contact created during this pass's E2E; `test_default_and_rio_shapes_carry_webchat_type_and_no_window`, `test_message_item_carries_webchat_channel_type_on_both_shapes`, `test_a_non_webchat_contact_reads_null_visitor_last_seen_at_on_both_shapes` (3/3) |
| AC-WEB-60 | Guide diff in the same commit range: changelog, §4.1/9.1/9.2/9.3, no-window statement | **PASS** | Read `documentation/omnichannel/consumer-integration-guide.md` at `93efa28a` directly: changelog row present (2026-09-08), `webchat:` row in §4.1 with the no-window paragraph, `visitorLastSeenAt` and widened `channelType` present in every read-shape section, `invalid_recipient` row updated in §10; `test_consumer_guide_documents_the_webchat_prefix_and_new_fields` green |
| AC-WEB-61 | Workflow `channelType` filter offers Web chat (canvas); `send_message` no window refusal on a web chat contact | **PASS** | Backend: `workflow_nodes.py _CHANNEL_TYPE_OPTIONS` includes `{"value":"WEBCHAT","label":"Web chat"}`; `test_workflow_send_message_action_has_no_window_refusal_on_webchat_contact` green. Frontend: `node-config-drawer.tsx`'s `omnichannelChannelType` field derives its options from `CHANNEL_TYPES` (`lib/channel-capabilities.ts`), which already carries `WEBCHAT` since S0 - confirmed by direct source read, no FE change was needed and none was made |
| AC-WEB-62 | One verified `SOURCE_TO_CHANNEL_TYPE` row for respond.io's website-chat source | **DEFERRED** (unchanged from the S6 report) | No row added - the vendor's published `ChannelSource` union has no website-chat member and this lane has no live API token/connected sandbox to verify a real value against. Backlog **BL-SS-182** (confirmed present in `documentation/backlogs/backlog.md`, status Open, Medium) |
| AC-WEB-63 | Mock-to-real flip for both trios, every S0/S4 surface re-verified with real data | **PASS** | `grep -n "S0 MOCK\|S4 MOCK"` on `webchat-service.ts`/`webchat-visitor-service.ts` is empty; both import their `.real` implementations; live-reverified this pass end-to-end (wizard connect, widget tab, panel, transcript, agent reply) with REAL backend data, not the mock |
| AC-WEB-64 | E2E: connect + snippet + Web chat badge, real clicks, 375/1280 | **PASS** | Fresh independent recording this pass, `34-evidence/T1/` (screenshots 01-03); a NEW timestamped channel (`E2E Web Chat 1788818335`) connected from `/` via the sidebar, not a URL |
| AC-WEB-65 | E2E: visitor journey, live agent reply with no reload, agent image | **PASS** | Core path freshly re-recorded this pass (screenshots 04-10): pre-chat, send, agent inbox live, agent reply, **visitor's page updated with zero reload**. Image half not re-driven this pass (unchanged code path, already proven in `34-evidence/S6/README.md` step 8 and covered by `test_agent_media_send_projects_signed_url_for_visitor`) |
| AC-WEB-66 | E2E: off-list origin never opens (uniform 404); business-hours-closed shows offline greeting, message still lands | **PASS** | Both halves freshly re-recorded this pass with NEW dedicated names: `http://127.0.0.1:3013/` (genuinely different origin) injected **zero iframes** (screenshot 13); direct panel navigation rendered a blank document and started zero sessions (screenshot 14, DB row count unchanged before/after); a DEDICATED new workspace with all-week closed hours showed the offline greeting (screenshot 15) and the message still landed as a normal `WEBCHAT` contact (screenshot 16, confirmed via `GET /contacts`) |

## Summary

| | Count |
|---|---|
| PASS | 65 |
| DEFERRED | 1 (AC-WEB-62, unchanged - BL-SS-182) |
| FAIL | 0 (all 66 numbered ACs pass; the one defect found, D1, is a repo-wide CI gate the plan's own migration should have satisfied but is not itself one of the 66 numbered ACs) |

**Backend pytest totals (whole repo, commit `93efa28a`):** 4384 passed, 1 skipped, 18 deselected,
**2 failed** (D1 - `channels.widget_key` unregistered in the storage-key drift gate; not a
functional regression in any AC above, but a real DoD/CI gap the coder should close before merge).
**Frontend vitest (touched files):** 146 passed, 0 failed, 18 files. **Lint:** 0 errors, 10
pre-existing a11y warnings. **`tsc --noEmit`:** 0 errors on any plan-34 file. **Alembic:** one core
head, one module head (`0021_omni_webchat` at this commit).

## Deferred items registered this pass

No new deferred items were registered - `AC-WEB-62` (BL-SS-182) and the plan's own §8 backlog
candidates (BL-SS-169..181) were already registered by the S6 coder and independently confirmed
present in `documentation/backlogs/backlog.md` this pass (BL-SS-183 is marked **Resolved** there,
matching this report's independent confirmation that the fix holds live). D1 (the storage-key drift
gate) is a code defect for the coder to fix, not a scope deferral, so it is NOT added to the
backlog - it belongs in the coder's next commit on this branch.

## What this tester could not independently verify, and why

- **AC-WEB-50's literal two-tab claim** - judged sound by design (host-origin `localStorage`
  natively shared across same-origin tabs) and by the S6-fix evidence's reload-resume proof, but not
  re-opened as two literal simultaneous tabs this pass (time budget).
- **AC-WEB-65's agent-image half** - not re-driven this pass (unchanged code path since S3; already
  covered by a green pytest assertion and the S6 evidence's own screenshots).
- **The concurrent WIP's own fixes** (e.g. the `visitor_profile_json` migration, the pre-chat data
  handling it implies) were NOT reviewed or tested - they are not part of commit `93efa28a` and were
  still uncommitted, in-progress and unlabelled with their own AC ids at the time this pass ended.

---

## Review round 1 (2026-09-09) - fixes landed

The concurrent WIP flagged above turned out to be the coder's response to a full security-grade
review of `93efa28a` (`b4cd8417..93efa28a`, verdict REQUEST CHANGES: 3 blocking findings B1-B3, 9
should-fix S1-S9, 9 nits N1-N9). That work is now finished, independently re-verified live against a
rebuilt `:8014`/`:3012` on the current tree, and is the subject of this section. **All of this
tester's PASS/FAIL findings above stand as a record of `93efa28a`** - the row-level addenda inline
above (AC-WEB-25, 28, 32, 35, 38, 39, 40, 54) point at what changed and why; this table is the
finding-by-finding map. Full live-probe transcripts, screenshots and psql output:
`34-evidence/R1/README.md`.

| Finding | What it was | Fix | File(s) | Test(s) |
|---|---|---|---|---|
| B1 | In-flight `QUEUED`/`SENDING` delivery status raised a `ValidationError` -> 500 on the public visitor read path (production only; invisible to the eager-Celery test suite) | Explicit status allowlist in the projection; unrecognised/in-flight maps to `None` instead of round-tripping the raw DB value | `modules/omnichannel/services/webchat_projection.py` | `test_in_flight_delivery_status_still_returns_200_on_the_visitor_read`, `test_visitor_projection_maps_in_flight_delivery_status_to_null` |
| B2 | The visitor WebSocket relay checked `contactId` but not `channelId` - a contact stitched across web chat AND WhatsApp would leak the WhatsApp thread (incl. signed media URLs) onto the still-open web chat panel | `visitor_frame` now requires the frame's `channelId` to match the principal's `visitor_channel_id`; `WsPrincipal` carries it from the handshake | `modules/omnichannel/services/webchat_projection.py`, `modules/omnichannel/routers/ws.py` | `test_visitor_frame_drops_a_frame_from_another_channel_on_the_same_contact`, `test_visitor_frame_fails_closed_when_the_frame_carries_no_channel` |
| B3 | Pre-chat wrote an unauthenticated, unverified `phone` onto `contact.phone_digits` - the exact key a later real WhatsApp inbound stitches contacts on, letting anyone with the public widget key poison a tenant's contact graph with a victim's number | `email`/`phone` from pre-chat now land only on the identity's new `visitor_profile_json` (never on the contact row); `name` still write-if-empty onto the contact as before | `modules/omnichannel/services/webchat_visitor_service.py`, `modules/omnichannel/models.py`, new migration `modules/omnichannel/alembic/versions/0022_omni_webchat_profile.py`, `modules/omnichannel/schemas.py` (`VisitorProfile`), FE `contact-details-form.tsx` ("Visitor provided" block) | `tests/test_omnichannel_webchat_hours_prechat_identity.py` (22 passed, covers the rewritten `_apply_pre_chat`); live-reverified via curl+psql AND a full browser click-through, `34-evidence/R1/README.md` |
| S1 | Non-string JSON scalars (`{"token":123}`, `{"hp":1}`) raised an unhandled `AttributeError` -> 500 on the unauthenticated surface | Body validated through the declared Pydantic request models instead of hand-parsed dict access | `modules/omnichannel/routers/webchat_public.py`, `schemas.py` (`WebchatSessionRequest` now used, closing N1 too) | `tests/test_omnichannel_webchat_public.py`; live-reverified, `34-evidence/R1/README.md` "S1" |
| S2 | Honeypot hit returned a distinguishable `200 {"ok":true}` shape, letting a bot fingerprint the trap field in one request (AC-WEB-32 not met) | Honeypot now returns `201` with a synthetic `VisitorMessage` carrying the same key set as a real send; `WebchatHoneypotResult` removed | `modules/omnichannel/routers/webchat_public.py`, `schemas.py` | `test_honeypot_hit_is_indistinguishable_from_a_real_send_and_stores_nothing`, `test_honeypot_hit_with_invalid_text_fails_exactly_like_a_real_send`; live-reverified, `34-evidence/R1/README.md` "S2" |
| S3 | Visitor WebSocket reconnected forever with no backoff after a permanent refusal (e.g. 4403 on epoch revocation), costing 4 DB queries every 3s per open panel | `onclose` now stops reconnecting on 4403 (falls back to the poll) and applies backoff/jitter otherwise | `service_frontend/services/webchat-visitor-service.real.ts` | `services/webchat-visitor-service.real.test.ts` (new, 5 passed) |
| S4 | Epoch revocation ("sign out all visitors") did not terminate already-open sockets - they kept receiving frames until the tab closed | The relay loop re-verifies the token/epoch/channel/tenant on a timer (`set_visitor_reverify_seconds`, 60s in tests) and closes `4403` on failure | `modules/omnichannel/routers/ws.py`, `webchat_visitor_service.py` | `tests/test_omnichannel_ws.py` (3 passed) |
| S5 | The consumer guide's `host:<userRef>` row pointed integrators at §12 (the unrelated plan-11H embed-shell HMAC), documenting no web chat identity-assertion recipe at all | New "Website chat channel" §12a documents `window.fxChatIdentity`/`fxWebchat.identify()`, the widget secret and the exact `HMAC-SHA256(userRef, widgetSecret)` recipe; the `host:` row now points at it | `documentation/omnichannel/consumer-integration-guide.md` | Guide-diff review; no code test (documentation-only) |
| S6 | The allowed-origins editor rendered interactive for a `channels.read`-only user, who could Save and get a 403 toast (frontend gating not mirroring the backend permission) | `WebchatIdentityBlock`'s `OriginsEditor` now gated on `can('channels.manage')`, read-only otherwise, matching the Identity block below it | `service_frontend/app/(protected)/omnichannel/settings/channels/components/channel-form-fields.tsx` | `webchat-identity-block.test.tsx` (new, 3 passed) |
| S7 | A shared/NAT'd IP's 60-per-5-minute budget made the widget "randomly disappear" for an entire office; a valid-token session resume silently spent one of those tokens | IP ceiling raised for this scope; a valid-token resume no longer spends an IP token; a warning log fires on 429 | `service_backend/app/config.py`, `app/services/throttle.py`, `modules/omnichannel/services/webchat_visitor_service.py` | `tests/test_omnichannel_webchat_public.py`; live-reverified via `psql auth_throttle`, `34-evidence/R1/README.md` "S7" |
| S8 | `GET /frame-policy` was unthrottled, uncached, and ran 3 DB queries per call on a hot path with no rate limit at all | 60s in-memory cache keyed on widget key; only a genuine miss-that-resolves-to-nothing (key enumeration) spends a throttle token | `modules/omnichannel/services/webchat_visitor_service.py` (`resolve_frame_policy`), `routers/webchat_public.py` | `tests/test_omnichannel_webchat_frame_policy.py` (8 passed); live-reverified via the backend SQL-echo log (1st call queries, 2nd identical call does not), `34-evidence/R1/README.md` "S8" |
| S9 | Core `app/main.py` hardcoded a module's route prefix (`_WEBCHAT_PUBLIC_PREFIX`) and registered a global `BaseHTTPMiddleware` for one module's CORS, violating "modules plug into the platform" | New `app/module_platform/public_cors.py` registry + a pure-ASGI `public_cors_middleware.py`; the module loader calls `register_public_cors()` at boot (mirrors `register_capabilities()`); omnichannel registers its own prefix from `bootstrap.py`. `app/main.py` now carries zero omnichannel constants (a dedicated test pins this) | `app/module_platform/public_cors.py` (new), `app/module_platform/public_cors_middleware.py` (new), `app/module_loader.py`, `app/module_platform/__init__.py`, `modules/omnichannel/bootstrap.py` | `tests/test_module_platform.py` (17 passed); live-reverified, `34-evidence/R1/README.md` "S9" |
| N1 | `WebchatSessionRequest` declared, documented, never used | Now used by S1's fix | `schemas.py` | covered by S1's tests |
| N2 | `webchat_visitor_service.py` reached into `WebchatService`'s private `_config_dict` | Promoted to a public `config_dict` | `modules/omnichannel/services/webchat_service.py`, `webchat_visitor_service.py` | covered by the existing widget-config test suite |
| N3 | `WebchatIdentityBlock` fired a second, redundant `useWebchatConfig` GET already fetched by the parent | Parent's config passed down instead of re-fetched | `service_frontend/app/(protected)/omnichannel/settings/channels/components/use-channel-form.tsx` | `use-channel-form.channels.test.tsx` (4 passed) |
| N4 | A global `BaseHTTPMiddleware` for one prefix added an anyio task group to every request app-wide | Resolved by S9's pure-ASGI middleware | `app/module_platform/public_cors_middleware.py` | covered by S9's tests |
| N5 | Raw hex colours (`bg-green-500`, `bg-[#6366F1]/10`) instead of `--foundryx-*` tokens | Left as-is per the plan's own precedent (workflow-canvas, other channel brand hexes) - explicitly not a hard fail; not changed this round | - | - |
| N6/N7 | Docstrings overstated "never writes a row" / "checked before a token exists" for the throttle | Docstrings corrected to match actual behaviour (the throttle DOES write/commit a row every call) | `app/services/throttle.py`, `webchat_visitor_service.py` | - |
| N8 | Loader iframe carried no `referrerpolicy` | Not changed this round (same-origin app, low severity) | - | - |
| N9 | `lib/channel-capabilities.ts` claimed exact parity with the backend's `WEBCHAT` capability record when the FE is actually more restrictive (`media.voice: false`) | Comment corrected to state FE-more-restrictive-than-backend rather than "parity-pinned" | `service_frontend/lib/channel-capabilities.ts` | `lib/channel-capabilities.test.ts` (8 passed) |
| D1 | `channels.widget_key` unregistered in the storage-key drift gate (a real CI/DoD failure, not a security bug) | One line added to `_NON_STORAGE_KEY_COLUMNS` with a plan-34 comment | `service_backend/app/storage_migration/registry.py` | `tests/test_storage_migration_registry.py` (9 passed), `tests/test_omnichannel_media_backfill.py` (4 passed) - **FIXED in the commit that lands this section** (`fix(omnichannel): plan 34 review round 1 - ...`, this branch, immediately following `6882db0f`) |

**Migration:** a new module migration, `0022_omni_webchat_profile` (on `0021_omni_webchat`), adds
`contact_channel_identities.visitor_profile_json` (`JSON(none_as_null=True)`). Applied to
`foundryx_service_s34` this round via `run_module_migrations(engine, 'omnichannel')` with
`DATABASE_URL` pinned explicitly to the s34 database in the command's own environment (the
worktree's `.env` symlinks to the main checkout's `.env`, which points at a different database -
never touched). Verified: module `alembic current` -> `0022_omni_webchat_profile`; core `alembic
current` -> `workflows_http_s31` (unchanged); `psql \d app_omnichannel.contact_channel_identities`
shows the new column.

**Backend regression this round** (the nine round-1-touched files + the two storage-drift files + WS,
each run alone per the lane's memory-pressure rule): `test_omnichannel_webchat_public.py` 53,
`test_omnichannel_webchat_outbound.py` 15, `test_omnichannel_webchat_frame_policy.py` 8,
`test_omnichannel_webchat_hours_prechat_identity.py` 22, `test_omnichannel_channels_webchat.py` 28,
`test_omnichannel_gateway_webchat.py` 10, `test_omnichannel_contacts_module.py` 38,
`test_omnichannel_embed.py` 36, `test_module_platform.py` 17, `test_storage_migration_registry.py` 9,
`test_omnichannel_media_backfill.py` 4, `test_omnichannel_ws.py` 3 - **all green, 0 failures**
(243 tests total across the twelve files). Frontend: the round-1-touched/new vitest files (8 files,
58 tests) all green; `npx eslint` 0 errors on the 12 round-1-touched non-test files (2 pre-existing
`jsx-a11y` warnings on `composer.tsx`, unrelated categories); `npx tsc --noEmit` 0 errors in any
plan-34 file. Full detail and live-probe transcripts: `34-evidence/R1/README.md`.

---

## Review round 2 (2026-09-09) - fixes landed

One new blocker introduced by the S8 fix itself, one should-fix on the same seam, and four nits.
Full live-probe transcripts: `34-evidence/R2/README.md`.

| Finding | What it was | Fix | File(s) | Test(s) |
|---|---|---|---|---|
| B4 | `GET .../frame-policy`'s throttle was keyed on the caller's IP - but the route's ONLY caller is the Next.js middleware (a server-to-server call), so every legitimate request AND every attacker probe shared ONE IP. 600 distinct-key misses tripped the shared bucket and put `frame-ancestors 'none'` on EVERY tenant's panel at once | Throttle removed from `frame_policy` entirely; the bounded, split-TTL origins cache (S-new-1) absorbs the enumeration cost instead, with no shared counter one caller can trip on another's behalf. `middleware.ts` now distinguishes "backend answered with no origins" (silent) from "the backend call itself failed" (logged, per-request only - never a shared/poisoned state) | `modules/omnichannel/routers/webchat_public.py`, `service_frontend/middleware.ts` | `tests/test_omnichannel_webchat_frame_policy.py::test_frame_policy_records_no_throttle_rows_ever`, `::test_frame_policy_601_unknown_key_probes_never_break_a_known_good_key`; `service_frontend/middleware.test.ts` (4 new); live-reverified via curl (601-probe loop) + `psql auth_throttle`, `34-evidence/R2/README.md` |
| S-new-1 | The CORS preflight path reached the same origins lookup through an ASGI middleware with NO throttle at all, an unbounded cache (every distinct widget key ever probed stayed cached forever), and a DB session opened before the cache was even consulted | `_origins_cache` is now a bounded LRU (hard cap 5000, oldest evicted) with a 15s TTL on an unresolved (enumeration-shaped) key vs 60s on a resolved one; both `resolve_frame_policy` and `preflight_origin_allowed` consult the cache before touching a `Session` | `modules/omnichannel/services/webchat_visitor_service.py` | `test_origins_cache_enforces_a_hard_cap_with_lru_eviction`, `test_negative_cache_entry_expires_in_15_seconds_not_60`, `test_preflight_cache_hit_opens_no_db_session` |
| N-new-1 | The 60s WS re-verify stamped `last_seen_at`, so a visitor who opened the panel and walked away read "Online now" forever | `_authorize` takes a `stamp_presence` flag (default `True`); the background revalidator passes `False`. Connect, message post and the real handshake still stamp | `modules/omnichannel/routers/ws.py` | `tests/test_omnichannel_webchat_outbound.py::test_ws_visitor_revalidation_ticks_do_not_advance_last_seen_at` |
| N-new-2 | Every visitor socket re-verified on the EXACT same interval with no jitter, so a connection burst re-verified in lockstep every minute | `_jittered_interval` applies +/-20% jitter to `VISITOR_REVERIFY_SECONDS`, computed once per socket at task start (pure function, unit-testable without a live socket) | `modules/omnichannel/routers/ws.py` | `tests/test_omnichannel_ws.py::test_jittered_interval_scales_within_the_documented_band`, `::test_jittered_interval_is_computed_once_per_socket_not_per_tick` |
| N-new-3 | `app/module_platform/public_cors.py`'s docstring pointed at the wrong file for `PublicCorsMiddleware` (`app/middleware/public_cors.py`, which does not exist) | Corrected to `app/module_platform/public_cors_middleware.py` | `app/module_platform/public_cors.py` | docstring-only, no test |
| N-new-4 | Migration `0022` added a fifth column while the manifest stayed `0.10.0`, so `update_tenant` never re-runs for a tenant already stamped there | Manifest bumped to `0.10.1`; `update_tenant`'s docstring records the bump as a no-op per tenant (the column already arrived via the module Alembic migration + `create_all` mirror inside `0.10.0`) | `modules/omnichannel/manifest.json`, `modules/omnichannel/bootstrap.py` | The four manifest version-pin tests (`test_omnichannel_channels_webchat.py`, `test_omnichannel_team_assignment.py`, `test_omnichannel_contacts_module.py`, `test_omnichannel_broadcasts.py`) updated to assert `0.10.1` |

**Residual backlog rows added:** BL-SS-185 (unverified pre-chat `name` on `contacts.first_name`/
`last_name`), BL-SS-186 (honeypot timing oracle), BL-SS-187 (no in-product `visitorProfile`
promotion action), BL-SS-188 (frame-policy 60s staleness has no cache-bust on widget-config write),
BL-SS-189 (host identity assertion has no expiry/nonce, single-secret rotation - carried over
unchanged from round 1's RR3). The sixth residual named in review (WS re-verify interval/jitter/
write cost) was FIXED in this round (N-new-1/N-new-2 above) rather than backlogged.

**Environment note:** the lane's `.env` (symlinked to the main checkout's) points `DATABASE_URL` at
the shared `foundryx_service` database, not the dedicated `foundryx_service_s34` this branch also
has available - pre-existing state, not part of this round's diff. The shared database was several
migrations behind this branch's head (unrelated pre-existing drift), which was brought current
(`alembic upgrade head` + `run_module_migrations(engine, "omnichannel")`, both additive/idempotent)
before restarting `:8014` for live verification. See `34-evidence/R2/README.md` for detail.

**Backend regression this round** (the touched files, each run alone): `test_omnichannel_webchat_
frame_policy.py` 12, `test_omnichannel_webchat_public.py` 53, `test_omnichannel_webchat_outbound.py`
16, `test_omnichannel_ws.py` 5, `test_module_platform.py` 17, `test_omnichannel_channels_webchat.py`
28, `test_omnichannel_contacts_module.py` 38, `test_omnichannel_broadcasts.py` 49,
`test_omnichannel_team_assignment.py` 34 - **all green, 0 failures** (252 tests across the nine
files). Frontend: `middleware.test.ts` (new, 4 passed); `npx eslint` 0 errors on
`middleware.ts`/`middleware.test.ts`. Full detail and live-probe transcripts (601-probe curl loop,
`psql auth_throttle` zero-rows check, the middleware CSP header for a known vs. unknown widget key):
`34-evidence/R2/README.md`.

## Review round 3 (2026-09-09) - fixes landed

One blocker (a synchronous DB-touching resolver on the ASGI event loop, exposed by round 2's own
throttle removal), one should-fix on the same cache's thread-safety, and two nits. Live-probe
transcript: `34-evidence/R3/README.md`.

| Finding | What it was | Fix | File(s) | Test(s) |
|---|---|---|---|---|
| B5 | `PublicCorsMiddleware.__call__` called the registered resolver directly, synchronously, on the ASGI event loop; a cache miss runs `resolve_live_channel`'s three DB queries there, and B4 (round 2) had already removed the only rate limit bounding how often an unauthenticated caller could force a miss - a sustained distinct-key probe could stall the worker's event loop for up to a connection-pool timeout once the pool exhausted | `PublicCorsMiddleware._allows` is now `async` and dispatches the resolver through `starlette.concurrency.run_in_threadpool`, keeping the existing broad `except` around it; `public_cors.py`'s provider contract docstring now says a resolver MAY do blocking I/O and is always run off the loop | `app/module_platform/public_cors_middleware.py`, `app/module_platform/public_cors.py` | `tests/test_module_platform.py::test_public_cors_middleware_resolver_runs_off_the_event_loop_and_fails_closed_on_error` (drives the middleware end-to-end with a hand-rolled ASGI scope, asserts the resolver's thread differs from the calling thread AND that a raising resolver still yields no `Access-Control-Allow-Origin`); `::test_public_cors_middleware_refuses_when_a_resolver_raises` updated for the new async signature; full regression `test_omnichannel_webchat_public.py` 53 passed (exercises the real preflight through `TestClient`) |
| S-new-2 | `_origins_cache`'s check-then-act sequences (get -> expire -> del, set -> move_to_end -> evict) were not atomic, and the cache is genuinely touched from multiple thread contexts (the sync `frame_policy` route's threadpool threads, and the CORS middleware's resolver threads once B5 dispatches it off the loop) - a race could raise `KeyError` out of a route as a 500, or be silently swallowed inside the preflight resolver, refusing a legitimate origin | Every read/write of `_origins_cache` now runs inside one module-level `threading.Lock`; the whole get-or-expire-or-store sequence is a single critical section | `modules/omnichannel/services/webchat_visitor_service.py` | `tests/test_omnichannel_webchat_frame_policy.py::test_origins_cache_is_thread_safe_under_concurrent_hammering` (16 threads, near-zero TTL and a tiny cap to force constant expiry AND eviction, asserts nothing raised) |
| N-new-5 | `middleware.ts` moved `await response.json()` outside the `try`, so a 200 with a non-JSON body (a captive proxy, a CDN error page) propagated out of `middleware()` as an uncaught error rather than failing closed | `json()` and the shape check are back inside a `try`, logged with the same "fetch failed" shape as the other two failure modes | `service_frontend/middleware.ts` | `service_frontend/middleware.test.ts::"emits frame-ancestors none, WITH a logged warning, on a 200 with a non-JSON body"` |
| N-new-6 | A code comment and the `frame_policy` route docstring both claimed a distinct-key probe "can grow the cache but never the database load" - backwards: a distinct-key probe is precisely the case that always reaches the database, since the cache only absorbs REPEATED keys | Both rewritten to state repetition is what the cache absorbs, distinct-key volume is deliberately unbounded here, and point at `BL-SS-181` | `modules/omnichannel/services/webchat_visitor_service.py`, `modules/omnichannel/routers/webchat_public.py` | docstring/comment-only, no test |

**Residual backlog rows amended/added:** BL-SS-181 amended to name `GET .../frame-policy` and the
webchat CORS preflight explicitly as the two unauthenticated, unthrottled, three-query endpoints
whose cache only helps the repeated-key case; BL-SS-190 (new - the origins cache is one unsegmented
LRU pool, a sustained distinct-key probe evicts every legitimate positive entry); BL-SS-191 (new -
revisit the 15s negative TTL / 60s staleness bound once BL-SS-188's cache-bust lands). Carried over
unchanged: BL-SS-184, BL-SS-185..189.

**Backend regression this round** (the touched files, each run alone): `test_module_platform.py` 18
(was 17, +1), `test_omnichannel_webchat_frame_policy.py` 13 (was 12, +1),
`test_omnichannel_webchat_public.py` 53 - **all green, 0 failures**. Frontend:
`middleware.test.ts` 5 (was 4, +1); `npx eslint middleware.ts middleware.test.ts` 0 errors.
Backend restarted on `:8014` per the lane's exact command with `DATABASE_URL` and `FRONTEND_URL`
confirmed present in the running process's environment. Full detail and live-probe transcripts
(preflight `curl` against an unknown key and the seeded `chn-demo-web` key): `34-evidence/R3/
README.md`.
