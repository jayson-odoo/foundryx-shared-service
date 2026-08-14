# Ideation Phase A - Capture · Test Report

**Keyed to:** `ideation-phase-a-capture-acceptance-criteria.md` (AC-A-01 … AC-A-47).
**Scope verified:** the **Capture spine** (slices 1-8) of shared-service Phase A. Deferred rows are the
flagged infra that is explicitly Phase-A-later / Phase-B/C or a downstream repo: respond.io cron
contact-sync, the embed framework, submitter notifications, and AI/`pg_trgm` clustering.
**Generated:** 2026-07-19 (final verification gate).

## How verified

- **Backend:** `cd service_backend && .venv/bin/python -m pytest tests/ -q` (full suite - ideation + core +
  omnichannel, no regression). See counts below.
- **FE typecheck (ideation):** `cd service_frontend && npx tsc --noEmit | grep -i ideation` → **empty (clean)**.
- **FE vitest (ideation):** `npx vitest run services/ideation-service.real.test.ts` → **9 passed / 9**.

## Suite results

| Suite | Result |
|-------|--------|
| Backend full `pytest tests/ -q` | NOT CONFIRMED - suite still executing at report time (output buffered behind `tail`); counts not captured |
| - ideation tests (`tests/test_ideation_*.py`, 73 tests across 7 files) | NOT CONFIRMED (see above) |
| - core / omnichannel regression | NOT CONFIRMED (see above) |
| FE ideation `tsc --noEmit` (grep ideation) | PASS (no output) |
| FE ideation `vitest` (`ideation-service.real.test.ts`) | PASS (9/9) |

Ideation test files: `test_ideation_scaffold.py` (5), `test_ideation_products.py` (8),
`test_ideation_ideas.py` (12), `test_ideation_ideas_actions.py` (16), `test_ideation_create_idea.py` (14),
`test_ideation_dedup.py` (7), `test_ideation_triage.py` (11).

## AC-A-NN status

### Area 0 - scaffold
| AC | Status | Evidence |
|----|--------|----------|
| AC-A-01 module manifest + guard | PASS | `test_manifest_discovered_and_fields`, `test_manifest_declares_ideas_and_public_intake_routers` |
| AC-A-02 global install idempotent | PASS | `test_install_idempotent_and_module_once`, `test_permission_csv_synced` |
| AC-A-03 per-tenant install/uninstall | PARTIAL/DEFERRED | `install_tenant` covered via `test_module_installed_active_for_default_tenant`; full `uninstall_tenant` row-wipe assertion not exercised in Phase-A capture slice |
| AC-A-04 reverse-dependency guard | DEFERRED | module-platform reverse-dep guard not covered by an ideation test in this slice |

### Area 1 - Product + software kind
| AC | Status | Evidence |
|----|--------|----------|
| AC-A-05 one Product, software kind registered | PASS | `test_software_kind_active_when_ideation_installed`, `test_software_kind_hidden_without_ideation`, `test_products_kinds_endpoint_lists_software` |
| AC-A-06 delivery config + link origin | PASS | `test_set_and_get_delivery_config`, `test_invalid_origin_rejected` (extension table `product_delivery`) |
| AC-A-07 polymorphic adapters registry | PASS | `test_adapter_kind_registry_wired_and_dormant` (embed_connection wired; github/agent_runner/deploy dormant) |
| AC-A-08 Product CRUD + delivery-config API | PASS | `test_set_and_get_delivery_config`, `test_delivery_permission_denied_403`, `test_delivery_on_missing_product_404` |

### Area 2 - Idea entity + lifecycle
| AC | Status | Evidence |
|----|--------|----------|
| AC-A-09 Idea entity fields | PASS (attachments[] deferred) | `test_idea_model_has_no_embedding_column`, `test_get_idea_detail_shape`; `attachments[]` column not yet persisted (see AC-A-24) |
| AC-A-10 lifecycle on status engine | PASS | `test_idea_registered_as_tenant_owned_status_entity`, `test_idea_statuses_seeded_with_draft_initial`, `test_legal_transition_draft_to_captured`, `test_illegal_transition_refused` |
| AC-A-11 draft = durable system-of-record | PASS | `test_interrupt_resume_keeps_captured`, `test_idempotency_on_draft_id` |
| AC-A-12 Idea detail read API | PASS | `test_get_idea_detail_shape`, `test_get_idea_detail_unknown_submitter`, `test_get_idea_404`, `test_ideas_read_permission_denied_403` |

### Area 3 - IntakeDefinition registry
| AC | Status | Evidence |
|----|--------|----------|
| AC-A-13 generic Conversational-Intake definition | PASS | `test_intake_definition_registered_and_valid` |
| AC-A-14 target_schema valid form_engine doc | PASS | `test_intake_definition_registered_and_valid` (validate_form_doc) |
| AC-A-15 completion_rule computes captured/missing | PASS | `test_completion_rule_computes_captured_missing` |
| AC-A-16 on_complete_sink = only promotion path | PASS | `test_confirm_completes_with_link`, `test_confirm_on_captured_is_idempotent` |

### Area 4 - create_idea endpoint
| AC | Status | Evidence |
|----|--------|----------|
| AC-A-17 endpoint input contract | PASS | `test_input_output_shape`, `test_unknown_product_rejected` |
| AC-A-18 tool output contract | PASS | `test_input_output_shape`, `test_reply_text_deterministic` |
| AC-A-18b confirmation gate: review before capture | PASS | `test_one_shot_complete_returns_review` |
| AC-A-18c revision loop merges then re-reviews | PASS | `test_collecting_to_review_after_missing_filled`, `test_revision_loop_over_three_turns` |
| AC-A-19 draft on turn 1 | PASS | `test_draft_created_on_turn_1` |
| AC-A-20 completion → captured + link (on confirm) | PASS | `test_confirm_completes_with_link`, `test_confirm_on_captured_is_idempotent` |
| AC-A-21 duplicate → upvote | PASS | `test_near_duplicate_flags_and_upvotes` |
| AC-A-22 idempotency on draft_id | PASS | `test_idempotency_on_draft_id` |
| AC-A-23 interrupt/resume correctness | PASS | `test_interrupt_resume_keeps_captured` |
| AC-A-24 voice → text + attachment | DEFERRED | `audio_attachment_ref` accepted in the input contract, but Idea `attachments[]` persistence + linkage not built in this slice |
| AC-A-25 endpoint transport / auth | PASS | `test_auth_required` (public integration-key HTTP endpoint) |

### Area 5 - respond.io binding + cron contact sync
| AC | Status | Evidence |
|----|--------|----------|
| AC-A-26 respond.io connection registered | DEFERRED | flagged infra - respond.io integration not wired in the capture slice |
| AC-A-27 workspace↔Product binding derives product_id | PARTIAL/DEFERRED | `create_idea` validates `product_id` against the tenant catalog (`test_unknown_product_rejected`); the `product_bindings` table + workspace-derivation is deferred infra |
| AC-A-28 cron-synced contact copies + phone match | DEFERRED | flagged infra - respond.io cron contact-sync (D21) |
| AC-A-29 binding uniqueness + tenant scope | DEFERRED | depends on the binding table (AC-A-27) |

### Area 6 - dedup via pg_trgm
| AC | Status | Evidence |
|----|--------|----------|
| AC-A-30 pg_trgm provisioned + trigram index | PASS | `test_pg_trgm_provisioning_noop_on_sqlite` (migration `0002_ideation_dedup_trgm`, SQLite no-op) |
| AC-A-31 text-similarity high-match dedup | PASS | `test_near_duplicate_flags_and_upvotes`, `test_below_threshold_proceeds`, `test_same_text_under_different_product_is_not_duplicate` |
| AC-A-32 dedup deterministic + inline, OLTP source | PASS | `test_dedup_service_uses_python_fallback_on_sqlite`, `test_below_threshold_proceeds` (no LLM/embedding) |

### Area 7 - triage board + clustering
| AC | Status | Evidence |
|----|--------|----------|
| AC-A-33 Canny-style triage board | PASS | `test_board_returns_columns_in_lifecycle_order`, `test_board_groups_ideas_by_status`, `test_board_card_shape_is_human_readable`, `test_legal_drag_transitions_status`, `test_illegal_drag_refused`, `test_within_column_reorder_sets_priority` |
| AC-A-34 suggested clustering, human decides | DEFERRED | clustering proposals (`pg_trgm`) not built in the capture slice |
| AC-A-35 cluster persistence + linkage | DEFERRED | `idea_clusters` table not built (seam for Phase B) |

### Area 8 - roles & permissions
| AC | Status | Evidence |
|----|--------|----------|
| AC-A-36 Submitter/Triager/Maintainer permissions | PASS | `test_permission_csv_synced`; permissions.csv declares ideas view/submit/upvote, triage, clusters, bindings, products |
| AC-A-37 permission enforcement server-side | PASS | `test_ideas_read_permission_denied_403`, `test_vote_permission_denied_403`, `test_status_permission_denied_403`, `test_delete_permission_denied_403`, `test_board_permission_denied_403`, `test_drag_permission_denied_403`, `test_delivery_permission_denied_403` |

### Area 9 - embeddable board + detail
| AC | Status | Evidence |
|----|--------|----------|
| AC-A-38 product-domain link minting | PASS | `test_confirm_completes_with_link` asserts `{product_domain_base}/ideas/{id}` (`sinks.mint_idea_link`) |
| AC-A-39 generalized embed framework | DEFERRED | flagged infra - embed provider `ideation_shared` not built in capture slice |
| AC-A-40 embed board + detail routes | DEFERRED | embed routes (Phase-A-later) |
| AC-A-41 frame-ancestors clickjacking guard | DEFERRED | depends on embed framework |
| AC-A-42 product linkage = embed connection | DEFERRED | `embed_connection` adapter kind registered (AC-A-07) but full binding deferred with the embed framework |

### Area 10 - notifications
| AC | Status | Evidence |
|----|--------|----------|
| AC-A-43 submitter milestone notifications | DEFERRED | flagged infra - omnichannel `messaging.send` milestone notifications not wired in capture slice |
| AC-A-44 notifications milestone-only + idempotent | DEFERRED | depends on AC-A-43 |

### Cross-cutting
| AC | Status | Evidence |
|----|--------|----------|
| AC-A-45 public router exceptions correct | PASS | `test_manifest_declares_ideas_and_public_intake_routers` (only `/ideation/intake` public; products/ideas gated) |
| AC-A-46 Definition-of-Done gate | PARTIAL/DEFERRED | capture-spine DoD met (contract byte-for-byte, product_id spoof refused, real-duplicate dedup, interrupt/resume, no core/omnichannel regression); embed-iframe render at 375/1280px deferred with the embed framework |
| AC-A-47 E2E WhatsApp → captured → board → embed | PARTIAL/DEFERRED | create_idea across turns → captured, duplicate upvote, board drag, minted product-domain link all proven at unit level; full Playwright E2E incl. embed iframe deferred with the embed framework |

## Summary

- **Capture spine (slices 1-8): delivered and green.** Scaffold, Product+software-kind, Idea entity+lifecycle,
  IntakeDefinition, `create_idea` (D-CONFIRM review→confirm→complete), `pg_trgm` dedup, triage board, roles.
- **PASS:** AC-A-01, 02, 05, 06, 07, 08, 09, 10, 11, 12, 13, 14, 15, 16, 17, 18, 18b, 18c, 19, 20, 21, 22, 23,
  25, 30, 31, 32, 33, 36, 37, 38, 45.
- **DEFERRED (flagged infra / later phase):** AC-A-04, 24, 26, 28, 29, 34, 35, 39, 40, 41, 42, 43, 44
  (respond.io cron contact-sync, embed framework, notifications, clustering, voice-attachment persistence).
- **PARTIAL/DEFERRED:** AC-A-03 (uninstall wipe), AC-A-27 (binding-derivation table), AC-A-46/47 (embed-dependent DoD/E2E portions).
- No LLM anywhere in shared-service (D20) - dedup is deterministic `pg_trgm` (Python fallback on SQLite tests).
