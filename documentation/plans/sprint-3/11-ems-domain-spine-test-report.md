# Sprint 3 · Plan 11 - EMS Domain Spine · Test Execution Report

**Branch:** `sprint-3/11-ems-domain-spine` · **Date:** 2026-06-16

Validates `11-ems-domain-spine-acceptance-criteria.md` (AC-11-01 … AC-11-19).

---

## Summary

| Layer | Result |
|-------|--------|
| Backend (`tests/test_ems_spine.py`) | **8 passed** |
| Backend full suite (regression) | **804 passed** (0 failures) |
| ems per-module Alembic on LIVE Postgres | **verified** (fresh upgrade → app_ems + 7 tables) |
| EMS vertical live smoke (curl → Postgres) | **PASS** (type→template→project→profile→participant) |
| EMS frontend live (Playwright MCP) | **PASS** (/ems/events renders, terminology, live data) |

---

## Backend tests (`tests/test_ems_spine.py`, 8)

| Test | AC |
|------|----|
| `test_module_install_grants_perms` | AC-11-18 |
| `test_terminology_event_label` | AC-11-11 (project→Event, participant→Participant) |
| `test_profile_crud_dedup_and_tier1_transition` | AC-11-02 (lowercase email, 409 dedup, patch, soft-delete) |
| `test_profile_tier1_transition_via_graph` | AC-11-07 (tier-1 Active→Suspended via status_machine) |
| `test_create_from_template_copies_eligibility_graph` | AC-11-03/04 (copy_scope → distinct 5-status project graph) |
| `test_participant_add_uniqueness_and_tier2_transition` | AC-11-05/07 (one-per-(profile,project) 409; tier-2 scoped transition) |
| `test_participant_bulk_import_find_or_create` | AC-11-05/17 (project-scoped import, find-or-create profile via F8) |
| `test_tenant_isolation` | AC-11-09 (cross-tenant 403/404; module-gated) |

## Live verification (Postgres)

- **ems per-module Alembic**: fresh DB → `upgrade` created `app_ems` schema + 7 spine
  tables + `alembic_version_ems` @ `0001_ems_baseline` (AC-11-06; never `create_all` in
  prod). Orchestrator fix: create the module schema before Alembic's version table.
- **API vertical** (as demo admin): terminology `project → {Event, Events}`; created Type
  → Template (materializes the participant eligibility scope graph) → Project (lifecycle
  status set; copy_scope materialized the project's own graph) → Profile → Participant
  (tier-2 scoped initial status set) → participants list = 1.
- **Frontend** (Playwright MCP, real login): `/ems/events` h1 = "Events", "New event"
  button, the live "City Run Live 2026" event in the list, module-gated "Events" sidebar
  group - all Terminology-driven (AC-11-11/12/13 list surfaces).

## Engine wiring (D9 - zero new engine code)

profile/project (unscoped tier-1/lifecycle) + project_participant (scoped, scope=project)
registered as status entities; terminology TermDefs (Event/Event Type/Event Template/
Participant/Profile); importer configs (profile + project-scoped participant find-or-create);
capabilities profile.resolve@1 + participant.resolve@1 - all via `register_engine_entities`/
`register_capabilities` at boot. The pre-existing status-engine suite stays green (tenant
lifecycle untouched - AC-11-15).

## Frontend scope (delivered vs deferred)

**Delivered (live-verified)**: ems-service, Profiles page (list + create + **profile bulk
import** via the F8 wizard), Events page (list + **create-from-template** dialog), module-
gated Events menu section with Terminology labels.

**Deferred refinements** (backend fully supports; primitives exist to wire): the tabbed
ResourceForm detail pages with the **Flow tab** (reuse `EntityFlow` with scopeId =
template_id / project_id) and the **embedded participants tab** with graph-driven row
transitions + in-tab bulk import. These are UI assembly over the proven backend +
existing components; logged as follow-ups.

## Verdict
The F4 EMS spine is **live end-to-end** - module installs via per-module Alembic, all four
foundation entities + two-tier status work, registers into every engine, and the vertical
is demoable (UI → API → Postgres). AC-11-01..11, 15, 17, 18, 19 MET; AC-11-12/13/14 list
surfaces met, detail-page Flow/participants UI deferred (documented). Clusters B-H can wire on.
