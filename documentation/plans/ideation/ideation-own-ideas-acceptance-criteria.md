# SS-IDEATION-OWN - acceptance criteria

Contract: `documentation/ideation/own-ideas-contract.md`.
Tests: `service_backend/tests/test_ideation_own.py` (test name in brackets).

## One-shot create
- AC-OWN-01 [BE][T] Given a workspace key and a CRM user id, When `POST /ideation/intake/ideas`, Then 201 `{idea_id, idea_number, status:"captured", title, link}` and numbers increase per tenant. [test_one_shot_create_returns_id_and_number]
- AC-OWN-02 [BE][T] The idea stores the CRM user id and links the contact matched by phone. [test_one_shot_create_links_submitter_contact_and_crm_user]
- AC-OWN-03 [BE][T] Missing/blank `submitter_crm_user_id` = 422 `submitter_required`. [test_one_shot_create_requires_crm_user]
- AC-OWN-04 [BE][T] Blank problem = 422 `problem_required`; >8-word title = 422 `title_too_long`; junk phone = 422 `invalid_phone`. [test_one_shot_create_rejects_blank_problem, test_one_shot_create_rejects_long_title_and_junk_phone]
- AC-OWN-05 [BE][T] Unknown product = 404; no key = 401. [test_one_shot_create_unknown_product_and_auth]
- AC-OWN-06 [BE][T] Attachments persist. [test_one_shot_create_persists_attachments]
- AC-OWN-08 [BE][T] A retry with the same `intake_ref` returns the same idea (no second number); a different submitter reusing it = 409. [test_one_shot_create_is_idempotent_on_intake_ref]
- AC-OWN-09 [BE][T] Phone matching uses normalized digits on the stored side too (legacy unstamped rows included); new contacts are stamped. [test_one_shot_create_matches_formatted_stored_phone, test_one_shot_create_new_contact_is_stamped, test_similar_own_matches_stamped_digits]
- AC-OWN-07 [BE][T] The existing `/create-idea` turn flow is unchanged (existing `test_ideation_create_idea*` suites stay green).

## Own-similar
- AC-OWN-10 [BE][T] Matches only the same submitter's ideas (phone), never another submitter's. [test_similar_own_matches_same_phone_only]
- AC-OWN-11 [BE][T] Phone formatting tolerant (`+`/spaces/dashes). [test_similar_own_phone_format_tolerant]
- AC-OWN-12 [BE][T] Matches by CRM user id. [test_similar_own_matches_crm_user_id]
- AC-OWN-13 [BE][T] Never matches by name. [test_similar_own_never_matches_by_name]
- AC-OWN-14 [BE][T] No usable identity = 422. [test_similar_own_requires_an_identity]
- AC-OWN-15 [BE][T] Live ideas only, top 3. [test_similar_own_live_only_top_three]
- AC-OWN-16 [BE][T] Same product, at/above the dedup threshold. [test_similar_own_scoped_to_product_and_threshold]
- AC-OWN-18 [BE][T] Ownership never crosses tenants (same CRM id + phone in another tenant). [test_similar_own_and_mine_never_cross_tenants]
- AC-OWN-17 [BE] pg_trgm path on Postgres (manual, see PR evidence).

## Embed
- AC-OWN-20 [BE][T] `isMine` true for own ideas (CRM id or phone claim), false for others even with the same name - on list, detail and board. [test_embed_is_mine_flags]
- AC-OWN-21 [BE][T] `mine=true` returns only own ideas. [test_embed_mine_filter]
- AC-OWN-22 [BE][T] No identity = empty `mine` list, all `isMine` false. [test_embed_mine_never_leaks_without_identity]
- AC-OWN-23 [BE][T] Embed create stamps the CRM user. [test_embed_create_stamps_crm_user]
- AC-OWN-24 [BE][T] `ideas_manage=false` blocks changes to others' ideas (patch / status / delete / reorder / merge / unmerge / attach = 403), allows own + voting. [test_embed_manage_claim_false_blocks_others_ideas]
- AC-OWN-26 [BE][T] Unmerging a survivor with `ideas_manage=false` needs every idea in the group to be the viewer's. [test_embed_manage_claim_false_unmerge_needs_whole_group]
- AC-OWN-25 [BE][T] `ideas_manage` true/absent keeps legacy access. [test_embed_manage_claim_true_or_absent_keeps_legacy_access]

## Migration
- AC-OWN-30 [BE] Migration `0016_ideation_own_ideas` adds `submitter_crm_user_id` + `intake_ref` (+ unique per tenant) idempotently; single head; upgrade 0015 -> 0016 verified on Postgres.
