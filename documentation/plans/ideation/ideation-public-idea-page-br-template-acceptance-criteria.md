# Issue #90 - Public idea page, BR template seed repair, test idea -> test BR · Acceptance Criteria

**Source plan:** `PLAN-ideation-public-idea-page-br-template.md`
**Issue:** [jayson-odoo/foundryx-shared-service#90](https://github.com/jayson-odoo/foundryx-shared-service/issues/90) (owner rulings in comments bind; W3 ruling 26 Sep 2026 ~12:50Z)
**Branch:** `fix/public-idea-page-and-br-template`, worktree `foundryx-shared-service-ideapage`
**Scope:** W1 a real public idea status page (was a 3-key stub); W2 the BR template seed survives a database that reached a half-seeded state (issue #89's failure shape); W3 a test idea may promote to a TEST Business Requirement.

Format: each AC is independently verifiable (Given/When/Then). `[BE]` backend · `[FE]` frontend · `[E2E]` real-click · `[T]` unit/integration test. Ids are derived from the tests' own docstrings (backend: `service_backend/tests/test_ideation_public_status.py`, `test_ideation_br_template_seed.py`, `test_ideation_br.py`; frontend: the files listed per AC). The Test Execution Report keys back PASS/FAIL/DEFERRED per id.

---

## W1 - the public idea page (AC-90-101..112)

### AC-90-101 - the page returns every new field, with real values [BE][T]
- **Given** a captured idea with problem/solution/impact/department/upvotes/submitter set, **when** `GET /public/ideas/{token}` is called, **then** the response carries `title`, `status` (LABEL), `ideaNumber`, `statusColor`, `productName`, `problem`, `proposedSolution`, `impact`, `department`, `submitterFirstName`, `submittedAt`, `upvotes`, a non-empty `timeline` (each step `{label, color, state}`, `state` in `done|current|upcoming`), and a non-empty `nextStep`.
- Test: `test_public_status_returns_page_fields`.

### AC-90-102 - status timeline order and states, driven by `sort_order` [BE][T]
- **Given** the platform Idea status set (captured/triaged/linked/building/delivered on the main path), **when** the idea sits on `triaged`, **then** the timeline lists all 5 main-path labels in order with New=done, Triaged=current, the rest upcoming.
- **Given** a tenant fork with `linked` and `building`'s `sort_order` swapped, **when** the idea sits on `building`, **then** the timeline reorders to New, Triaged, Building, Linked to BR, Delivered - proving the order comes from the DB, never a hardcoded key sequence.
- Test: `test_public_timeline_order_and_states`.

### AC-90-103 - an off-ramp status renders a truthfully short timeline [BE][T]
- **Given** an idea on `rejected` (`is_archived`, not on the main path), **then** the timeline is exactly `[New done, Rejected current]` - never a fabricated position among steps the idea never passed.
- Test: `test_public_timeline_off_ramp`.

### AC-90-104 - the exact key set, and no PII beyond a first name [BE][T]
- **Given** any servable idea, **then** the response body's key set is EXACTLY `{title, status, ideaNumber, statusColor, productName, problem, proposedSolution, impact, department, submitterFirstName, submittedAt, upvotes, nextStep, timeline}` - no `id`/`productId`/`tenantId`/`statusId`/`key`/`submitterContactId`/`phone`/`email`/`lastName`/`submitterName`/`submitterTier`/`rawText`/`capturedJson`/`intakeState`/`attachments`/`downvotes`/`priority`/`isTest`/`statusToken`/`draftId`/`submitter`/`product`, and no `@` or last name anywhere in the raw body text.
- Test: `test_public_status_exact_key_set_and_no_pii`.

### AC-90-105 - first name only, first token [BE][T]
- **Given** an operator-authored idea with `submitter_name = "Jayson Teh"`, **then** `submitterFirstName == "Jayson"` (last name never leaks).
- Test: `test_first_name_only`.

### AC-90-106 - the first-name guard never leaks a phone/email fragment (security-critical) [BE][T]
- **Given** intake's find-or-create writes `first_name = phone` for every new WhatsApp contact, **then** `submitterFirstName` is `null`, never the phone.
- **Given** review round 2's probe set - a phone split by spaces/hyphens (`"+60 12-345 6789"`, `"0123 456 789"`), a fullwidth `@` (U+FF20, `"a＠b.co"`), and a name-shaped string carrying digits (`"Ali_0123"`) - **then** none of the corresponding forbidden fragments (`"+60"`, `"0123"`, `"a@b.co"`, `"Ali_0123"`) ever appear in the response body, and `submitterFirstName` is `null` for every case.
- Test: `test_first_name_never_a_phone` (parametrized, 5 cases: the original phone-contact case + the 4 review-round-2 probes).

### AC-90-107 - Product/Contact lookups are tenant-scoped (polymorphic stored-id rule) [BE][T]
- **Given** an idea whose `product_id`/`submitter_contact_id` point at rows owned by ANOTHER tenant (defensive; never happens in the real flow), **then** `productName` and `submitterFirstName` both resolve to `null` - never the other tenant's data.
- Test: `test_product_and_contact_lookups_tenant_scoped`.

### AC-90-107b - the current-Status lookup is tenant-scoped too (review round 2 nit) [BE][T]
- **Given** an idea's `status_id` pointing at a status row owned by ANOTHER tenant's fork (defensive, same rule as AC-90-107), **then** the page 404s uniformly - never that other tenant's status label/color.
- Test: `test_status_lookup_is_tenant_scoped`.

### AC-90-108 - "what happens next" copy, with a trait-flag fallback [BE][T]
- **Given** a known platform status key (e.g. `captured`), **then** `nextStep` is its authored sentence.
- **Given** a tenant-added status key unknown to `PUBLIC_NEXT_STEP` that is `is_terminal`/`is_archived`, **then** `nextStep` falls back to "This idea is closed."
- Test: `test_next_step_copy_and_fallback`.

### AC-90-109 - `Cache-Control: no-store` on the 200 [BE][T]
- **Given** the page now carries idea content, **then** every 200 response carries `Cache-Control: no-store`.
- Test: `test_public_status_no_store_header`.

### AC-90-109b - optional hardening headers (review round 2) [BE][T]
- **Given** the token is a bearer credential forwarded over WhatsApp/links, **then** every 200 response also carries `X-Robots-Tag: noindex` and `Referrer-Policy: no-referrer`.
- Test: `test_public_status_hardening_headers`.

### AC-90-110 - the full page renders (FE) [FE][T]
- **Given** the widened contract, **then** the page renders the header (product name), idea number, title, a status pill, first name, date, votes, four labelled sections (problem/proposed solution/impact/department, each rendering "Not provided" when empty), the next-step line, and a footer mark.
- Test: `app/(public)/public/ideas/[token]/page.test.tsx` describe block "AC-90-110 the full page contract".

### AC-90-111 - the status timeline renders client-side [FE][T]
- **Given** the `timeline` array, **then** each step renders with a `data-state` attribute matching `done`/`current`/`upcoming`, including the off-ramp shape.
- Test: `page.test.tsx` describe block "AC-90-111 the status timeline".

### AC-90-112 - white-label footer/header mark (Q2 ruling) [FE][T]
- **Given** an unbranded host, **then** the Foundryx mark shows (`BrandMark`'s existing unbranded-wordmark behaviour, extracted unchanged to `components/platform/branding/brand-mark.tsx`).
- **Given** a branded tenant, **then** its own logo/name shows instead - the public idea page NEVER hardcodes "Foundryx" text (Q2 ruling: keep the existing white-label `BrandMark` rule, do not special-case this page).
- Test: `components/platform/branding/brand-mark.test.tsx` (regression, reused by the header/footer) + `app/(public)/public-branded-shell.test.tsx` ("renders no AuthFooter on /public/ideas/:token").

---

## W2 - the BR template seed survives a late migration (AC-90-201..211)

### AC-90-201 - the #89 rollback sequence leaves no platform template (characterization) [BE][T]
- **Given** `install()` seeds the template via flush-only then the session rolls back (modelling issue #89's lock-timeout -> rollback step), **then** no platform template row survives, a BR create 422s with `detail.code == "br_template_unavailable"`, and `GET .../template-status` reports `{"active": false}`.
- Test: `test_seed_lost_to_rollback_then_migrated_leaves_no_template`.

### AC-90-202 - the next bootstrap seeds and activates it [BE][T]
- **Given** the emptied state, **when** `install()` runs again and commits (the owner's actual workaround, #90 comment 1), **then** `template-status` reports `{"active": true}` and a BR create stamps `templateVersion == 1`.
- Test: `test_next_bootstrap_seeds_and_activates`.

### AC-90-203 - the seed repairs a half-seeded state (never just insert-if-missing) [BE][T]
- **Given** a template row with a NULL pointer, a dangling pointer, or zero version rows, **when** `seed_br_template` runs, **then** it creates v1 if missing and points `active_version_id` at the highest existing version - a BR create then succeeds (201).
- Test: `test_seed_repairs_half_state` (parametrized: `null_pointer`, `dangling_pointer`, `no_versions`).

### AC-90-204 - idempotent, and NEVER moves a VALID pointer (incl. an older one) [BE][T]
- **Given** an operator activates v2 (the highest version at the time), **when** the seed runs twice, **then** v2 stays active and v1's `doc_json` is byte-identical.
- **Given** a v3 is then added and the operator moves the pointer BACK to v1 (a valid but OLDER version while v2/v3 exist - review round 2 strengthening), **when** the seed runs twice, **then** the pointer stays v1 (never "helpfully" repointed to the highest version).
- Test: `test_seed_is_idempotent_and_keeps_operator_active_version`.

### AC-90-205 - `template-status` is permission-gated [BE][T]
- **Given** no token, **then** 401. **Given** a token lacking `ideation.business_requirements.read`, **then** 403.
- Test: `test_template_status_requires_read_permission`.

### AC-90-210 - the create dialog explains an inactive template [FE][T]
- **Given** `templateStatus().active === false` (or a create 422 carrying `detail.code === 'br_template_unavailable'`), **then** the dialog renders an Alert ("No active requirement template" / "Ask an administrator to restore the Business Requirement template.") and disables "Create draft". Per Q1 ruling: NO link (no admin page exists - BL-SS-278 filed).
- Test: `br-create-dialog.test.tsx` describe block "AC-90-210 no active template".

### AC-90-211 - the promote-to-BR toast carries the same copy [FE][T]
- **Given** a promote 422s with `br_template_unavailable`, **then** the toast shows the same "ask an administrator" sentence; any other error keeps the generic failure message.
- Test: `promote-to-br.test.ts` describe block "AC-90-211 br_template_unavailable toast".

---

## W3 - a test idea may promote to a TEST Business Requirement (AC-90-301..313)

*(Owner ruling 26 Sep 2026 ~12:50Z: INVERTS the prior refusal - a test idea now promotes successfully, into a TEST BR.)*

### AC-90-301 - promoting a test idea creates a TEST BR [BE][T]
- **Given** a promote (`ideaIds`) carrying only test ideas, **then** the create succeeds (201) and the BR carries `isTest: true`.
- Test: `test_promote_test_idea_creates_test_br` (inverts and replaces the old `test_promote_refuses_test_idea`).

### AC-90-302 - a test BR is excluded from the default list, `includeTest=true` brings it back [BE][T]
- **Given** a real BR and a test BR both exist, **then** the default `GET /ideation/business-requirements` excludes the test one; `?includeTest=true` includes both.
- Test: `test_test_br_excluded_from_list_unless_include_test`.

### AC-90-303 - a mixed test+real promote is refused with the EXACT message, no BR left behind [BE][T]
- **Given** `ideaIds` mixing a real and a test idea, **then** the create 422s with `detail == "Test and real ideas cannot be promoted together."` (proving `_derive_lane` itself catches it, not `_link_ideas`' different message) and NO BR - test or real - exists afterward (`?includeTest=true` list is empty).
- Test: `test_mixed_test_and_real_promote_refused` (strengthened, review round 2).

### AC-90-304 - the lane invariant is bidirectional [BE][T]
- **Given** an existing test BR, **when** a REAL idea is linked to it, **then** 422 ("A real idea cannot be linked to a test Business Requirement."). The reverse direction (`test_link_refuses_test_idea`, a test idea onto a real BR) is unchanged and still valid.
- Test: `test_real_idea_cannot_link_to_test_br` + `test_link_refuses_test_idea` (unchanged).

### AC-90-305 - a client-sent `isTest` is ignored on a manual create [BE][T]
- **Given** a manual create (no `ideaIds`) with a body carrying `isTest: true`, **then** the created BR's `isTest` is `false` - the lane is ALWAYS server-derived, never client input.
- Test: `test_client_is_test_ignored_on_manual_create`.

### AC-90-306 - the status-engine integrity hooks still count test BRs [BE][T]
- **Given** a test BR sitting on a status, **then** `br_count_records` for that status includes it - a status holding test BRs must still be blocked from deletion.
- Test: `test_test_br_counted_by_status_engine`.

### AC-90-307 - migration 0011 chains onto 0010 [BE][T]
- **Given** the module's migration chain, **then** `0011_ideation_br_is_test.py` exists with `down_revision == "0010_ideation_intake_contract"` and `len(revision) <= 32`.
- Test: `test_migration_0011_chains_onto_0010`.

### AC-90-310 - the TEST badge on list rows [FE][T]
- **Given** an `isTest` BR/idea row, **then** the title cell shows a `TEST` badge (same badge component as the ideas list); a real row shows none.
- Test: `use-br-list-config.test.tsx` describe block "AC-90-310 title column TEST badge" + `use-ideas-list-config.test.tsx` "Idea column TEST badge".

### AC-90-311 - promote is disabled only for a MIXED selection [FE][T]
- **Given** an all-test selection, **then** Promote stays enabled; **given** a mixed test+real selection, **then** Promote is disabled (plus the existing mixed-product rule).
- Test: `use-ideas-list-config.test.tsx` describe block "useIdeasListConfig - promote-br action".

### AC-90-312 - the BR list gains `includeTest` [FE][T]
- **Given** `useBusinessRequirements()`, **then** it defaults `includeTest` to `false` and `setIncludeTest(true)` reloads the list with `includeTest: true`.
- Test: `hooks/use-business-requirements.test.ts` describe block "AC-90-312 includeTest passthrough".

### AC-90-313 - the BR detail page labels a test BR "Test" [FE][T]
- **Given** a test BR's detail page, **then** the subtitle prepends a TEST badge and the record pager (`fetchRecordAt`) passes `includeTest: true` so the pager can find the BR itself.
- Test: `use-br-form.test.tsx` describe blocks "AC-90-313 TEST badge on the subtitle" and "the record pager passes includeTest".

---

## E2E (real-click, agent-browser only, 375px + 1280px)

### AC-90-E01 - W1 the public page journey [E2E]
- **Given** a captured idea's "Track it here" link, **then** opening it shows the full page; moving the idea New -> Triaged on the board and reloading the link shows the timeline advance; an unknown token shows the uniform not-found state.

### AC-90-E02 - W2 the template-inactive -> restored journey [E2E]
- **Given** the platform template rows deleted on the lane DB, **then** "New business requirement" shows the Alert + disabled Create; running `python -m scripts.bootstrap_db` on the lane restores it and the dialog succeeds.

### AC-90-E03 - W3 the test-idea -> test-BR journey [E2E]
- **Given** a test idea, **then** "Promote to BR" succeeds and lands on the BR with a TEST badge; the BR is absent from the default Business Requirements list and present with "Show test requirements" on.

Evidence: `documentation/plans/ideation/90-evidence/` (README + `ev-01`..`ev-15` screenshots) - captured against an EARLIER revision of this branch (head `65fbabe3`, before the review-round-2 backend fixes). **Pending re-run** against the current head to confirm the round-2 fixes (B2 first-name guard, the tenant-scoped Status lookup, the hardening headers) show correctly live - the tester owns this re-run.
