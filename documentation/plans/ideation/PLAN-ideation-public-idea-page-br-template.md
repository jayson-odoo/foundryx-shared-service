# Plan - issue #90: a real public idea page (W1), the BR template seed survives a late migration (W2), test idea -> test BR (W3)

Worktree `foundryx-shared-service-ideapage`, branch `fix/public-idea-page-and-br-template` (from `c855319d`). Module = `service_backend/modules/ideation` (abbrev. `ideation/`). Owner rulings in #90's comments bind (W3 approved 26 Sep 2026 ~12:50Z). #89's lane (`fix/deploy-abort-on-module-migration-failure`) owns bootstrap ORDERING; this PR never touches `app/module_loader.py`.

UAC ids used below: `AC-90-1xx` (W1), `AC-90-2xx` (W2), `AC-90-3xx` (W3). See `ideation-public-idea-page-br-template-acceptance-criteria.md` for the full Given/When/Then list.

## Resolved rulings (coordinator, recorded here for the permanent record)

- **Q1 (W2 link target - "the dialog must say what to do ... link to the template admin page").** No BR template admin page exists anywhere in the codebase. Ruling: **no link**. The Alert names the fix in plain text ("Ask an administrator to restore the Business Requirement template.") with no `<a>`/link. A BR template admin page is logged as **BL-SS-278** (`documentation/backlogs/backlog.md`).
- **Q2 (W1 footer mark vs white-label - "a footer with the Foundryx mark").** Ruling: **keep the white-label footer**. The footer (and header) use the existing `BrandMark` component unchanged - it shows the Foundryx mark exactly when the host is unbranded, the tenant's own logo/name otherwise. The public idea page does not special-case this; it reuses the SAME extracted `BrandMark` the shell already uses.
- **R1 (W1 "product name" in the header).** Ruling: the idea's own **core Product** (e.g. "Sorento CRM"), shown beside the tenant `BrandMark` - not the tenant/app name. `productName` is a new field on `PublicIdeaStatusOut`, resolved tenant-scoped from the idea's `product_id`.

---

## 1. W1 - public idea page

### 1.1 What the endpoint returns today vs what the page needs

Before this plan (`GET /public/ideas/{token}`):
- Router `ideation/routers/public_ideas.py` - token shape gate, uniform 404, delegates to the service.
- Service `ideation/services/public_status.py` - lookup by `status_token` across tenants, `Tenant.signin_allowed` gate, draft 404 by `status_row.key == "draft"`, returns `title`, `status` (LABEL), `ideaNumber` only.
- Schema `ideation/schemas.py` `PublicIdeaStatusOut` - exactly 3 keys.
- Tests pinned the 3-key contract (`test_ac_1601_returns_only_title_status_idea_number`, `test_ac_1601_no_auth_header_required`) - REWRITTEN, not deleted, per the owner's #90 ruling (the exact-key-set pin now lives in `test_public_status_exact_key_set_and_no_pii`, AC-90-104).

Page needs (new keys, all camelCase, `PublicIdeaStatusOut` stays an `ApiModel` so `submittedAt` is Z-suffixed):

| key | source | note |
|---|---|---|
| `title`, `status`, `ideaNumber` | unchanged | `status` = current LABEL (back-compat) |
| `statusColor` | current `Status.color` | FE maps via `colorToTone`/`colorToHex` |
| `productName` | `Product.name` WHERE `id = idea.product_id AND tenant_id = idea.tenant_id` | R1: the idea's own Product |
| `problem`, `proposedSolution`, `impact`, `department` | `Idea` cols | nullable |
| `submitterFirstName` | see 1.4 | nullable, first token only |
| `submittedAt` | `idea.created_at` | date only rendered |
| `upvotes` | `idea.upvotes` | "votes" |
| `nextStep` | derived, 1.3 | string |
| `timeline` | derived, 1.2 | `[{label, color, state}]`, `state` in `done|current|upcoming` |

Explicitly NOT returned (pinned by AC-90-104): `id`, `productId`, `tenantId`, `statusId`, status `key`, `submitterContactId`, any phone/email, last name, `submitterName` (full), `submitterTier`, `rawText`, `capturedJson`, `intakeState`, `attachments`, `downvotes`, `priority`, `isTest`, `statusToken`.

Backend change: `PublicIdeaStatusService.resolve` builds the richer DTO (every new read keyed on the idea ROW's own `tenant_id`, never input); `PublicIdeaTimelineStepOut(ApiModel){label,color,state}` + widened `PublicIdeaStatusOut`; router unchanged except it sets `Cache-Control: no-store` (and, per review round 2, `X-Robots-Tag: noindex` + `Referrer-Policy: no-referrer`) on the 200. The draft gate switches from `key == "draft"` to `status_row.is_initial` (trait flag rule).

### 1.2 Status timeline (tenant's set, trait flags, never category)

- Rows: `StatusRepository(db).list_for_entity(IDEA_ENTITY, idea.tenant_id, include_inactive=False)` - resolves the tenant tier and orders `sort_order ASC, created_at ASC`.
- Main path = rows where `not is_initial and not is_archived` (platform set -> New, Triaged, Linked to BR, Building, Delivered).
- Current on the main path: steps before it `done`, it `current`, after `upcoming`.
- Current NOT on the main path (an `is_archived` off-ramp, or a status the resolved tier no longer carries): timeline = `[first main-path step done, current current]`. Truthful without history (no status-history table - **BL-SS-279**).
- Review round 2 nit: the CURRENT status row lookup is scoped `Status.tenant_id IN (idea.tenant_id, NULL)` - a status id belonging to another tenant's fork must resolve to nothing (uniform 404), same polymorphic-stored-id rule as every other lookup here.

### 1.3 "What happens next" copy

Stored in the module, backend-derived: `PUBLIC_NEXT_STEP: Dict[str, str]` in `ideation/services/public_status.py`, keyed by the platform status KEY (a tenant fork copies keys; display lookup only, no behaviour branch). Fallback for an unknown/tenant-added key derives from trait flags: `is_terminal or is_archived` -> "This idea is closed."; else "The team will review it and update this page." Tenant-editable copy = deferral **BL-SS-277**.

### 1.4 Submitter first name (security-critical)

`_first_name(idea)`: source = `idea.submitter_name`, else the contact looked up `Contact.id == idea.submitter_contact_id AND Contact.tenant_id == idea.tenant_id` (polymorphic stored-id rule) -> `first_name`. Never falls back to "Unknown" - null hides the line.

**Review round 2 hardened this guard** (a token-only digit-count check leaked fragments - probes: `"+60 12-345 6789"` -> leaked `"+60"`, `"0123 456 789"` -> leaked `"0123"`, a fullwidth `＠` email -> leaked the whole email, `"Ali_0123"` -> leaked whole). The fixed algorithm:
1. NFKC-normalize the WHOLE raw name first (a fullwidth `＠` otherwise bypasses an ASCII-only `@` check).
2. Reject on the WHOLE normalized string carrying 5+ digits anywhere (any Unicode digit) or containing `@` - a phone split across tokens leaves an individual token with too few digits to trip a token-only check.
3. Only THEN take the first token, and reject it outright if it carries ANY digit or has no alphabetic character at all.

### 1.5-1.7 Component tree, reuse, responsive, security note

Unchanged from the original design intent: `PublicBrandedShell` generalises its chromeless-path predicate to cover `/public/ideas/`; `BrandMark` is extracted unchanged to `components/platform/branding/brand-mark.tsx` (Q2: white-label rule preserved, both header and footer use it); `StatusBadge` reused for the pill; new components under `app/(public)/public/ideas/[token]/components/`. Responsive at 375px (single column) and 1280px (two-column with a sticky aside). Security: access path unchanged (same token gate, uniform 404, no new params); every new read scoped by the idea row's own `tenant_id`; personal data = first name only (hardened per 1.4); `Cache-Control: no-store` + `referrer: no-referrer` + `robots noindex` (backend headers added per review round 2; the frontend layout already carried the meta-tag equivalents).

---

## 2. W2 - BR template seed on a late-migrated database

### 2.1 Failing sequence (issue #89's shape, reproduced as STATES since sqlite `create_all` cannot replay the actual Alembic-lock-timeout bug)

1. Deploy at code head 0010, DB at 0007. `bootstrap_modules` -> `install(engine, db)` BEFORE `run_module_migrations`.
2. `install`: `create_schema_and_tables` commits the NEW tables (empty). Then `seed_br_template(db)` inserts the platform template + v1 and flushes on the SHARED session - not committed.
3. `run_module_migrations` -> a later migration's `CREATE INDEX` waits on the open session's lock -> timeout -> exception.
4. `bootstrap_modules` rolls back: the flushed template + version rows are discarded. Tables stay (committed by step 2), empty.
5. `resolve_active_template` returns `None` -> BR create 422s "No active Business Requirement template is configured." forever.
6. A plain re-run of bootstrap seeds it (insert-if-missing on an empty table works) - but ANY half-state (row present, pointer NULL/dangling, or zero version rows) is permanent, because the old guard keyed on the template ROW only.

### 2.2 Idempotent fix

`seed_br_template(db)` becomes "ensure" semantics, three independent idempotent repairs:
1. Platform template row (`template_key = BR_TEMPLATE_KEY`, `tenant_id IS NULL`): create if missing.
2. Version rows: if none, create v1 from `br_target_schema()` (validated with `validate_form_doc`).
3. Active pointer: if NULL or not one of this template's own version rows, point it at the HIGHEST version. A VALID pointer is NEVER moved - proven not just for "the highest version was already active" (the original test's blind spot) but for an OLDER version deliberately reactivated while newer ones exist (review round 2 strengthening of AC-90-204).

`db.flush()` only - the caller (`bootstrap_modules`) commits. New `br_template_is_active(db, tenant_id) -> bool` = `resolve_active_template` + `active_version_number` not `None`.

### 2.3 Dialog change

- `create` raises `HTTPException(422, detail={"code": "br_template_unavailable", "message": "..."})`.
- New `GET /ideation/business-requirements/template-status` -> `BrTemplateStatusOut{active: bool}`, `require_permission("ideation.business_requirements.read")`, declared ABOVE `/{br_id}` so the literal path wins.
- FE: `templateStatus()` service method, `use-br-template-status` hook, the create dialog renders an Alert + disables Create when inactive (Q1: no link), `promote-to-br.ts` maps the same code to the same toast copy.

---

## 3. W3 - test idea -> test BR

### 3.1 Where it was refused before this plan
`_link_ideas` (the single funnel for promote-create and the explicit link endpoint): `if idea.is_test: 422`. Test to INVERT: `test_promote_refuses_test_idea` (issue #1179's original rule, now superseded by the #90 W3 ruling).

### 3.2 Data model + migration
`BusinessRequirement.is_test = Column(Boolean, nullable=False, default=False)` (mirrors `Idea.is_test`). New `ideation/alembic/versions/0011_ideation_br_is_test.py` (`down_revision = "0010_ideation_intake_contract"`, Postgres-only `ADD COLUMN IF NOT EXISTS`).

### 3.3 Service rules (server-derived, never client input)
- `create`: when `idea_ids` given, `_derive_lane` computes the lane from the ideas' `is_test` (tenant-scoped). All-test -> `br.is_test = True`; all-real -> `False`; mixed -> 422 **with the exact message** "Test and real ideas cannot be promoted together." (review round 2: pinned so the test proves `_derive_lane` itself catches it, not a fallthrough to `_link_ideas`' different message) and no BR left behind. Manual create (no ideas) -> always `False`. A client-sent `isTest` is ignored (`BusinessRequirementCreateIn` has no such field).
- `_link_ideas`: lane check is bidirectional - `bool(idea.is_test) != bool(br.is_test)` -> 422, with a message naming whichever side is wrong.
- `is_test` immutable (no update path writes it). Status moves, promote gate, grill, delete behave normally for a test BR.
- **Disclosure (review round 2):** `is_test` ONLY gates list/count visibility and the promote/link lane - a status move on a test BR rides the SAME `status_machine.transition` as a real one, so it still fires real same-transaction notifications and any `entity.status_changed` workflow trigger. Documented in `BusinessRequirementService.set_status`'s docstring and the `is_test` column comment.
- `_serialize` adds `isTest=bool(br.is_test)`.

### 3.4 Every list/count query
| Site | Change |
|---|---|
| `BusinessRequirementService.list` + router | EXCLUDE `is_test` by default; `include_test` param, router `Query(False, alias="includeTest")` |
| `get` / `_br_or_404`, `linked_business_requirements`, `linked_ideas`, `_idea_counts` | no filter - a test BR detail must open, and the lane invariant means these never cross-contaminate |
| `br_count_records` / `br_migrate_records` | DO NOT exclude - status-engine integrity hooks (delete/migrate guard); excluding would let a status holding test BRs be deleted |

### 3.5 Frontend
`types/business-requirement.ts` gains `isTest`; service trio `list({..., includeTest})`; `hooks/use-business-requirements.ts` gains `includeTest`/`setIncludeTest`; `br-view.tsx` gets a "Show test requirements" switch; `use-br-list-config.tsx` shows the TEST badge; `use-br-form.tsx` prepends the badge to the subtitle and passes `includeTest` to the record pager; `idea-brs-tab.tsx` shows the badge; `use-ideas-list-config.tsx` disables promote only for a MIXED selection.

---

## 4. Deferrals filed to `documentation/backlogs/backlog.md`

- **BL-SS-277** - Tenant-editable "what happens next" copy per idea status.
- **BL-SS-278** - Business Requirement template admin page (Q1's answer - no such page exists anywhere).
- **BL-SS-279** - Idea status history so the public timeline can mark exactly which steps an off-ramped idea passed.
- **BL-SS-280** - Operator-captured ideas never get `idea_number`/`status_token` (`services/actions.py`'s `create_operator` never calls `mint_idea_identity`) - found during the S4 evidence run; decide whether operators may share a track link.

## 5. Slice order (as executed)

1. Tester (Sonnet): all RED tests, confirmed failing for the right reason, committed `[skip ci]` (`ff826692`).
2. Coder BE (Sonnet): W2 seed + status route + 422 code, W3 model/0011/service/router, W1 service/schema/router; green pytest; kill-tests recorded (`ad9ae668`).
3. Coder FE (Sonnet, concurrent): W1 components + shell predicate + BrandMark extraction, W2 dialog/toast/hook/service, W3 badges/toggle/pager/promote gate.
4. Coordinator follow-up round 1: strengthened AC-90-204 (an older valid pointer must never be repointed), cherry-picked the pre-existing `test_s13_flip_baseline_seed.py` real-clock TTL fix (`710e88c8`, `6460ade3`).
5. Review round 2 (security-focused, public unauthenticated surface + PII): B2 first-name guard fragment leaks, the tenant-scoped Status lookup nit, the AC-90-303 wrong-reason pass, optional hardening headers, the test-BR notification/workflow disclosure, the operator-track-link backlog item, and these S3 process artefacts - THIS round.
6. Tester: re-run the browser evidence against the current head (S4 evidence rows in the Test Execution Report are marked "pending re-run").
7. Reviewer (Opus): final diff vs UAC + design hard-fails; final push without `[skip ci]`; PR title per the brief; comment on #90.
