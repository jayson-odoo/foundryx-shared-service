# Evidence: AC-10-50 operator pull-setup journey (re-verify at current HEAD)

Run date: 2026-09-20 (UTC), approx 12:40-13:20Z. HEAD `17dc2c619b42224d1211f9006d1c805aec498cd0`
(worktree `.claude/worktrees/s40`, branch `sprint-5/10-autocount-pull-review`). Lane: backend
`:8009` (uvicorn, no `--reload`), frontend `:3009` (`npx next start -p 3009` after `rm -rf .next &&
npm run build`), DB `foundryx_service_s40`. Tenant `default`, user `demo@example.com` (Admin).
Company `Sorento SRT S40` (`0e6f5c95-b099-4a1f-8de9-425b63f561b4`).

**Resume context:** a previous tester died mid-run on an API limit; its PARTIAL screenshots were
parked in commit `aea5e62c` (26 PNGs at 375px complete through snapshot detail, 1280px only
through the build dialog, no README). The backend changed materially since that commit: three
security-fix commits landed (`6c150e73`, `d818ea4f`, `02837e11`, `17dc2c61`) including, per their
own commit messages, a **non-blocking gateway build fix** (this run's Finding A below) and
connection-sizing fields (AC-10-85). Every step in this journey was RE-OBSERVED live at this HEAD
via real sidebar clicks - no parked screenshot was reused verbatim; every file listed below is a
fresh capture from this session (the old aea5e62c PNGs were left untouched in git history but are
superseded by this run).

## Journey (real clicks from the sidebar, both viewports)

1. **Entities list.** AutoCount -> Companies -> `Sorento SRT S40` -> Entities tab. Both Product
   and Stock balance already showed `Pull on request` in the Delivery column at the start of this
   session (an earlier tester's partial run had already flipped and activated them) - re-verified
   live, not assumed. `01-entities-list-375.png`, `16-entities-list-1280.png`. **PASS.**
2. **Schedule tab toggle (AC-10-16).** Product's Schedule tab in VIEW mode: read-only radios
   `Push`/`Pull on request`, `Pull on request` checked (`02-schedule-tab-readonly-375.png`,
   `17-schedule-tab-readonly-1280.png`). Clicked **Edit** -> the same radios become a live
   `group "Delivery"` -> clicked **Push** -> the Incremental (`Every 15 minutes`) and Reconcile
   (`Daily at 02:00`) cadence controls reappear with their PREVIOUSLY SAVED values, unchanged
   (`03-schedule-push-cadence-375.png`, `18-schedule-push-cadence-1280.png`) -> clicked
   **Pull on request** again -> cadence controls vanish immediately
   (`04-schedule-pull-hidden-375.png`, `19-schedule-pull-hidden-1280.png`). At 375px this round
   trip was SAVED (Push, confirmed via toast, then Pull, confirmed via toast) to prove persistence
   end to end; at 1280px the toggle was exercised then **Cancel**led (no net state change) since
   persistence was already proven at 375px. **PASS** both viewports.
3. **Review & Activate banner (AC-10-17).** Product is ALREADY `Active` from the earlier
   session, so its own Review & Activate tab shows the live-operation controls
   (`Re-run preview` / `Pause` / `Run now`), never the pre-activation banner - this is CORRECT
   per-spec behaviour (the banner is a pre-activation affordance only), captured as
   `05-review-activate-375.png` / `20-review-activate-1280.png` for completeness. To independently
   confirm the banner's exact COPY for Pull mode (AC-10-17: `"Activating lets the consumer request
   this extract."`), the SAME check was run against the Mocha company's `Stock balance` task,
   which is genuinely still `Draft` + `pull` this session: its Review & Activate tab shows exactly
   that sentence, a `Run preview` button and an `Activate` button, no toggle, no hint copy.
   `20b-review-activate-banner-1280.png` (1280px; the 375px banner text was confirmed via
   `get text` during the pull-stock/flip-push work and is not separately screenshotted here to
   avoid a redundant capture of the identical fixed string). **PASS**, drift noted: this HEAD's
   lane state made the entity-under-test already-active, so the banner was verified on a
   same-shape substitute entity rather than a fresh Draft-to-Active walk on Product itself; the
   copy, the field text and the CTA all match AC-10-17 exactly.
4. **Back to Entities - Delivery column.** `06-entities-delivery-column-375.png` (table clipped,
   Delivery column off-screen at 375px - a horizontal scroll is required, matching the shell's
   documented internal-scroll pattern for wide tables) + `06b-entities-delivery-column-scrolled-
   375.png` (scrolled into view: both rows read `Pull on request`) + `21-entities-delivery-column-
   1280.png` (visible after one internal scroll even at 1280px - the table has 9 columns).
   **PASS.**
5. **Pull -> Keys -> Issue key.** Sidebar AutoCount -> Pull. Real backend data confirmed live
   (the FE phase-2 mock-to-real swap, commit `994ca215`, is an ancestor of this HEAD - the Keys
   list showed genuine leftover rows from earlier sessions, not the old fixture). `07-pull-keys-
   list-375.png`, `22-pull-keys-list-1280.png`. **Issue key** dialog: Name (timestamped, e.g.
   `S6 pull-setup 20260920T124430Z`) + Companies `MultiSelect` -> **Select all** picked both
   `Sorento SRT S40` and `Mocha MCH S40 ...`. `08-issue-key-dialog-filled-375.png`,
   `23-issue-key-dialog-filled-1280.png`. Submitting switched the dialog to "Key issued": the
   plaintext key rendered ONCE with a Copy button and the warning "Copy this key now - it will not
   be shown again." `09-key-issued-plaintext-375.png`, `24-key-issued-plaintext-1280.png`. Closing
   via **Done** confirmed the plaintext is gone from `document.body.innerText` afterward (checked
   both times via `eval`). **PASS**, both viewports.
6. **Snapshots segment -> Build.** Switched the `View segment` `SearchSelect` Keys -> Snapshots.
   `10-snapshots-segment-375.png`, `25-snapshots-segment-1280.png`. **Build snapshot** dialog:
   Company + Entity `SearchSelect`s, both searchable. `11-build-dialog-filled-375.png` (Product),
   `26-build-dialog-filled-1280.png` (Product). Clicking **Build** disabled the dialog's own
   buttons while the request was in flight (this lane runs `CELERY_TASK_ALWAYS_EAGER=true`, so the
   whole paged extraction runs SYNCHRONOUSLY inside the operator route's own request - the browser
   tab that clicked Build stays on a spinner-disabled dialog for the full build duration; a
   SEPARATE tab/session polling the Snapshots list sees the row go `building` mid-flight, since the
   `add_building_row` insert is committed to the DB by the job's own first heartbeat, well before
   the whole request resolves). Captured the transient `building` row from a second browser tab:
   `12-snapshot-building-375.png`, `27-snapshot-building-1280.png`. Once the original tab's request
   resolved it auto-navigated straight to the finished snapshot's detail page: `13-snapshot-ready-
   375.png` was captured from the Snapshots list re-poll (Ready, 11,840 records); `29-snapshot-
   ready-1280.png` is the detail page itself, Ready badge, 11,840 records, `Complete: Yes`, content
   hash `2d1b3832afc0de42f4cddc5edc2c6f70e26c66ee62c6539358c9197946f1a984` - IDENTICAL to the S6
   live-replay evidence's own recorded hash for the same entity/company, confirming the build is
   still deterministic at this HEAD. Detail header + first page of rows: `14-snapshot-detail-
   header-375.png`, `15-snapshot-detail-rows-375.png`, `30-snapshot-detail-rows-1280.png`
   (`zeroListPriceCount 5129`, `negativeListPriceCount(clamped) 121`, `enrichMissCount 0` - exact
   match to the plan's own AC-10-53 figures). **PASS**, both viewports.

## Build durations (actual, this run - all via the eager, in-request-synchronous path)

| Build | Route | Started (UTC) | Finished (UTC) | Duration | Records |
|---|---|---|---|---|---|
| Product, SRT (375 run) | Operator | 12:45:49 | 12:50:40 | 4m 51s | 11,840 |
| Stock balance, SRT (375 run) | Operator | 12:54:37 | 13:00:19 | 5m 42s | 12,133 |
| Product, SRT (gateway, triggered by the grace-window probe, see Finding B) | Public gateway | 12:57:46 | 13:03:15 | 5m 29s | 11,840 |
| Product, SRT (1280 run) | Operator | 13:11:42 | 13:17:15 | 5m 33s | 11,840 |

All four builds against `db1` (`AED_SORENTO`) via the live `https://hapi.sorento.cc.cd/api/db1`
wrapper completed in 5-6 minutes this session - faster than the S6 live-replay evidence's own
9-minute baseline (likely wrapper-load variance; every OTHER number - record counts, zero/negative
counts, content hash - is byte-identical across all four runs, confirming the extraction itself is
unaffected).

## Finding A - the gateway build event-loop-block (S6 live-replay Finding 2) IS NOW FIXED

The S6 live-replay evidence (`10-evidence/live-replay/README.md`) recorded a severe defect: the
public gateway's `POST /api/v1/autocount/snapshots` was declared `async def`, so FastAPI ran its
fully-synchronous, minutes-long extraction directly on the ASGI event loop, freezing EVERY route
(including unauthenticated `/openapi.json`) for the whole build duration. This run reproduces the
SAME call pattern against the CURRENT HEAD and finds it fixed:

- `modules/autocount/routers/pull_v1.py`'s `build_snapshot` is now a **plain `def`** (confirmed by
  reading the router source - its own docstring cites "Sprint-5/10 S6 (live-replay Finding 2)" and
  explains the fix: a plain `def` route gets Starlette's automatic threadpool, exactly like the
  operator route `routers/pull.py` always did).
- Live proof: while a gateway-triggered product build was `building` (confirmed via direct DB
  read, `status='building'`), `curl -m 5 http://localhost:8009/openapi.json` returned `200` in
  **5-29 milliseconds** on every one of six separate probes across two different in-flight gateway
  builds (one triggered incidentally by the grace-window test in Finding B, one the deliberate
  1280px Build-dialog run). The old defect's own reproduction (`curl --max-time 10/15` timing out
  repeatedly) does NOT reproduce here.
- Also confirmed indirectly: normal UI navigation (Companies list, Entities tab, Settings ->
  Integrations, Keys revoke actions) all succeeded normally in separate tabs WHILE a build was in
  flight in another tab, both at 375px and 1280px.

**Verdict: Finding A (formerly live-replay Finding 2) is FIXED at this HEAD.** No new defect filed;
recommend the plan owner close the backlog item this finding would have produced.

## Finding B - a revoked key still works during the 9-second grace/undo window (owner question, answered)

Investigated while doing the Keys Run 4 revoke (full detail in `pull-keys-snapshots/README.md`
Run 4 section): clicking **Revoke** on a key's row starts a deferred-action countdown
("Revoking in 9s / Cancel") BEFORE the actual backend mutation commits. A `curl` gateway build
request using that key, issued during the countdown, returned `202 {"snapshotId":...,
"status":"ready",...}` - the key was still valid. Cross-checking the DB: the key's own
`revoked_at` timestamp landed **~0.8 seconds AFTER** the snapshot row's `created_at` (i.e. after
the gateway had already accepted the request). **Answer: yes, a key still works for the duration
of the grace/undo window** - the actual revoke does not take effect until the countdown completes
(or would have been rolled back entirely by Cancel). This is consistent with the deferred-action
engine's documented design (commit fires after the countdown, not before) and is not itself a
defect, but it is worth the plan owner explicitly deciding whether a security-sensitive action like
API-key revocation should commit IMMEDIATELY (with the grace window only controlling whether an
already-fired mutation can still be undone) rather than DEFERRING the mutation itself - flagged for
a design decision, not filed as a bug.

## Finding C - AC-10-85 connection sizing fields are present but render blank, no default placeholder (bonus check, 1280 only)

Settings -> Integrations -> `S40 db1 SRT ...` (the open, no-auth AutoCount connection) -> Edit:
`Page size` and `Request timeout (seconds)` fields ARE present, gated correctly (only shown for
`auth: none`, per the `showWhen` mechanism AC-10-85 specifies), confirmed via
`document.querySelectorAll('input[type=number]')` -> `config.pageSize` / `config.requestTimeoutSeconds`.
Screenshot `28-connection-sizing-fields-1280.png`. Both fields render EMPTY with no placeholder
text hinting the documented fallback defaults (1000 / 90) - an operator opening this form sees two
blank number inputs with no clue what value is actually in effect until they read the docs or type
something. This is a minor foolproof-UI gap (AC-10-85's own defaults ARE applied server-side when
the field is unset, so functionally nothing is broken), reported for the coder; not fixed here (no
changes saved to this connection - Cancel was clicked). **PASS on presence/gating, minor UX
finding on missing default placeholder.**

## Responsive

Both widths confirmed no page-level horizontal scroll beyond the documented internal-scroll
patterns (wide `DataGrid` tables scroll internally, e.g. the Entities list's Delivery column and
the Pull page's Keys/Snapshots tables); dialogs and toasts render correctly at both sizes.

## House rules

- No hint/instructional copy anywhere on this journey. **PASS.**
- Every dropdown (Company, Entity, Companies multi-pick, View segment) is a searchable
  `SearchSelect`/`MultiSelect`. **PASS.**
- Console: only the pre-existing benign `DialogContent` missing-`aria-describedby` warning across
  every journey step; no page errors. **PASS.**
- No "Foundryx" branding visible to the tenant; no em/en dashes anywhere. **PASS.**

## AC verdicts (this run)

- **AC-10-50 [E2E]** PASS at both 375px and 1280px. Full operator journey (Companies -> Product ->
  Schedule toggle -> Review & Activate -> Entities Delivery column -> Pull -> Keys -> Issue key ->
  Snapshots -> Build -> building -> ready -> detail) reproduced with real clicks, real data, at the
  current HEAD.
- **AC-10-16 [FE]** PASS. Two-segment toggle, cadence show/hide, persistence round-trip, all
  confirmed live both viewports.
- **AC-10-17 [FE]** PASS. Banner copy confirmed exact match on a substitute Draft+Pull entity
  (Product itself was already Active this session); Delivery column badges confirmed both
  viewports.
- **AC-10-88 [BE]** PASS (re-attach) - see `pull-keys-snapshots/README.md` for the dedicated
  cooldown/re-attach transcript this run did not re-duplicate; every build this run started a
  genuinely NEW extraction (cooldown had elapsed each time), consistent with re-attach-while-alive
  behaving correctly (no double-build was ever observed for a still-building triple).
- **AC-10-85 [BE]/[FE]** PASS on presence + gating; Finding C (blank fields, no default
  placeholder) noted as a minor UX gap, not a hard fail.
- New finding (this run) - the S6 live-replay's severe gateway-blocking defect (Finding 2 there,
  Finding A here) is CONFIRMED FIXED. Recommend closing its backlog entry.
- New finding (this run) - Finding B answers the "does a key work during the revoke grace window"
  question definitively: yes, flagged as a design decision for the plan owner.

## Teardown state left by this evidence run

- Company `Sorento SRT S40`: `product` delivery mode `pull`/`active` (unchanged net of this run's
  toggling, which always ended back on Pull with a Save); `stock_balance` delivery mode
  `pull`/`active` (untouched by this file's journey).
- Every pull API key issued during this run (`S6 pull-setup 20260920T124430Z`, `AC-10-50 pull-
  setup 1280 20260920T131041Z`) is revoked - see `pull-keys-snapshots/README.md` Run 4.
- Four new `ready` snapshots exist (see the duration table above) - harmless, expiring on their own
  24h TTL, not cleaned up (evidence-only tester, no DB writes beyond normal app usage).
