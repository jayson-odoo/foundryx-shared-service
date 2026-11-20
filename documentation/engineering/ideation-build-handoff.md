# Ideation: BR "Send to build" hand-off (contract of record)

A Business Requirement (BR) that is complete can be sent to the build crew. Sending creates ONE GitHub issue labelled `crew-intake` in the repository mapped from the BR's product, moves the BR to `sent_to_build` through the status engine, and starts a Trace. The crew orchestrator then appends progress entries through an authenticated write-back endpoint; the BR page Trace tab renders them, and a `merged` or `released` entry moves the BR to `delivered`. Humans read the Trace tab, never GitHub.

Plan: `documentation/plans/ideation/PLAN-ideation-br-send-to-build.md`. UAC: `ideation-br-send-to-build-acceptance-criteria.md` (same folder). Code: `service_backend/modules/ideation/` (`services/build_handoff.py`, `services/issue_body.py`, `services/build_keys.py`, `build_auth.py`, `github_client.py`, `github_provider.py`, `routers/build_keys.py`, `routers/build_writeback.py`).

## 1. Pieces and where they live

- **GitHub connection.** A core `Connection` with provider `github`, type `scm`, one secret field `token` (a fine-grained personal access token, Fernet encrypted, never echoed). Registered from the ideation bootstrap. `scm` is subject to one active connection per type, so a tenant has one GitHub identity. The token needs Issues read and write on every target repository (label creation needs the same). Test connection = authenticated `GET https://api.github.com/user` (200 = ok with the login; 401 or 403 = "GitHub rejected the token"; transport error = "GitHub is unreachable"). Configured from Settings > Integrations.
- **Product to repository.** `product_delivery.build_repo` (nullable `owner/repo`, pattern `^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`), edited in the product dialog Delivery section through `PUT /ideation/products/{id}/delivery` (`buildRepo`; null clears; omitted leaves the stored value). `productDomainBase` is still required on that PUT (BL-SS-294). A missing repo is a blocker, never a default.
- **Permission.** `ideation.business_requirements.send_to_build` (label "Send to build"). It gates Send, the Business requirement build write-back keys and "Back to ready" on a sent BR. Existing tenants: `sweep_send_to_build_grants(db)` (called from the module `install()`, idempotent) grants it to every role, in every tenant, that already holds `ideation.business_requirements.promote`, stamping the role's own tenant id. The sweep is one-shot: it runs only when the permission row is newly created by the module sync (first deploy of this feature), so a later deliberate removal of the grant is respected.
- **Status.** `sent_to_build` (id `br-status-sent-to-build`, label "Sent to build", violet, sort 4; `in_fr`, `delivered`, `archived` moved to sort 5, 6, 7 by migration `0014_ideation_br_build`). Edges: `br-tr-send-to-build-draft`, `br-tr-send-to-build-grilling`, `br-tr-send-to-build-ready` (each into `sent_to_build`), `br-tr-build-delivered` (`sent_to_build` to `delivered`), `br-tr-build-back` (`sent_to_build` to `ready`, label "Back to ready"). The seed is insert-if-missing and runs at every bootstrap. The BR status entity is registered platform-owned (operators edit it, tenants cannot fork it) because the promote gate and these hand-off edges are edge-id contracts that only hold on the platform tier. The generic status move refuses any `br-tr-send-to-build*` edge with 409 "Use Send to build"; the Send endpoint is the only caller that fires them. The status actions menu does not list the send edges.
- **Tables** (schema `app_ideation`, migration `0014_ideation_br_build`): `br_builds` (one row per BR, unique on `business_requirement_id`, state `creating | recovering | sent | delivered | failed`), `br_build_events` (append-only Trace, `seq` is the order), `br_build_keys` (write-back keys).

## 2. Readiness (`build` on the BR detail)

`GET /ideation/business-requirements/{id}` carries `build`, and `GET /ideation/business-requirements/{id}/build` returns the same object (permission `.read`). Fields: `canSend`, `sendEdgeAvailable`, `fieldsDone`, `fieldsTotal`, `blockers[]`, `repo`, `issueUrl`, `issueNumber`, `state` (`none` until a row exists), `sentAt`, `sentBy {id, name}`, `stage`, `prUrl`, `handtestUrl`, `events[]` (oldest first: `id`, `seq`, `kind`, `stage`, `message`, `prUrl`, `handtestUrl`, `status`, `statusMoved`, `actorName`, `createdAt`). `stage` is the latest entry's stage; `prUrl` and `handtestUrl` are the latest non-empty values. List rows do not carry `build`.

`sendEdgeAvailable` says whether a send edge leaves the BR's status (false in FR, delivered, archived: the header keeps the plain Edit primary). `canSend` is true only when the BR's status has a send edge (draft, grilling, ready) and there are no blockers. A BR past the send edges (sent, delivered, archived) has `canSend` false and no blockers. Blockers, in this order (Send needs EVERY input field of the stamped template filled, required or not; Promote keeps the required-only rule):

1. "Test requirements cannot be sent to build" (a test BR).
2. "Missing: <field labels>" (the same completeness validator Promote uses, over the stamped template; labels in document order).
3. "Set the build repository on the product <name>".
4. "Connect GitHub in Settings > Integrations" (needs an ACTIVE `github` connection in the BR's tenant).

## 3. Send

`POST /ideation/business-requirements/{id}/send-to-build` (permission `send_to_build`) returns the refreshed BR detail.

- Not sendable: 422 with `{"detail": {"message": <first blocker>, "blockers": [...]}}`, no GitHub call. Unknown or other-tenant BR: 404. Missing permission: 403.
- Order (idempotent): insert `br_builds` in state `creating` and COMMIT (a unique violation from a concurrent send returns 409); ensure the label; create the issue; then in ONE transaction store the issue refs, state `sent`, `sent_by`, `sent_at`, fire the status edge for the current status through the status engine (notifications and workflow events ride it), and write the `sent` Trace entry (stage `Sent`, message "Sent to build by <name>").
- A second send on a sent BR returns 200 with the existing issue and makes no GitHub call.
- Crash recovery: a leftover `creating` row makes the next send recover instead of creating blindly. A row younger than two minutes means another request is in flight: 409 "This requirement is already being sent to build. Try again in two minutes." with no GitHub call and the row untouched. An older row is claimed with one compare-and-set (state `recovering`, fresh `updated_at`; a lost race is the same 409), then the repository's issues labelled `crew-intake` are listed (any state, up to 5 pages, following the Link next header; the search API is never used) and an issue is adopted only if its body ends with EXACTLY the two marker lines for this BR and product. Otherwise one new issue is created. A `recovering` row is never dropped: any failure during recovery keeps it and returns 502.
- Re-send (Back to ready, then Send again): an issue comment `Re-sent to build <ISO time>` on the SAME issue, the BR re-enters `sent_to_build`, a new `sent` Trace entry. Never a second issue.
- Public repository: before anything is created the repository is looked up; if it is not private the answer is 422 (message names the repository as public), nothing is created and no row is kept. A repository stored in a bad shape never reaches the wire.
- GitHub failures: a definitive refusal (401, 403, 404, 422) or any failure before the issue create removes the `creating` row and leaves the status unchanged; a transient failure of the issue create itself (timeout, 5xx) keeps the `creating` row as the recovery anchor. All return 502: "GitHub rejected the token" (401, 403), "Repository <owner/repo> not found or the token cannot see it" (404), "GitHub is unreachable" (transport), "GitHub returned an error (<status>)" (other). The token is never echoed.

### Issue crew receives

Repository = the product's `build_repo`. Label `crew-intake` (created with colour `ff5a00` if missing). Title = the BR title. Body is Markdown:

- one `## <field label>` section per input field of the STAMPED template, in template order (never hardcoded keys); a blank answer reads `(not provided)`;
- `## Linked ideas`: `- <idea number> <title or problem> (+<up>)`;
- `## Grill transcript`: `**<role>:** <content>` per turn; omitted when the grill has no messages; truncated first (with a final `(transcript truncated)` line) so the whole body stays under 65000 characters;
- `## Links`: `Business requirement: <frontend url>/ideation/business-requirements/<id>`;
- the last two lines, always:

```
<!-- br-id: <business requirement id> -->
<!-- br-product: <product id> -->
```

The `br-id` marker is the identity of the hand-off; read it from the LAST two lines of the body. Tenant text is neutralised so it cannot forge or trigger anything: a zero-width space (U+200B) follows `@`, `#` before digits, `GH-` before digits, `github.com` before its slash, and `<!`, and sits inside the words `br-id:` and `br-product:`. Crew must therefore read the markers from the last two lines and must not rely on plain-text equality of the body sections. The body contains no em or en dashes. Crew is expected to label the issue `crew-accepted` when a lane spawns; shared-service does not read labels. Crew must keep the `crew-intake` label on the issue: crash recovery lists the repository's issues by that label.

## 4. Write-back (crew to Trace)

```
POST {base}/ideation/build/{brId}/events
Authorization: Bearer fxb_live_<32 url-safe chars>
Content-Type: application/json

{ "stage": "PR+CI", "message": "Draft PR opened", "prUrl": "https://github.com/acme/repo/pull/1410", "handtestUrl": "http://localhost:3103", "status": "in_progress" }
```

`brId` is the `br-id` marker. Public route (no session); the tenant comes from the key.

- `stage` 1 to 40 characters, free text (crew's own vocabulary, for example `Sent`, `Plan`, `Mock`, `Build`, `PR+CI`, `Review`, `Merge-ready`, `Merged`, `Released`). `message` 1 to 2000. `prUrl` and `handtestUrl` optional, http or https only. `status` optional: `in_progress` (default), `merged`, `released`, `failed`, `cancelled`.
- 201 body: `id`, `seq`, `kind` (`crew`), `stage`, `message`, `prUrl`, `handtestUrl`, `status`, `statusMoved`, `actorName` (null), `createdAt` (Z-suffixed UTC).
- 401 `{"error": {"code": "invalid_api_key", "message": ...}}` for a missing, malformed, unknown, revoked or wrong-scheme key (one uniform answer; a session token is not a key). Each 401 counts one failure against the caller's IP under the `build` throttle scope (default 5 failures per 15 minutes); the next attempt is 429 `{"error": {"code": "too_many_requests", ...}}` with `Retry-After`. Successful calls never touch the bucket.
- 403 `{"error": {"code": "service_not_enabled", ...}}` when the key's tenant is suspended or archived, or the ideation module is inactive for it. It records no throttle failure and does not stamp the key's last used time.
- 404 `{"detail": "Not found."}` when the BR is not in the key's tenant OR has never been sent (the two are not distinguished, nor from an unknown id).
- 422 (`{"detail": [...]}`, the default validation shape) for a bad shape; nothing is stored.
- Status moves: `merged` or `released` move the BR `sent_to_build` to `delivered` through the engine edge `br-tr-build-delivered` with no actor, in the same transaction as the entry, set the build row to `delivered` and answer `statusMoved: true`. If that edge is not available from the BR's current status (already delivered, archived, sent back to ready) the entry is stored, `statusMoved` is false and the answer is still 201. `in_progress`, `failed` and `cancelled` never move the BR (a human presses "Back to ready" to resend).
- Append-only: there is no update or delete route, and the key opens nothing else. Duplicate posts create duplicate entries; crew sends each stage change once.

## 5. Keys

Ideation owns its keys (`br_build_keys`); cross-module tables are never read. Scheme `fxb_live_` plus 32 url-safe characters, shown ONCE on mint. Stored: sha256 and the 8-character lookup prefix (characters 9 to 16 of the key). Endpoints (session, permission `send_to_build`): `POST /ideation/build-keys {"name"}` returns 201 with `id`, `name`, `keyPrefix`, `createdAt`, `lastUsedAt`, `plaintext`; `GET /ideation/build-keys` lists active keys without plaintext; `DELETE /ideation/build-keys/{id}` revokes immediately (204; 404 for another tenant's or an unknown id). The UI uses the core deferred-action `ideation_build_key.revoke` (grace-window countdown, no confirm dialog). Mint and revoke from the Business requirements list, "Build write-back keys". Crew keeps the key in `crew/state/secrets`.

## 6. Crew side (built by the crew orchestrator, not by this repository)

1. Poll the target repositories for open issues labelled `crew-intake` that do not yet carry `crew-accepted`.
2. For each, read the `br-id` marker, spawn a lane against the repository with the issue body as the brief, and label the issue `crew-accepted`.
3. At each stage change call the write-back endpoint with the stage, a short message, and the PR and hand-test links when they exist.
4. On merge send a final entry with `status: merged` (or `released` after deploy); shared-service moves the BR to Delivered.
5. A comment `Re-sent to build <time>` on an existing issue means the human sent the same BR again: continue or restart the lane for that marker, never open a second lane.

## 7. Known limits

- One GitHub identity per tenant (one active `scm` connection).
- The issue body carries the BR text, linked ideas and grill transcript into the target repository, which is expected to be private (BL-SS-296 tracks a redaction flag).
- The product blocker is plain text (BL-SS-295).
