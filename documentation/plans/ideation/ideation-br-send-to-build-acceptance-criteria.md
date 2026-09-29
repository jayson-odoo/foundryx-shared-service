# Ideation - BR "Send to build" -> GitHub crew-intake issue + crew progress write-back (UAC)

Lane BR-TO-CREW (crew), branch `crew/br-send-to-build`. Owner approval of the concept: 29 Sep 2026 23:10. Owner decisions 29 Sep (later the same night): GitHub auth = fine-grained PAT as a core Connection (provider `github`); Send gate = button disabled with the missing-field reason, same validator as Promote, new `send_to_build` permission; write-back = one tenant-scoped ideation build key (`fxb_live_`, hashed, Keys dialog), append-only Trace plus the merged/released status move.
Plan: `PLAN-ideation-br-send-to-build.md` (same folder). Mockup: `documentation/mockups/br-send-to-build/index.html`.

Legend: `[FE]` frontend · `[BE]` backend · `[T]` unit/service test · `[E2E]` one recorded agent-browser run
(real clicks, 375px AND 1280px). Every AC is independently verifiable Given/When/Then. The test report is
keyed to these ids. Status keys below are the SEEDED platform keys; the UI never branches on a label.

## A. Product -> repository mapping

### AC-STB-01 [BE][T] Build repository on the product's delivery config
- **Given** a software product, **when** a Maintainer (`ideation.products.manage`) PUTs
  `/ideation/products/{id}/delivery` with `buildRepo: "jayson-odoo/sorento-crm"`,
- **Then** the row persists it and `GET` returns `buildRepo`; a value that is not `owner/repo`
  (`^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`) is refused 422 with a plain message; `buildRepo: null` clears it.
- **And** the existing `productDomainBase` round trip is unchanged.

### AC-STB-02 [FE] Product dialog field
- **Given** the product form dialog for a software product, **then** the Delivery section shows a
  "Build repository" text field next to "Product domain base"; save writes both through the same
  delivery PUT; a 422 shows inline on the field. No help copy on screen.

### AC-STB-03 [BE][T] Tenant scoping
- **Given** product P of tenant A, **when** tenant B's Maintainer PUTs P's delivery,
- **Then** 404 (never 403, never a leak of A's values).

## B. GitHub connection

### AC-STB-04 [BE][T] GitHub provider in the connections registry
- **Given** the ideation module is loaded, **then** `GET /integrations/providers` lists provider
  `github` (type `scm`, one password field `token`, no test target).
- **When** an Admin saves a connection with a token, **then** `credentials_json` is Fernet-encrypted and
  the token is never echoed by any read endpoint.

### AC-STB-05 [BE][T] Test names the failing step
- **Given** a saved GitHub connection, **when** Test runs, **then** it calls `GET /user` (authenticated,
  writes nothing): 200 -> `ACTIVE` with the login in the message; 401 -> `ERROR` "GitHub rejected the
  token"; transport error -> `ERROR` "GitHub is unreachable" (never a raw traceback, never the token).

## C. Send to build

### AC-STB-06 [BE][T] Readiness is server-computed on the BR detail
- **Given** `GET /ideation/business-requirements/{id}`, **then** the detail carries
  `build: { canSend, blockers[], issueUrl, issueNumber, repo, sentAt, sentBy, stage, status }`.
- `canSend` is true only when ALL hold: the BR is not test-excluded from the lane, its answers pass
  the stamped template's required-field validation (the SAME validator Promote uses), the product has a
  `buildRepo`, the tenant has an ACTIVE `github` connection, and no build row exists yet.
- `blockers[]` lists the human reasons in that order, e.g. `"Missing: Success metric, Constraints"`,
  `"Set the build repository on the product Sorento CRM"`, `"Connect GitHub in Settings > Integrations"`.

### AC-STB-07 [FE] Header button states (mockup section 1)
- **Given** the BR page, **then** "Send to build" is THE primary call-to-action in the record-actions
  row, rendered as a split button (primary main segment + attached chevron segment); the chevron opens a
  menu whose first item is Edit (owner ruling 30 Sep). A user without
  `ideation.business_requirements.send_to_build` sees the plain Edit primary as today.
- **When** `canSend` is false and no issue exists, **then** the main segment is disabled, the chevron
  segment stays enabled (Edit reachable), and ONE muted reason line renders under the actions row with
  `blockers[0]` (a product blocker links to the product).
- **When** an issue exists, **then** the main segment is the issue-link chip "<repo short name> #<n>"
  (opens the issue in a new tab) with the same chevron menu, plus the line
  "Sent <date time in the user's tz> by <name>". A gear menu keeps the status moves and Delete.

### AC-STB-08 [FE] Confirm dialog (mockup section 2)
- **When** the enabled button is clicked, **then** a confirm dialog shows the repository, the linked
  idea count and "<n> of <m> fields complete"; Cancel closes; "Send to build" fires ONE request.
  The button shows a pending state until the response and never fires twice.

### AC-STB-09 [BE][T] Send creates exactly one issue and moves the status
- **Given** a sendable BR, **when** `POST /ideation/business-requirements/{id}/send-to-build`
  (permission `send_to_build`),
- **Then** (1) a `br_builds` row is inserted first (unique per BR), (2) the GitHub issue is created in
  the product's repo with label `crew-intake`, title = BR title, body per AC-STB-10, (3) the row stores
  `issue_number`, `issue_url`, `issue_node_id`, (4) the BR moves to `sent_to_build` through
  `status_machine.transition` on the edge `br-tr-send-to-build`, (5) a Trace entry `sent` is written
  with the actor, (6) the response is the refreshed detail.
- **And** the label is ensured (`GET /repos/{r}/labels/crew-intake`, 404 -> create, colour `#ff5a00`).

### AC-STB-10 [BE][T] Issue body is the BR snapshot, template-driven
- **Given** the stamped template doc, **then** the body renders, in document order, one `## <field label>`
  section per input field with the answer (empty answer -> "(not provided)"); NO hardcoded field keys.
- **Then** it appends `## Linked ideas` (each `- <ideaNumber> <title or problem> (+<up> / -<down>)`),
  `## Grill transcript` (each turn `**<role>:** <content>`; omitted when the grill has no messages),
  `## Links` with the BR URL `<frontend_url>/ideation/business-requirements/<id>`, and ends with the
  machine markers `<!-- br-id: <id> -->` and `<!-- br-product: <productId> -->`.
- **And** the body has no em/en dashes and is under GitHub's 65536-char limit (truncate the transcript
  first, with a "(transcript truncated)" line).

### AC-STB-11 [BE][T] Idempotent, including after a crash between create and store
- **Given** a BR already sent, **when** send is POSTed again, **then** 200 with the existing issue in the
  detail and NO GitHub call.
- **Given** a `br_builds` row in state `creating` with no issue yet (a prior request died), **when** send
  is POSTed, **then** the server first searches the repo for the marker (`search/issues` with
  `"br-id: <id>" in:body repo:<r>`) and adopts a hit instead of creating a second issue.
- **Given** two concurrent sends, **then** exactly one issue exists (the unique index makes the loser
  409 -> the client reloads and sees the link).

### AC-STB-12 [BE][T] Refusals are precise
- Not sendable -> 422 `{ message, blockers[] }` naming the first blocker; missing permission -> 403;
  GitHub 401/403 -> 502 "GitHub rejected the token" and the BR status is unchanged and the build row is
  removed; GitHub 404 -> 502 "Repository <r> not found or the token cannot see it"; unreachable -> 502.
  The status move happens AFTER the issue exists and in the same transaction as the row update.

### AC-STB-13 [BE][T] New status + edges seeded for every tenant
- **Given** bootstrap, **then** the platform BR graph has status `sent_to_build` (label "Sent to build",
  colour `violet`, sort 4, before `in_fr`) and edges `br-tr-send-to-build` (draft/grilling/ready ->
  sent_to_build), `br-tr-build-delivered` (sent_to_build -> delivered), `br-tr-build-back`
  (sent_to_build -> ready, label "Back to ready"). Existing DBs converge at the next bootstrap
  (insert-if-missing seed); no data backfill is needed because no row can hold the new status yet.
- **And** the generic status actions menu does NOT offer `br-tr-send-to-build` (it is fired only by the
  Send endpoint) but DOES offer "Back to ready" on a sent BR (permission `send_to_build`).

### AC-STB-14 [BE][T] Permission + grant sweep
- **Given** the ideation permissions CSV, **then** `ideation.business_requirements.send_to_build`
  exists (label "Send to build"), and the grant sweep gives it to every role that already holds
  `ideation.business_requirements.promote` in every provisioned tenant.

## D. Write-back API (crew -> Trace)

### AC-STB-15 [BE][T] Build write-back keys (ideation-owned)
- **Given** an Admin (`ideation.business_requirements.send_to_build`), **when** they mint a key from the
  Keys dialog on the Business requirements list, **then** the plaintext `fxb_live_<32 url-safe chars>`
  is returned ONCE; the table stores only sha256 + 8-char prefix; list shows name, prefix, created,
  last used; revoke sets `revoked_at` and the key stops resolving immediately.

### AC-STB-16 [BE][T] Append a Trace entry
- **Given** `POST /ideation/build/{brId}/events` with `Authorization: Bearer <key>` and body
  `{ stage, message, prUrl?, handtestUrl?, status? }`,
- **Then** 401 for a missing/unknown/revoked key (uniform, no enumeration); 404 when the BR is not in the
  key's tenant OR has no build row (never distinguishes the two); 422 when `stage` or `message` is
  empty, `stage` > 40 chars, `message` > 2000 chars, a URL is not http(s), or `status` is not one of
  `in_progress | merged | released | failed | cancelled`.
- **Then** on success 201 with the stored entry; the row records `key_id`, `created_at` (DB clock);
  `last_used_at` on the key is bumped.

### AC-STB-17 [BE][T] Closing the loop
- **Given** an event with `status: merged` or `released` on a BR in `sent_to_build`, **then** the BR
  moves to `delivered` through the status engine on `br-tr-build-delivered` (actor none), in the same
  transaction as the entry; a second `merged` event on a delivered BR stores the entry and does not
  error.
- **Given** `status: failed | cancelled`, **then** the entry stores; the BR status is unchanged (a human
  presses "Back to ready" if they want to resend).

### AC-STB-18 [BE][T] Write-back is append-only and BR-scoped
- The key can only create events; there is no update/delete route; it cannot read or change the BR,
  the issue, or any other entity. A key of tenant A posting to tenant B's BR gets 404.

## E. Trace tab

### AC-STB-19 [FE] Trace tab renders the build (mockup section 3)
- **Given** a sent BR, **then** the Trace tab shows a summary card (Issue link, Stage badge = latest
  entry's stage, Pull request link = latest non-empty `prUrl`, Hand test link = latest non-empty
  `handtestUrl`) and a chronological timeline of entries (time in the user's tz via `useDatetime`,
  stage badge, message, links). `merged`/`released` entries use the success tone.
- **Given** a BR never sent, **then** the tab shows the single line "Not sent to build yet." (the
  existing placeholder component).
- **Given** the page is open, **then** the tab refetches on focus/tab switch (no polling loop).

### AC-STB-20 [FE][E2E] Real-click run at 375 AND 1280
- From the sidebar: Ideation > Business requirements > open a complete BR > Send to build > confirm ->
  the header shows the issue link; open the issue URL (new tab) and see label `crew-intake`; POST two
  write-back events with curl (one with `prUrl`, one `merged`) -> Trace shows both, header status is
  Delivered. Repeat the header + Trace views at 375px. Evidence under
  `documentation/plans/ideation/ideation-br-send-to-build-evidence/`.

## F. Guards

### AC-STB-21 [BE][T] Test BRs
- A test BR (`is_test`) can be sent only to a repo whose product delivery has `allowTestBuilds`
  unset -> refused 422 "Test requirements cannot be sent to build" (no crew lane for a test row).

### AC-STB-22 [BE][T] Failure isolation
- A GitHub outage during Send never leaves the BR in `sent_to_build` without an issue; a write-back
  whose status move is refused by the graph (e.g. BR archived meanwhile) stores the entry and returns
  201 with `statusMoved: false`.

### AC-STB-23 [Docs] Contract of record
- `documentation/engineering/ideation-build-handoff.md` documents the issue body format, the markers,
  the write-back endpoint, key scheme, status vocabulary and the crew-side steps (poller + trace call).
  A wire change without the doc change is a review finding.
