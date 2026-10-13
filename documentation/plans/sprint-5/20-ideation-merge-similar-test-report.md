# 20 - Ideation merge + similar - Test Execution Report

Lane IDEA-CORE, PR #124. Keyed to `20-ideation-merge-similar-acceptance-criteria.md`.

Head verified: `b6cffdec` (browser pass and full frontend vitest 473 files / 3762 tests).

Environment: cloud sandbox with a sandbox-local Postgres 16 and Redis, fresh `bootstrap_db`, uvicorn on :8001, a fresh `rm -rf .next && npm run build` + `next start` on :3001, and a headless Chromium (playwright-core) driving real clicks. Data: the owner's real IDEA-0010 title, business problem and original message, plus "Quotation knowledge capture", plus two ideas marked `(SAMPLE)`, all created locally and never committed. AI: a local OpenAI connection on the tenant's `ideation-grill` agent (model gpt-4o-mini). Screenshots are in `20-evidence/browser/`.

Automated suites:
- Backend: `pytest -k "ideation or intake"`, 855+ passed. New files: `test_ideation_canny_fields.py` (8), `test_ideation_field_merge.py` (12), `test_ideation_similar.py` (8), plus embed tests in `test_ideation_embed_writes.py` (2).
- Frontend: ideation vitest, 39 files / 318+ tests.
- Kill tests (each mutation was reverted afterwards):
  - combine dedup
  - unmerge restore check
  - flatten snapshot handling
  - snapshot chaining
  - similar id filter
  - similar self-exclusion
  - similar agent detach
  - FE default-tick fallback
  - FE combine separator

| AC | Result | Evidence |
|---|---|---|
| AC-20-01 | PASS | `test_migration_0017_is_additive_and_short_id`. On live Postgres: stamped 0016, dropped the 4 columns, re-ran `bootstrap_db`. The log showed `Running upgrade 0016 -> 0017`, version is now `0017_ideation_canny_fields`, and all 4 columns are present. |
| AC-20-02 | PASS | `test_one_shot_*`, `test_operator_create_and_patch_new_fields` |
| AC-20-03 | PASS | `test_one_shot_persists_new_fields`, `..._without_new_fields_and_unknown_keys_ok`, `..._blank_strings_are_null`, `..._use_cases_must_be_a_list` |
| AC-20-04 | PASS | `test_turn_intake_captures_new_fields`, `test_ask_order_unchanged`, `test_ac_1101_*` updated |
| AC-20-05 | PASS | `test_operator_create_and_patch_new_fields`; the embed PATCH goes through the same service (`ideation-embed-service.merge.test.ts`) |
| AC-20-06 | PASS | vitest `DetailsTab - plan 20 card fields`. Browser: `op-details-desktop/mobile.png`, `embed-details-*.png` (empty new fields show "-"; no Proposed solution / Impact / Department rows) |
| AC-20-07 | PASS | vitest edit-mode + `UseCasesInput`; capture dialog test |
| AC-20-08 | PASS | `embed-list/details/similar-{desktop,mobile}.png` via `/embed/ideas#token=` (embed token minted from a signed assertion, the same handoff Sorento's iframe uses), scrollWidth = viewport at 375 and 1280 |
| AC-20-09 | PASS | `test_embed_card_fields_json_parity` |
| AC-20-10 | PASS | `test_field_merge_picks_and_combines`, `test_combined_skips_empty_values`. Browser: ticked two Business problem cells and two Use cases cells; the result on Details matched the dialog's Result preview (`op-merge-dialog-ticked-desktop.png`, `op-after-merge-desktop.png`) |
| AC-20-11 | PASS | `test_field_merge_validation_writes_nothing`, `test_merge_without_fields_keeps_survivor_values` |
| AC-20-12 | PASS | `test_votes_still_move_with_field_merge`; the full `test_ideation_merge.py` suite stays green; live merge minted IDEA-0001 for the survivor |
| AC-20-13 | PASS | `test_unmerge_restores_unedited_fields`, `test_dissolve_group_restores_fields`, `test_two_layered_merges_unwind`, `test_out_of_order_unmerge_chains_snapshots`, `test_flatten_drops_stale_snapshot`. Live: dissolving the browser merge restored title, problem, desired outcome, use cases and workaround exactly |
| AC-20-14 | PASS | `test_survivor_reads_through_child_comments_and_attachments` |
| AC-20-15 | PASS | `test_embed_field_merge_and_scope` |
| AC-20-16 | PASS | vitest `MergeIdeasDialog (plan 20)` (5 tests, including the kept radio moving the untouched defaults); `op-merge-dialog-desktop.png` |
| AC-20-17 | PASS | `ideas-view.tsx` bulk Merge opens the same dialog with `fields`; the list action allows N >= 2 |
| AC-20-18 | PASS | `op-merge-dialog-mobile.png`: grid scrolls inside the dialog, the label column stays, page scrollWidth is 375 |
| AC-20-19 | PASS | `test_embed_merge_lifecycle_json_parity` |
| AC-20-20 | PASS | `test_similar_ranked_by_ai_and_scoped`, `test_similar_candidates_exclude_merged_and_test`. Live AI: for IDEA-0010 the model returned the two dealer/order ideas in about 1.7s and left out "Quotation knowledge capture" |
| AC-20-21 | PASS | `test_similar_unavailable_on_*` (error, unusable output, exception), `test_similar_no_candidates_makes_no_ai_call`, `test_similar_never_rewrites_the_agent_connection`. Live, with no connection: `{"available":false,"ideas":[]}` |
| AC-20-22 | PASS | `test_embed_similar_scoped`; live embed call returned `available:true` |
| AC-20-23 | PASS | vitest `IdeaSimilarTab` + `useIdeaSimilar`; `op-similar-*.png`, `op-similar-selected-*.png` (bulk "Actions" > Merge) |
| AC-20-24 | PASS | Real clicks: sidebar Ideation > Ideas > IDEA-0010 > Similar ideas > tick both > Bulk actions > Merge > tick cells > Merge, at 1280 (full merge) and 375 (through the open dialog) |

Notes:
- The broken "Default Logo" image in the sandbox header is local branding with no logo asset. It is a pre-existing environment issue, not this change.
- Ideas created by the operator API have no idea number until they are captured or merged, so the separator falls back to the title (`--- from Dealer portal to see my orders (SAMPLE) ---`). Real captured ideas carry `IDEA-xxxx`.
