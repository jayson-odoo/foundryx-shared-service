# PLAN - BR "Send to build" -> GitHub crew-intake issue + crew progress write-back to Trace

Lane BR-TO-CREW (crew), branch `crew/br-send-to-build`, base `origin/main` (4b1a4ec3).
UAC: `ideation-br-send-to-build-acceptance-criteria.md`. Mockup: `documentation/mockups/br-send-to-build/index.html`.
Status: **PHASE 1 (scout + plan + mock). Nothing is built until the owner approves the mock.**

## 0. Scope in one paragraph

A "Send to build" button on the Business Requirement (BR) detail page hands the BR to the crew orchestrator:
the backend creates ONE GitHub issue (label `crew-intake`) in the repository mapped from the BR's product,
moves the BR to a new `sent_to_build` status through the status engine, and records a Trace entry. Crew then
appends progress entries through an authenticated write-back endpoint; the Trace tab renders them; a
`merged`/`released` entry moves the BR to `delivered`. The crew-side poller and trace step are built by the
orchestrator (ask a95074396 answered 29 Sep: option a); section 6 below is that contract of record.

## 1. Scout findings (file:line, verified 29 Sep 2026 on this worktree)

| Question | Answer | Evidence |
|---|---|---|
| Outbound GitHub client / token / App in shared-service? | **None.** Only a registered-but-dormant adapter-kind LABEL `github` (metadata, nothing acts on it) and keenicons glyphs. No `httpx` GitHub calls, no settings key, no provider. | `service_backend/modules/ideation/adapters.py:8-11,35`; `service_backend/modules/ideation/models.py:98-118` (`ProductAdapter` table exists, no CRUD); `grep -rIl github service_backend/app service_backend/modules` = those two files only |
| Outbound HTTP + connection-driven secrets pattern to reuse | Module providers register into the core connections registry at boot; credentials are Fernet in `connections.credentials_json`, decrypted with `app.secrets.decrypt_secret`; `test()` must name the failing step. | `service_backend/app/integrations/base.py:50-98` (provider protocol), `modules/autocount/bootstrap.py:107-114` (`register_provider`), `modules/autocount/sorento_provider.py:1-60` (outbound consumer provider, httpx, probe), `modules/autocount/services/company_service.py:29,1458` (`decrypt_secret`), `app/models/connection.py:35,105-129` |
| BR model + status enum | `BusinessRequirement` (`app_ideation.business_requirements`): `status_id` -> core `public.statuses`, `answers_json`, `template_key/version` (stamped), `is_test`, `created_by/updated_by`. Statuses are a PLATFORM-TIER seeded set (`tenant_id NULL`): `draft, grilling, ready, in_fr, delivered, archived`; edges seeded with fixed ids (`br-tr-promote` etc). Seed is insert-if-missing and runs at EVERY bootstrap. | `models.py:408-457`; `services/statuses.py:204-297` (`BR_STATUS_IDS`, `BR_STATUS_SEED`, `BR_TRANSITION_SEED`, `seed_br_statuses`); `bootstrap.py:156-172` (`install()` calls `seed_br_statuses`) |
| Where status changes happen / are audited | ONE executor: `BusinessRequirementService.set_status` -> `status_machine.transition` (409/403/422 mapping, promote gate by EDGE id, completeness validator). The engine writes `status_id`, dispatches notifications, emits in-process `StatusTransitioned` + the workflow `entity.status_changed` event. **There is no persisted status-history/audit table in core** - "audited" today = notification outbox + workflow triggers. The ideas side has its own event feed table (`idea_status_events`), BRs have none. | `services/business_requirements.py:595-700`; `app/services/status_machine.py:118-219`; `app/events.py:1-40`; `models.py:495-529` |
| Grill "N of 6 captured" | `coveredFields` = LLM-reported keys per assistant turn, stored on `ai_messages.covered_fields_json`; the 6 fields = the STAMPED template's input fields. The durable truth is `answers_json`, validated against the stamped template by `_enforce_promote_completeness` (required enforced) - the same check Promote uses. | `services/grill.py:106-118,272-294`; `app/models/ai.py:280`; FE `grill-chat.tsx:84-96`; `business_requirements.py:622-655` |
| Service-to-service API token mechanism | Two module-owned key tables, same scheme (plaintext `prefix_live_...` shown once, sha256 + 8-char lookup prefix stored, `resolve()` O(1) by prefix, uniform 401): omnichannel `WorkspaceApiKey` (`Authorization: Bearer fxw_live_`) and autocount `AcPullApiKey` (`X-API-Key`). Cross-module table reads are FORBIDDEN, so autocount duplicated the table on purpose (D9/BL-SS-210). Ideation must own its own key table too. Public routers are declared `"public": true` in the manifest. | `modules/omnichannel/api_auth.py:26-71`; `modules/omnichannel/models.py:753-773`; `modules/omnichannel/services/api_key_service.py:24-98`; `modules/autocount/pull_auth.py:1-40`; `modules/autocount/models.py:642-667`; `modules/ideation/manifest.json` (`public` routers), `routers/intake_reads.py:1-16` |
| Trace tab today | A placeholder: `BrPlaceholderTab label="Available after grilling."` - no data, no endpoint. Tabs come from `useBrForm` (`ResourceFormConfig.tabs`). | FE `components/br-placeholder-tab.tsx`; `components/use-br-form.tsx:280-285` |
| Header / where a button can go | `ResourceForm` renders identity left and `data-slot="record-actions"` right (pager, gear menu from `config.actions`, then Edit). `ResourceFormConfig` has NO slot for an extra primary button; `ResourceAction` can be hidden/disabled but not carry a reason line. **One small shell extension is needed** (section 3.4). | `components/platform/resource-form/resource-form.tsx:295-380`; `resource-form/types.ts:32-92`; `resource-list/types.ts:80-110` |
| Product -> repo mapping | **None today.** The per-product delivery config row `product_delivery` holds only `product_domain_base`, edited from the product dialog's Delivery section via `GET/PUT /ideation/products/{id}/delivery`. `ProductAdapter(kind='github')` exists as a dormant table with no CRUD. | `models.py:71-96`; `routers/products.py:31-42`; `schemas.py:135-147`; FE `app/(protected)/products/product-form-dialog.tsx:37-91` |
| BR template field keys | Platform template seeds `problem_statement, business_goal, stakeholders, success_metric, scope, constraints` - but templates are versioned + tenant-editable, so the issue body must iterate the STAMPED doc, never these keys. | `services/br_templates.py:59-94`; `grill.py:106-118` (`form.input_fields()`) |
| Frontend URL for the link-back | `settings.frontend_url` (default `http://localhost:3001`). | `app/config.py:118` |
| Crew today | No `crew-intake` consumer. `crew.toml` maps `[repos.sorento] gh=jayson-odoo/sorento-crm`; `crew spawn --repo --feature --brief-text`. | `/Users/tehjayson/Documents/foundryx/crew/crew.toml:50-55`, `crew spawn --help` |
| Program-plan alignment | The 2026-07 program plan put the GitHub issue on the FR (D4 FR->issue 1:1, Phase C AgentRunner). The owner's 29 Sep approval moves the hand-off to the BR with crew as the runner; GitHub stays machine-only (D15), humans read the Trace tab. | `PLAN-ideation-to-delivery-program.md:34-36,51,77`; `ideation-phase-c-deliver-acceptance-criteria.md:169-195` |

## 2. Decisions (all decided; owner answered asks A1-A3 on 29 Sep 2026, verbatim: "shared service to github yeah can via token, send to build yeah correct, crew writes progress yeah can")

| # | Decision |
|---|---|
| D1 | **GitHub auth = fine-grained PAT stored as a core `Connection`** (`provider='github'`, `type='scm'`, one secret field `token`), registered from the ideation bootstrap like autocount's Sorento provider. `type='scm'` is NOT exempt from one-active-per-type, so v1 = one GitHub identity per tenant (fine: one PAT covers every product repo). (**A1 = owner decided (a), 29 Sep.**) |
| D2 | **Gate = server-computed `build.canSend` + `blockers[]` on the BR detail.** Send to build requires EVERY input field of the STAMPED template to be non-empty (the owner's "6 of 6 captured" model = the grill's coverage count, the same N of M the confirm dialog shows; hand-test ruling 30 Sep after the optional `constraints` field surfaced the gap). Promote keeps its required-only validator; both share one missing-labels helper in template document order. Button disabled with ONE reason line; never confirm-with-warning. Send allowed from `draft`, `grilling`, `ready` (Send IS the Gate-0 human action) behind a NEW permission `ideation.business_requirements.send_to_build`, granted to every role that holds `.promote`. (**A2 = owner decided (a), 29 Sep.**) |
| D3 | **New BR status `sent_to_build`** (`br-status-sent-to-build`, label "Sent to build", violet, sort 4) + edges `br-tr-send-to-build` (draft/grilling/ready -> sent_to_build; three seeded rows share the label, ids `-draft/-grilling/-ready` suffixed), `br-tr-build-delivered` (sent_to_build -> delivered), `br-tr-build-back` (sent_to_build -> ready). Seeded by `seed_br_statuses` (insert-if-missing, runs every bootstrap) = lands on every existing DB automatically; no data backfill because no row can already hold it. `in_fr` keeps its existing edges. Sort orders of `in_fr/delivered/archived` shift +1 (the seed re-asserts flags only, so a one-line data migration re-sorts existing rows). |
| D4 | **Audit = the Trace itself.** New table `br_build_events` (one row per hand-off event, incl. the `sent` row with `actor_user_id`) plus `br_builds` (one row per BR: repo, issue refs, state). The status move still goes through `status_machine.transition` so notifications/workflows fire as for any BR move. No new core audit table (simplest thing that works). |
| D5 | **Product -> repo = `product_delivery.build_repo`** (nullable `owner/repo`), edited in the existing product dialog Delivery section. NOT the dormant `ProductAdapter(kind=github)` (would need a CRUD + UI for one string). Missing repo = a blocker, not a default. |
| D6 | **Issue body is template-driven**: one `## <label>` per stamped input field (no hardcoded keys - tenant-editable template), then linked ideas with votes, grill transcript, links, machine markers. Label `crew-intake` is ensured before create (`GET /labels/crew-intake`, 404 -> create). |
| D7 | **Idempotency = DB first, GitHub second, marker search as crash recovery.** Insert `br_builds` (unique on `business_requirement_id`) in state `creating` and COMMIT, call GitHub, store refs and transition in one transaction. A retry that finds a `creating` row searches the repo for `"br-id: <id>" in:body` and adopts a hit. Concurrent second click = unique violation -> 409 -> client reloads and shows the link. |
| D8 | **Write-back auth = ONE tenant-scoped ideation build key** (`fxb_live_` + 32 url-safe chars; sha256 + 8-char prefix stored in ideation's own `br_build_keys`; `Authorization: Bearer`). Least privilege by construction: the only route it opens is append-one-event on a BR that (a) belongs to the key's tenant and (b) has a `br_builds` row. Per-BR tokens rejected: no safe channel to crew (cannot ride the public issue). (**A3 = owner decided (a), 29 Sep.**) |
| D9 | **Closing the loop**: event `status in (merged, released)` -> `br-tr-build-delivered` via the engine, actor none, same transaction. `failed/cancelled` store only; a human presses "Back to ready" to resend (which creates a NEW issue? No - see D10). |
| D10 | **Resend after Back to ready** reuses the SAME issue: `br_builds` row stays, Send on a BR with an existing row that is back in `ready` posts an issue COMMENT "Re-sent to build" (marker kept) and re-transitions; never a second issue. |
| D11 | **Test BRs (`is_test`) cannot be sent** (422). No crew lane for a test row. |
| D12 | **Shell extension, not a hand-rolled header** (owner Lavish rulings: round 2 "send to build is call to action button, put Edit in the button dropdown"; round 3, anchored on the existing "..." record-actions menu: "can reuse this button to store the 'Edit' button as the dropdown"; the issue chip "is good"). `ResourceFormConfig.primaryAction?: { label, icon, disabled, reason, onRun, href? }` renders as a PLAIN primary `Button` in the record-actions slot where Edit is today; when it is set, the shell moves its Edit toggle into the EXISTING `ActionMenu` ("...") as the FIRST item, above the form actions (status moves, then Delete). No split button, no new chevron. Without `primaryAction` every existing form renders exactly as today. Disabled CTA + `reason` = the one muted line under the row (`actionsNote`); the "..." menu stays enabled so Edit is always reachable. In the sent state the CTA slot shows the issue-link chip (outline, external-link icon). |
| D13 | Crew side (poller + `crew report --trace`) is built by the orchestrator, NOT this lane (ask a95074396 = a). Section 6 is the contract. |
| D14 | **BR status set is platform-owned** (`StatusEntity(platform_owned=True)`, review round 1). The promote gate (`br-tr-promote`) and the hand-off edges (`br-tr-send-to-build-*`, `br-tr-build-delivered`, `br-tr-build-back`) are EDGE-ID contracts that only hold on the platform tier; a tenant fork would mint fresh ids and silently disable Send and the delivered close. Operators edit labels/colours; tenants do not fork this set. |
| D15 | **Send is stricter than Promote by design** (hand-test ruling 30 Sep): every stamped-template input field must be non-blank (the grill's "N of M captured" count), Promote keeps required-only. One shared missing-labels helper, document order. |
| D16 | **Fix-round rulings (review + security, 30 Sep):** a fresh `creating` row (younger than the staleness window) is another request in flight -> 409, never a second issue; only a stale row triggers marker recovery, and a hit is adopted only with the `crew-intake` label and the exact two-line marker tail; transient GitHub failures (timeout/5xx) at the create step KEEP the `creating` row, definitive 4xx drops it; the target repo must be private (GET /repos before create) or Send is refused 422; tenant text is defused (`<!--`, `@mention`, `#ref`); the public write-back also checks tenant lifecycle + module active (403, no throttle hit); `br-tr-build-back` needs `send_to_build` server-side; `br-tr-build-delivered` is refused to humans (409); the grant sweep runs only when the permission row is newly created. |

## 3. Design

### 3.1 Data (module schema `app_ideation`, alembic `0014_ideation_br_build`, revision id <= 32 chars, single head after `0013_ideation_attachment_upload`)

- `product_delivery.build_repo VARCHAR NULL` (owner/repo).
- `br_builds`: `id`, `tenant_id` (idx), `business_requirement_id` (UNIQUE), `repo`, `state` (`creating | sent | delivered | failed`), `issue_number INT NULL`, `issue_url TEXT NULL`, `issue_node_id VARCHAR NULL`, `sent_by` (user id, resolved WITH tenant at read time), `sent_at`, `created_at`, `updated_at`.
- `br_build_events`: `seq` PK, `id` unique, `tenant_id` (idx), `business_requirement_id` (idx), `kind` (`sent | crew | system`), `stage VARCHAR(40)`, `message TEXT`, `pr_url TEXT NULL`, `handtest_url TEXT NULL`, `status VARCHAR NULL`, `actor_user_id NULL`, `key_id NULL`, `status_moved BOOL`, `created_at` (DB clock). Index `(tenant_id, business_requirement_id, seq)`.
- `br_build_keys`: mirror of `AcPullApiKey` minus company scope: `id`, `tenant_id` (idx), `name`, `key_prefix` (idx), `key_hash`, `last_used_at`, `revoked_at`, `created_by`, `created_at`.
- Data migration in 0014: re-sort BR statuses (`in_fr`=5, `delivered`=6, `archived`=7) on a frozen `sa.table`. No other backfill needed (new tables; nullable column).
- `JSON` columns: none new. Datetimes: `UTCDateTime`.

### 3.2 Backend (module `ideation`)

- `github_provider.py`: `GitHubProvider` (`provider="github"`, `type="scm"`, fields `[token: password, required, secret]`, `test()` = `GET https://api.github.com/user`, names the failing step; `test_target=None`). Registered in `bootstrap.register_engine_entities` (idempotent). Core registry only; tenant-facing UI never says "Foundryx" (unchanged).
- `github_client.py`: thin httpx wrapper (timeout 15s, `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`): `ensure_label`, `create_issue`, `create_comment`, `search_issue_by_marker`. Raises `GitHubError(step, status)`; never logs the token.
- `services/build_handoff.py`: `BuildHandoffService`
  - `readiness(br) -> BuildOut` (canSend/blockers): is_test -> blocker; completeness via the SAME `validate_submission(..., enforce_required=True)` path as promote (refactor the missing-labels part into a helper both use); `product_delivery.build_repo`; ACTIVE `github` connection (`ConnectionRepository`, tenant-scoped); existing `br_builds`.
  - `send(tenant_id, br_id, actor)`: D7 sequence; issue body via `issue_body.py` (pure function over the stamped doc, answers, ideas, grill messages, frontend_url); transition on `br-tr-send-to-build-<from>` edge (fired through `set_status`-equivalent internal path that skips the promote gate but keeps the engine); writes the `sent` event.
  - `append_event(key_row, br_id, payload)`: 404 unless BR in key tenant AND has a build row; store; status move per D9 through the engine with `actor=None`; `status_moved` flag.
  - `mint_key / revoke_key / list_keys` (`BuildKeyService`, mirrors `PullKeyService`).
- Routers: `business_requirements.py` gains `POST /{br_id}/send-to-build` (perm `send_to_build`) and `GET /{br_id}/build` (perm `read`, returns `BuildOut` with `events[]`); new `build_keys.py` under `/ideation/build-keys` (perm `send_to_build`); new PUBLIC router `build_writeback.py` at `/ideation/build` (`"public": true` in the manifest) with `POST /{br_id}/events` authed by `get_build_key` (module-local sibling of `get_api_workspace`, uniform 401, throttle failures under scope `build` like the pull gateway). Routers stay HTTP + Pydantic only.
- Schemas: `BuildOut`, `BuildEventOut`, `BuildEventIn` (`stage: 1..40`, `message: 1..2000`, `prUrl/handtestUrl: http(s) only`, `status: Literal[...]`), `BuildKeyOut/BuildKeyMintIn/BuildKeyMintOut`; `BusinessRequirementDetailOut.build: BuildOut`; `DeliveryConfigIn/Out.buildRepo`.
- `permissions.csv`: `ideation.business_requirements,Business Requirements,send_to_build,Send to build,Hand a complete BR to the build crew and manage write-back keys (Maintainer)`. Grant sweep in `update_tenant`/a one-off in `install()`: copy grants of `.promote` -> `.send_to_build` for every tenant role (idempotent).
- Statuses: extend `BR_STATUS_IDS/SEED/TRANSITION_SEED` (D3). `set_status` (generic menu) refuses `br-tr-send-to-build-*` edges with 409 "Use Send to build" so the only path to `sent_to_build` is the endpoint (edge id = code contract, same trick as the promote gate).

### 3.3 Frontend

- Types: `BusinessRequirementStatus` += `'sent_to_build'`; `BuildInfo`, `BuildEvent`, `BuildKey` in `types/business-requirement.ts`; `DeliveryConfig.buildRepo`.
- Services: `business-requirement-service.{ts,mock.ts,real.ts}` += `sendToBuild(id)`, `getBuild(id)`, `listBuildKeys/mintBuildKey/revokeBuildKey`; `ideation-service` delivery add `buildRepo`. Phase 1 mock carries the four header states + a trace fixture; swap = one line at the service boundary.
- Hooks/components under `app/(protected)/ideation/business-requirements/components/`: `use-br-build.ts` (readiness + send + confirm state), `br-send-to-build-button.tsx` (builds the `primaryAction` config: CTA / disabled + reason / issue-link chip; rendering lives in the shell), `br-trace-tab.tsx` (summary card + timeline; `useDatetime`; `ClampedText` for long messages; `Badge` for stages; success tone for merged/released), `build-keys-dialog.tsx` (clone of autocount `issue-key-dialog.tsx`, list + mint + revoke, plaintext shown once with copy), product dialog field.
- Shell: `ResourceFormConfig.primaryAction` + `actionsNote` (D12) in `resource-form/types.ts` + `resource-form.tsx`: when `primaryAction` is set the plain primary CTA takes Edit's slot inside `data-slot="record-actions"` and Edit becomes the first `ActionMenu` item (Cancel/Save while editing are unchanged; the shell prepends a synthetic Edit action to the existing `ActionMenu`, which itself is untouched); the note is a full-width muted line under the flex row so it wraps under the identity at 375.
- Status menu: `use-br-actions.tsx` filters out edges whose id starts with `br-tr-send-to-build` (they are the button's), keeps "Back to ready".

### 3.4 Trace tab data
`GET /ideation/business-requirements/{id}/build` -> `{ canSend, blockers[], repo, issueUrl, issueNumber, state, sentAt, sentBy: {id, name}, stage, prUrl, handtestUrl, events: [{ id, kind, stage, message, prUrl, handtestUrl, status, statusMoved, actorName, createdAt }] }`. Fetch on tab open + window focus; no polling.

## 4. Slices (each = tester red tests -> coder -> parallel review; one coder for the lane)

| Slice | Content | Tests (tester writes first) |
|---|---|---|
| S0 | Mock approval gate. Frontend against `business-requirement-service.mock.ts`: header states, confirm dialog, Trace tab, product field, keys dialog. Shell props D12. | vitest: `br-send-to-build-button.test.tsx` (4 states, permission-hidden, pending never double-fires), `br-trace-tab.test.tsx` (empty, timeline order, success tone), `resource-form` prop render test |
| S1 | Alembic 0014 + models + `build_repo` on delivery (BE+FE) + statuses/edges + permission + grant sweep + GitHub provider registration. | pytest: `test_ideation_build_repo.py` (AC-01/03), `test_ideation_br_statuses_build.py` (AC-13 seed converge, sort), `test_ideation_send_to_build_perm.py` (AC-14 sweep), `test_github_provider.py` (AC-04/05 with a fake transport) |
| S2 | Send endpoint + readiness + issue body + idempotency (httpx `MockTransport`). | `test_ideation_send_to_build.py` (AC-06,09,10,11,12,21,22); kill test: remove the unique index -> the concurrency test must fail |
| S3 | Write-back keys + public events endpoint + status close. | `test_ideation_build_writeback.py` (AC-15..18, 22) |
| S4 | Swap mocks to real; Trace tab live; agent-browser evidence at 375 + 1280; `documentation/engineering/ideation-build-handoff.md`; engine index row in `AGENTS.md`. | AC-STB-19/20/23 report |

Hand test (crew contract): script at `laneboard/scripts/<PR>.md`; schema SQL at `crew/state/migrations/BR-TO-CREW.sql` (additive: `ADD COLUMN IF NOT EXISTS build_repo`, `CREATE TABLE IF NOT EXISTS` x3; the status re-sort UPDATE is held for the owner or skipped on the test copy - the copy runs `bootstrap_db`, which applies 0014 itself).

## 5. Risks and open points

- **GitHub content leaves the tenant boundary**: the issue body carries the BR text, ideas and grill transcript into the product's repo. The repo is expected private; the plan states it in the confirm dialog copy ("Creates an issue in <repo>"). If the owner wants redaction (e.g. drop the transcript), it is a body-builder flag.
- **One GitHub identity per tenant** (D1). Acceptable for the owner's single-org setup.
- **Dev write-back reachability**: crew runs on the same Mac as the dev stack, so the write-back to `localhost:8xxx` works; prod is `chat.foundryx.my` (public).
- **Status re-sort** touches `public.statuses` rows the module SEEDED (platform-tier, `entity_type=ideation_business_requirement`) - allowed (module-owned rows via the status engine seed, not an ALTER of a core table).
- **Search API rate limit** (30 req/min authenticated) only on the crash-recovery path.

## 6. Write-back contract of record (for the crew orchestrator)

Copied to `documentation/engineering/ideation-build-handoff.md` in S4; until then this section IS the contract.

### 6.1 Issue crew receives
- Repo = the product's `buildRepo`. Label `crew-intake` (created if missing, colour `ff5a00`). Title = BR title.
- Body (Markdown): `## <field label>` sections in template order; `## Linked ideas` (`- IDEA-0042 <title> (+3 / -0)`); `## Grill transcript` (`**assistant:** ...` / `**user:** ...`, may be truncated with a trailing "(transcript truncated)"); `## Links` (`Business requirement: <frontend_url>/ideation/business-requirements/<id>`); final lines:
  ```
  <!-- br-id: 5f1c... -->
  <!-- br-product: 9a2e... -->
  ```
- A re-send (D10) adds an issue COMMENT `Re-sent to build <ISO time>` and does not create a second issue. Crew treats the marker `br-id` as the identity.
- Crew is expected to label the issue `crew-accepted` when a lane spawns (crew side; shared-service does not read labels).

### 6.2 Endpoint
```
POST {base}/ideation/build/{brId}/events
Authorization: Bearer fxb_live_<32 url-safe chars>
Content-Type: application/json

{ "stage": "PR+CI", "message": "Draft PR opened", "prUrl": "https://github.com/jayson-odoo/sorento-crm/pull/1410", "handtestUrl": "http://localhost:3103", "status": "in_progress" }
```
- `brId` = the `br-id` marker. `stage` 1..40 chars, free text (crew uses its own vocabulary: `Sent`, `Plan`, `Mock`, `Build`, `PR+CI`, `Review`, `Merge-ready`, `Merged`, `Released`). `message` 1..2000. `prUrl`/`handtestUrl` optional http(s). `status` optional: `in_progress` (default) | `merged` | `released` | `failed` | `cancelled`.
- Responses: `201 {id, seq, stage, message, prUrl, handtestUrl, status, statusMoved, createdAt}`; `401 {"error":{"code":"invalid_api_key"}}` (missing/unknown/revoked; counts toward the IP throttle); `404` (BR not in the key's tenant or never sent - not distinguished); `422` (shape); `429` with `Retry-After` after repeated 401s.
- Status moves: `merged` or `released` -> BR `sent_to_build -> delivered` (engine edge `br-tr-build-delivered`), `statusMoved: true`; on any other BR status the entry stores and `statusMoved: false`. `failed`/`cancelled`/`in_progress` never move the BR.
- Idempotency: the endpoint is append-only; crew should send each stage change once. Duplicate posts create duplicate entries (harmless, visible). No update/delete route exists.
- Key issuance: Ideation > Business requirements > "..." > Build write-back keys > Mint; plaintext shown once. Store it in `crew/state/secrets`. Revoke from the same dialog.
