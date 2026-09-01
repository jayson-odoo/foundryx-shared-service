# Ideation Phase B-i - Slice 1 (Core AI foundation) · Test Execution Report

**Under test:** the UNCOMMITTED S1 slice on `feat/ideation-phase-b-idea-to-br`
(worktree `.claude/worktrees/ideation-phase-b`) - the new core `app/ai/`
subsystem: `type='llm'` connections (anthropic/openai/gemini), agent registry
(agent ⇄ many skills), versioned skill registry (immutable version + movable
active label), traces/spans + retention sweep, deterministic dev-stub adapter,
and `/ai/{agents,skills,traces}` + `/settings/ai/*` on the Resource shell.

**Contract:** `ideation-phase-b-idea-to-br-acceptance-criteria.md` - AC-BI-01..14
plus AC-BI-03b, AC-BI-06b (all Slice 1). Slices 2-4 (BR entity, grill engine,
Idea→BR) are out of scope for this report.

**Tester:** independent QA. Application code was NOT modified. No test needed to
be added - every target AC already carries focused coverage (see §4).

**Date:** 2026-07-22

---

## 1. Command output (ACTUAL, not "should pass")

| Suite | Command (from `service_backend` unless noted) | Result |
|---|---|---|
| **Backend - AI core** | `.venv/bin/python -m pytest tests/test_ai_core.py -q` | **78 passed** in 43.7s |
| **Backend - full** | `.venv/bin/python -m pytest -q` | **1 failed, 1381 passed, 18 deselected** in 1103s (18m23s) |
| **Backend - live (opt-in)** | `set -a; . ./.env; set +a; .venv/bin/python -m pytest -m live -q -rs` | **6 passed (gemini), 12 skipped (anthropic+openai), 1382 deselected** in 4.1s |
| **Frontend - full** | `npm test` (in `service_frontend`) | **861 passed / 112 files** in 38s |
| **Frontend - AI-specific** | `npx vitest run services/ai-service.test.ts hooks/use-ai-models.test.ts hooks/use-ai-prerequisite.test.ts` | **20 passed / 3 files** in 1.8s |

### 1.1 The one full-suite failure is PRE-EXISTING and OUT OF SCOPE

```
FAILED tests/test_cluster_d_slice3_migration.py::test_module_migration_revision_ids_fit_alembic_column
AssertionError: Module migration revision ids exceed Alembic's VARCHAR(32) version
column (un-runnable on Postgres):
  [('ideation', '0003_ideation_idea_submitter_name.py',  '0003_ideation_idea_submitter_name',  33),
   ('ideation', '0004_ideation_idea_segregated_fields.py','0004_ideation_idea_segregated_fields', 36)]
```

- This is a guard test that scans **module** migrations (`service_backend/modules/*/alembic/versions/`).
- The two offending revision ids belong to the **`ideation` MODULE** (Phase A capture spine), committed **2026-07-19 in `98f6f37`** - they are tracked/committed and appear in **no part of the uncommitted S1 diff** (`git status --short` clean for those files).
- The S1 AI slice's OWN migrations are **core** (not module) and correctly ≤32 chars: `ai_core_s1b` (11) and `ai_perms_s1b_grant_sweep` (24). `alembic heads` shows a single clean head, no cycle.
- **Verdict:** NOT a regression from S1. It is, however, a genuine pre-existing Phase-A deploy bug - on real Postgres `run_module_migrations('ideation')` will 500 with `StringDataRightTruncation` at the version-stamp UPDATE (invisible to pytest because conftest uses `create_all`, not Alembic). **Kick to the coder** to shorten `0003`/`0004` ideation revision ids (rename + backfill the live `alembic_version_ideation` stamp). Maps to no AC-BI-* id.

### 1.2 Live-suite behaviour (AC-BI-12/13 fixture control)

Confirmed the routine suite runs OFFLINE: `conftest.py` blanks `platform_llm_api_key`
+ `grill_api_key`, so with no platform LLM connection seeded the **stub adapter
answers** - zero key, zero network. With `-m live` and the Gemini key loaded from
`.env` (`GRILL_API_KEY`), the **6 Gemini tests ran against the real API and
passed**; the 6 Anthropic + 6 OpenAI tests **skipped cleanly** (`no ANTHROPIC_API_KEY
… skipping`, `no OPENAI_API_KEY … skipping`). The key value was never printed or
logged at any point.

---

## 2. Live verify-stack smoke (:8002 backend / :3001 frontend)

E2E is deferred to S4 per the contract (no user journey yet in S1). A light smoke
against the running verify stack (throwaway DB `foundryx_ideation_verify`) confirms
the S1 surfaces render REAL data, not a mock:

- `GET /health` → **200**; `GET /ai/agents` unauthenticated → **401** (endpoint exists, gated).
- Logged in as `demo@example.com` (default tenant Admin):
  - `GET /ai/agents/prerequisite` → `hasConnection: true` with **two** LLM connections - platform `Platform Google Gemini` (UNVERIFIED) **and** tenant `Gemini (verify)` (ACTIVE). This is AC-BI-03b (multiple LLM connections coexist) + AC-BI-11 (tenant-before-platform) observed live.
  - `GET /ai/agents` → agents `["Gemini", "Multi 1784676965"]` (real rows).
  - `GET /ai/skills` → 3 skills.

The `demo@example.com` Admin already holds the AI perms (grant sweep applied on the
verify DB). Responsive 375px/1280px verification NOT performed - deferred to S4's
real E2E.

---

## 3. AC-by-AC results

| AC | Verdict | Evidence |
|---|---|---|
| **AC-BI-01** - `LLMProvider` protocol; `LLMResult` text XOR structured + normalized usage; adapter owns structured-output dialect | **PASS** | `test_llm_result_enforces_text_xor_structured` (both-set/neither-set raise), `test_gemini_schema_downconversion_strips_unsupported_keys`, provider-surface tests; live `test_live_text_completion_round_trips` asserts normalized `tokens_in/out > 0` |
| **AC-BI-02** - 3 adapters registered `type='llm'` with fields/test/models/complete; appear as catalog cards on the existing Resource shell | **PASS** | `test_llm_provider_registered_with_required_surface` (×3), `test_llm_provider_marks_api_key_secret` (×3). Catalog-card rendering reuses the existing integrations Resource shell (no new UI) - FE card display not separately E2E'd (S4) |
| **AC-BI-03** - Fernet write-only; never echoed; blank-to-keep; FERNET loud at seed; config PATCH merges | **PASS** | `test_llm_credentials_are_never_echoed`, `test_blank_credential_on_update_keeps_the_stored_key`, `test_config_patch_merges_rather_than_wipes`, `test_platform_llm_seed_is_idempotent_and_refuses_without_fernet_key` |
| **AC-BI-03b** - `llm` carved out of `uq_connection_tenant_type`; two active LLM coexist; two active same-provider rejected; storage one-per-type unchanged; deterministic prereq pick | **PASS** | `test_two_active_llm_connections_coexist`, `test_llm_connections_do_not_block_each_other_via_api`, `test_two_active_same_provider_llm_connections_rejected`, `test_storage_one_per_type_invariant_unchanged`, `test_resolution_is_deterministic_across_several_llm_rows`. Model `EXEMPT_FROM_ONE_PER_TYPE=('payment','llm')` shared by service (`in EXEMPT…`) + migration index predicate; coexistence observed live |
| **AC-BI-04** - `test()` = model-list probe; clean error, no traceback/key echo; UNVERIFIED until first pass | **PASS** | `test_llm_provider_test_reports_clean_error_without_key` (×3), live `test_live_test_reports_ok` + `test_live_bad_key_is_rejected_cleanly`; UNVERIFIED status visible in the live prereq payload |
| **AC-BI-05** - model picker SearchSelect: live list, static fallback, pinned id fails loudly | **PASS** | `test_llm_provider_has_static_model_fallback` (×3), `test_models_endpoint_falls_back_to_static_list_on_provider_failure` (`isLive:false`, static served), live `test_live_retired_model_fails_loudly`; FE `hooks/use-ai-models.test.ts` (5) |
| **AC-BI-06** - agent registry, no own credential column, Resource shell, missing-prerequisite warning | **PASS** | `test_agent_holds_no_credential_of_its_own`, `test_agent_without_connection_surfaces_warning`, `test_agent_warns_when_its_connection_is_deleted`, `test_agent_rejects_a_non_llm_connection`, `test_agent_duplicate_name_rejected`, `test_agent_temperature_bounds_enforced` |
| **AC-BI-06b** - agent equips MANY skills (`ai_agent_skills` join); MultiSelect; `skillIds[]`; foreign-tenant refused / platform allowed | **PASS** | `test_agent_equips_zero_one_and_many_skills`, `test_agent_update_replaces_the_equipped_set`, `test_agent_equip_dedupes_repeated_skill_ids`, `test_agent_equip_allows_platform_tier_skill`, `test_agent_equip_refuses_foreign_tenant_skill` (422), `test_agent_skill_set_is_tenant_scoped_on_read`, `test_skill_delete_blocked_while_equipped` (409) |
| **AC-BI-07** - versioned skill artifact; edit mints immutable version + moves label; rollback = label move; gated manage | **PASS** | `test_skill_edit_mints_new_version_and_moves_label`, `test_skill_rollback_is_a_label_move_not_a_copy`, `test_skill_unchanged_body_does_not_mint_a_version`, `test_skill_rollback_refuses_foreign_version_id`, `test_tenant_edit_of_platform_skill_forks_rather_than_mutating` |
| **AC-BI-08** - prompt composition substitution-only; eval-shaped bodies inert (anti-SSTI) | **PASS** | `test_compose_substitutes_tokens`, `test_compose_never_evaluates_eval_shaped_bodies` (`7*7` never 49; `{% for %}` body appears once, verbatim), `test_compose_missing_token_collapses_to_empty` |
| **AC-BI-09** - traces + spans; OTel GenAI naming; flat ordered step list | **PASS** | `test_trace_and_spans_written_on_completion` (trace usage = span roll-up), `test_failed_completion_still_writes_an_error_trace`, `test_trace_detail_returns_ordered_flat_step_list` (`dottedOrder ["1","2","3"]`) |
| **AC-BI-10** - retention sweep (short `ok` / long `error`+`flagged`, failure-isolated in beat); payload size-caps with truncation marked | **PASS** | `test_retention_sweep_prunes_ok_but_keeps_error_and_flagged` (cascade, no orphan spans), `test_retention_sweep_is_wired_into_the_beat_task`, `test_span_payload_is_capped_and_truncation_marked`, `test_cap_payload_does_not_mutate_the_caller_object`, `test_cap_payload_handles_nested_structures`, `test_long_completion_is_capped_when_traced` |
| **AC-BI-11** - resolution order tenant→platform; neither → clear missing-prereq warning, action unavailable | **PASS** | `test_resolution_prefers_tenant_connection_over_platform`, `test_resolution_falls_back_to_platform_connection`, `test_no_connection_anywhere_reports_missing_prerequisite`, `test_prerequisite_endpoint_reports_absence` / `…lists_llm_connections`; observed live (tenant Gemini preferred over platform) |
| **AC-BI-12** - deterministic stub adapter (no key/cost/network); fixture-driven (script invalid/missing-field extraction); only HTTP faked | **PASS** | `test_stub_is_deterministic_for_identical_input`, `test_stub_fixture_can_declare_an_invalid_extraction` (missing `success_metric`), `test_stub_answers_when_no_connection_is_configured` (`provider=="stub"`), `test_stub_queue_drains_then_falls_back`; `conftest.py` blanks both platform keys; `AiClient.resolve_for_agent` routes to `stub_provider` when no connection / dev creds - engine/validation/RBAC still run for real |
| **AC-BI-13** - live tests opt-in; skipped by default | **PASS** | `pytest.ini` `addopts = -m "not live"`; live run = 6 gemini passed, 12 anthropic/openai **skipped cleanly** with per-provider reason; routine run deselects all 18 |
| **AC-BI-14** - `ai_agents.read/.manage` (agents+skills) + separate `ai_traces.read`; implied-read; connections need no new perm; grant sweep for existing tenants | **PASS** | `test_ai_permissions_declared_in_core_csv`, `test_trace_read_is_separable_from_agent_manage`, `test_manage_required_to_write_agents` (403), `test_implied_read_normalization_for_ai_manage`; migration `ai_perms_s1b_grant_sweep` inserts perms + grants to every non-platform Admin idempotently |

**Tally: 16 / 16 target ACs PASS · 0 FAIL · 0 DEFERRED** (S1 scope).

---

## 4. Coverage-gap assessment

Instructed to add a focused test for any AC lacking coverage, with priority to the
carve-out, agent-skills many-many, key-never-echoed, skill immutability/rollback,
substitution-only prompt, and trace retention/payload-cap.

**No test was added - every priority item is already covered**, and covered well:

- **AC-BI-03b carve-out** - coexist / same-provider-reject / storage-unchanged / deterministic-pick all asserted; the exempt-set constant is shared between the service 409 and the DB index predicate (no drift).
- **AC-BI-06b many-many** - 0/1/N equip, replace-set, dedupe, platform-allow, foreign-tenant-422, tenant-scoped read, delete-while-equipped-409 all asserted.
- **AC-BI-03 key-never-echoed** - create/get/list all scrubbed of the raw key; blank-to-keep + config-merge asserted.
- **AC-BI-07 immutability/rollback** - new-version-on-edit, prior-row-untouched, rollback-is-label-move (no new version), no-op-save mints nothing, foreign-version-id 404.
- **AC-BI-08 substitution-only** - a hostile Jinja/`${}`/subclass-walk body survives verbatim and nothing evaluates.
- **AC-BI-10 retention + caps** - status-windowed prune with span cascade + beat-wiring, per-string + total payload caps, no-mutate + nested, long-completion capped when traced.

The `app/ai/` implementation (`client.py`, `stub.py`, `tracing.py`, `retention.py`,
`prompt.py`) was read directly and matches what the tests assert - the stub-routing
decision (`resolve_for_agent` → `is_dev` → `stub_provider`) is exactly the
omnichannel `_is_dev` pattern AC-BI-12 requires, and `cap_payload` returns a fresh
structure (no in-place JSON mutation).

---

## 5. Findings / remarks

1. **PRE-EXISTING FAIL (not S1) - kick to coder.** `ideation` module migration
   revision ids `0003_ideation_idea_submitter_name` (33) and
   `0004_ideation_idea_segregated_fields` (36) exceed Alembic's `VARCHAR(32)` →
   `run_module_migrations('ideation')` will 500 on real Postgres. Committed in
   Phase A `98f6f37` (2026-07-19); orthogonal to the AI slice. Shorten both ids
   (+ backfill the live stamp). Detected only because conftest is `create_all`.

2. **Deprecation noise (cosmetic).** `ai_service.py` raises
   `HTTP_422_UNPROCESSABLE_ENTITY` - Starlette now prefers
   `HTTP_422_UNPROCESSABLE_CONTENT`. Warning only; consistent with the rest of the
   codebase; not a defect. Optional cleanup.

3. **Migration/model coupling (minor, currently consistent).** The one-per-type
   exempt set exists in two places - `EXEMPT_FROM_ONE_PER_TYPE=('payment','llm')`
   in `connection.py` and the literal `type NOT IN ('payment','llm')` in the
   migration's index `postgresql_where`. They agree today; a future edit must
   change both (the code comment already flags this).

4. **Slice-1-only reach.** `ai_conversations` / `ai_messages` tables + the
   `GrillDefinition` are shipped/created but unfilled - that is by design (S3
   fills them; S1 only lands the schema so the grill adds no later core migration).
   Not evaluated here.

5. **Deferred to S4:** full real-click E2E (idea→promoted BR), 375px/1280px
   responsive verification, and the real-model manual live-verification gate
   (AC-BI-37). S1 has no user journey to click.

**Bottom line:** all 16 Slice-1 ACs pass across backend (78 AI-core + full-suite AI
coverage), live Gemini (6 passed, others skip cleanly), and frontend (20 AI-specific
+ 861 full). The lone full-suite red is a pre-existing Phase-A ideation-module
migration-id bug, not a regression from this slice.
