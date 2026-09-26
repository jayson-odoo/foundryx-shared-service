# Issue #90 - Public idea page, BR template seed repair, test idea -> test BR · Test Execution Report

**Branch:** `fix/public-idea-page-and-br-template` (worktree `foundryx-shared-service-ideapage`)
**Contract:** `ideation-public-idea-page-br-template-acceptance-criteria.md`
**Commits covered:** `ff826692` (RED, tester) -> `ad9ae668` (BE green) -> `6460ade3`/`710e88c8` (coordinator follow-up: strengthened AC-90-204, cherry-picked the `test_s13_flip_baseline_seed.py` TTL fix) -> review-round-2 backend fixes (this report's HEAD)
**Scope of this report:** backend fully re-run by the backend coder; frontend rows reflect the FE coder's committed test files as of the tester's S4 evidence run (`documentation/plans/ideation/90-evidence/`) - a frontend coder is concurrently working uncommitted in `service_frontend/`, so FE verdicts here are carried forward, not re-executed, by this backend-only round.

---

## 1. Automated suite results (ACTUAL output, this round)

### Backend - targeted ideation files
```
.venv/bin/python -m pytest tests/test_ideation_public_status.py tests/test_ideation_br_template_seed.py tests/test_ideation_br.py -q
```
-> **69 passed** (33 `test_ideation_public_status.py` + 7 `test_ideation_br_template_seed.py` + 29 `test_ideation_br.py`) in ~16s.

Breakdown after review round 2's additions: `test_ideation_public_status.py` grew from 27 to 33 (the phone-guard test became a 5-case parametrize, +4; two new tests: `test_public_status_hardening_headers`, `test_status_lookup_is_tenant_scoped`, +2; net +6). `test_ideation_br_template_seed.py` stayed at 7 (AC-90-204 gained assertions inside the same test, no new test). `test_ideation_br.py` stayed at 29 (AC-90-303 gained assertions inside the same test).

### Backend - full ideation suite
```
.venv/bin/python -m pytest tests/ -k ideation -q
```
-> **323 passed, 5309 deselected** (up from 317 in the prior round by exactly the 6 net-new tests added to `test_ideation_public_status.py` this round).

### Backend - `test_s13_flip_baseline_seed.py` (coordinator follow-up 2)
```
.venv/bin/python -m pytest tests/test_s13_flip_baseline_seed.py -q
```
-> **13 passed** (was 11 failed / 2 passed before cherry-picking `bff0fbf8` - a pre-existing real-clock 24h TTL time bomb, unrelated to issue #90, now fixed).

### Backend - full suite (prior round; not re-run in full this round since only `service_backend/modules/ideation` + 2 test files changed)
Prior full run (`-n auto --dist loadfile`): **5596 passed, 11 failed** (all in `test_s13_flip_baseline_seed.py`, confirmed pre-existing at `ff826692` before any of this branch's code), **1 skipped**. The 11 failures are now fixed by the cherry-pick (§ above) - not re-run at full scale this round to avoid disturbing the reserved `:8015`/`:3015` lane per the coordinator's instruction (pytest only, no lane restart).

### Frontend
Not re-run this round (backend-only per the coordinator's brief; a frontend coder is concurrently uncommitted in `service_frontend/`). The file list below reflects what existed at the tester's S4 evidence run and is unchanged by this round's backend-only diff.

---

## 2. AC-by-AC verdicts

### W1 - public idea page

| AC | Title | Verdict | Evidence |
|----|-------|---------|----------|
| AC-90-101 | Full page fields, real values | **PASS** | `test_public_status_returns_page_fields` |
| AC-90-102 | Timeline order/states, `sort_order`-driven | **PASS** | `test_public_timeline_order_and_states` (incl. the sort_order-swap proof) |
| AC-90-103 | Off-ramp timeline stays truthfully short | **PASS** | `test_public_timeline_off_ramp` |
| AC-90-104 | Exact key set, no PII beyond first name | **PASS** | `test_public_status_exact_key_set_and_no_pii` |
| AC-90-105 | First name only, first token | **PASS** | `test_first_name_only` |
| AC-90-106 | First-name guard never leaks a fragment | **PASS (review round 2 fix)** | `test_first_name_never_a_phone` parametrized, 5/5 green incl. the 4 new probes (`"+60 12-345 6789"`, `"0123 456 789"`, fullwidth-`@` email, `"Ali_0123"`). Kill-tested: reverting `_first_name` to the old token-only check reproduces exactly the 4 new-probe failures (confirmed, then restored - `diff` clean). |
| AC-90-107 | Product/Contact lookups tenant-scoped | **PASS** | `test_product_and_contact_lookups_tenant_scoped`. Kill-tested (this round): removing the `tenant_id` filter on the Product query reproduces the exact failure (`'Other Tenant Product' is None` assertion fails) - confirmed, restored. |
| AC-90-107b | Current-Status lookup tenant-scoped (review round 2 nit) | **PASS (new)** | `test_status_lookup_is_tenant_scoped`. Kill-tested: reverting the query to `Status.id == idea.status_id` (no tenant filter) reproduces `200 != 404` - confirmed, restored. |
| AC-90-108 | Next-step copy + trait-flag fallback | **PASS** | `test_next_step_copy_and_fallback` |
| AC-90-109 | `Cache-Control: no-store` | **PASS** | `test_public_status_no_store_header` |
| AC-90-109b | Hardening headers (review round 2, optional) | **PASS (new)** | `test_public_status_hardening_headers`. Kill-tested: removing the two `response.headers[...]` lines reproduces `None == 'noindex'` - confirmed, restored. |
| AC-90-110 | Full page renders (FE) | **PASS (carried forward)** | `app/(public)/public/ideas/[token]/page.test.tsx`; live evidence `ev-01`..`ev-04`, `ev-07`/`ev-08` |
| AC-90-111 | Timeline renders client-side | **PASS (carried forward)** | `page.test.tsx`; evidence `ev-03`/`ev-04` (advancing timeline) |
| AC-90-112 | White-label header/footer mark (Q2) | **PASS (carried forward)** | `brand-mark.test.tsx` (regression, extracted unchanged) + `public-branded-shell.test.tsx` |

### W2 - BR template seed

| AC | Title | Verdict | Evidence |
|----|-------|---------|----------|
| AC-90-201 | #89 sequence leaves no template | **PASS** | `test_seed_lost_to_rollback_then_migrated_leaves_no_template` |
| AC-90-202 | Next bootstrap seeds + activates | **PASS** | `test_next_bootstrap_seeds_and_activates` |
| AC-90-203 | Seed repairs a half-state (3 kinds) | **PASS** | `test_seed_repairs_half_state[null_pointer\|dangling_pointer\|no_versions]`. Kill-tested: removing repair step 3 (the pointer fix) reproduces the exact 4 failures (202 + the 3 parametrized 203 cases) - confirmed, restored. |
| AC-90-204 | Idempotent, never moves a VALID pointer (incl. older) | **PASS (strengthened this round)** | `test_seed_is_idempotent_and_keeps_operator_active_version`, now covers BOTH "operator activates the highest version" (original) AND "operator reactivates an OLDER v1 while v2/v3 exist" (review round 2 - the original case alone could not distinguish "only repoint an invalid pointer" from a regressed "always repoint to highest" mutant, since both landed on the same id there). Kill-tested TWICE: (1) original mutant - "always repoint to highest" - now correctly fails on the NEW older-pointer assertion (`v3's id != v1's id`), confirmed then restored; (2) same mutant tested BEFORE the strengthening also confirmed to previously slip through, documenting why the strengthening was needed. |
| AC-90-205 | `template-status` permission-gated | **PASS** | `test_template_status_requires_read_permission` |
| AC-90-210 | Dialog explains inactive template (FE) | **PASS (carried forward)** | `br-create-dialog.test.tsx`; evidence `ev-11`/`ev-12` |
| AC-90-211 | Promote toast copy (FE) | **PASS (carried forward)** | `promote-to-br.test.ts` |

### W3 - test idea -> test BR

| AC | Title | Verdict | Evidence |
|----|-------|---------|----------|
| AC-90-301 | Promote a test idea creates a TEST BR | **PASS** | `test_promote_test_idea_creates_test_br` |
| AC-90-302 | Test BR excluded by default, `includeTest` restores | **PASS** | `test_test_br_excluded_from_list_unless_include_test`. Kill-tested: removing the `is_test.is_(False)` filter reproduces the exact failure (test BR id present in the default list) - confirmed, restored. |
| AC-90-303 | Mixed promote refused, EXACT message, no BR left | **PASS (strengthened this round)** | `test_mixed_test_and_real_promote_refused`, now asserts `detail == "Test and real ideas cannot be promoted together."` (not just status 422) and that `?includeTest=true` returns `[]` afterward. Kill-tested: removing `_derive_lane`'s own mixed-check makes `_link_ideas`' DIFFERENT message surface instead (`"A test idea cannot be linked to a real Business Requirement."`) - the strengthened assertion now correctly catches this (previously it passed for the wrong reason); confirmed, restored. |
| AC-90-304 | Lane invariant is bidirectional | **PASS** | `test_real_idea_cannot_link_to_test_br` + `test_link_refuses_test_idea` (unchanged). Kill-tested: removing the `bool(idea.is_test) != bool(br.is_test)` check reproduces both failures (200 instead of 422) - confirmed, restored. |
| AC-90-305 | Client `isTest` ignored on manual create | **PASS** | `test_client_is_test_ignored_on_manual_create` |
| AC-90-306 | Status-engine hooks still count test BRs | **PASS (no code change needed)** | `test_test_br_counted_by_status_engine` - `br_count_records` was already tenant-scoped only, never filtered `is_test` |
| AC-90-307 | Migration 0011 chains onto 0010 | **PASS** | `test_migration_0011_chains_onto_0010` |
| AC-90-310 | TEST badge on list rows (FE) | **PASS (carried forward)** | `use-br-list-config.test.tsx`, `use-ideas-list-config.test.tsx`; evidence `ev-13`/`ev-15` |
| AC-90-311 | Promote disabled only for mixed selection (FE) | **PASS (carried forward)** | `use-ideas-list-config.test.tsx`; evidence `ev-13`, `ev-14` |
| AC-90-312 | BR list gains `includeTest` (FE) | **PASS (carried forward)** | `use-business-requirements.test.ts` |
| AC-90-313 | BR detail page labels a test BR (FE) | **PASS (carried forward)** | `use-br-form.test.tsx`; evidence `ev-14` |

### E2E

| AC | Title | Verdict | Evidence |
|----|-------|---------|----------|
| AC-90-E01 | W1 public page journey | **PENDING RE-RUN** | `90-evidence/README.md` + `ev-01`..`ev-10`, captured at head `65fbabe3` (BEFORE the review-round-2 backend fixes: the first-name guard hardening, the tenant-scoped Status lookup, the hardening headers). The tester owns re-running this against the current head. |
| AC-90-E02 | W2 template-inactive journey | **PENDING RE-RUN** | `ev-11`/`ev-12`, same head caveat as above (W2's `seed_br_template` behaviour is unchanged by review round 2, so this evidence is likely still accurate, but not re-confirmed) |
| AC-90-E03 | W3 test-idea journey | **PENDING RE-RUN** | `ev-13`/`ev-14`/`ev-15`, same head caveat (W3's lane logic gained the AC-90-303 message/no-BR-left assertions this round, behaviour was already correct, evidence likely still accurate but not re-confirmed) |

---

## 3. Findings from the S4 evidence run, disposition

1. **Operator-captured ideas never get `idea_number`/`status_token`** (`services/actions.py`'s `create_operator`) - filed as **BL-SS-280** this round, per the coordinator's instruction. Not fixed in this PR (product decision needed: should an operator-authored idea be shareable via a track link at all).
2. **The "No active requirement template" Alert has no link** - this is Q1's ruling (no admin page exists), not a defect; **BL-SS-278** tracks building the admin page this would eventually link to.

## 4. Disclosure added this round

`BusinessRequirementService.set_status`'s docstring and the `BusinessRequirement.is_test` column comment (`modules/ideation/models.py`) now explicitly state: **a status transition on a test BR still fires real same-transaction notifications and any `entity.status_changed` workflow trigger** - `is_test` only ever gates list/count visibility and the promote/link lane, never the status-engine's notification/workflow side effects. No code behaviour changed (this was already true); this is a documentation-only disclosure requested by the review.

## 5. Kill-test summary (every repair this round + the prior round, all confirmed then restored - `diff` clean against the committed source after every restore)

| Fix | Kill mutation | Result before fix / after removing it |
|---|---|---|
| B2 first-name guard (NFKC + whole-string + first-token rules) | Revert to old token-only check | 4/5 parametrized cases fail (only the original phone-contact + Jayson-Teh-style cases still pass) |
| Tenant-scoped current-Status lookup | Drop the `tenant_id` filter | `test_status_lookup_is_tenant_scoped` fails (200 instead of 404) |
| Hardening headers | Remove both `response.headers[...]` lines | `test_public_status_hardening_headers` fails |
| AC-90-204 strengthened (older valid pointer) | "Always repoint to highest" mutant | Now fails (previously slipped through the original, weaker assertion) |
| AC-90-303 strengthened (exact message + no BR left) | Remove `_derive_lane`'s own mixed-check | Now fails on the message mismatch (previously passed for the wrong reason via `_link_ideas`) |
| (prior round) seed repair step 3 | Remove the pointer-repair branch | AC-90-202 + all 3 AC-90-203 cases fail |
| (prior round) `br_template_unavailable` code | Drop the `code` key from the 422 detail | AC-90-201 fails (`TypeError` on `detail["code"]`) |
| (prior round) `_link_ideas` bidirectional lane check | Remove the lane-mismatch check | AC-90-304 + `test_link_refuses_test_idea` both fail (200 instead of 422) |
| (prior round) `list()`'s `include_test` filter | Remove the `is_test.is_(False)` filter | AC-90-302 fails (test BR id present in the default list) |
| (prior round) Product/Contact tenant scoping | Remove the `tenant_id` filter on the Product query | AC-90-107 fails |
| (prior round) first-name phone guard (original) | Remove the guard entirely | `test_first_name_never_a_phone`'s original phone-contact case fails |
