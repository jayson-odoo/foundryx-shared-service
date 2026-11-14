# 52 - respond.io continuous sync until cutover - test execution report

Lane SS-MIGRATION-SYNC. UAC: `52-migration-continuous-sync-acceptance-criteria.md`. Backend tests were red-first (commit c3d01479) and are green at head deb6ebea (67 passed). A first live run used ac21fda9; a re-run on the round 2 build (f77a3db8 code, docs-only commits after) is described under "Re-run". The live run used a stack started from ac21fda9, a throwaway local Postgres (role and db `sync_e2e`) and a local synthetic respond.io; nothing live or shared was touched. Evidence: `documentation/plans/sprint-5/52-evidence/continuous-sync/` (15 screenshots plus `command-log.txt`).

Test files: BE `service_backend/tests/test_omnichannel_migration_sync.py` (01-06, 30-33), `test_omnichannel_migration_sync_ticks.py` (10-21, 40-44), `test_omnichannel_migration_sync_support.py` (fixtures only), `test_omnichannel_migration_sync_security.py` (security round, extra). FE `service_frontend/app/(protected)/omnichannel/settings/migration/components/migration-sync-card.test.tsx`.

## FAIL

None of the ACs failed. Findings and deviations are listed under "Findings" below; read the first two.

## Verdicts

| AC | Verdict | Evidence |
|---|---|---|
| AC-SYNC-01 | PASS | `test_sync_01_create_from_done_run`. Live: Start syncing on the DONE run created an Active sync (`04-sync-active-1280.png`) |
| AC-SYNC-02 | PASS | `test_sync_02_no_finished_real_api_run_is_409_and_stores_nothing` (none, dry run only, CSV only, failed run; control 201) |
| AC-SYNC-03 | PASS | `test_sync_03_exists_409_and_stopped_row_is_reactivated`. Live: Start syncing on a Stopped sync re-activated the same row, totals kept (`12-active-375.png`) |
| AC-SYNC-04 | PASS | `test_sync_04_tenant_scope_and_read_only_user` |
| AC-SYNC-05 | PASS | `test_sync_05_item_hides_secret_and_webhook_url_rotates`, `test_sync_05_webhook_url_uses_public_base_url`, security `test_n5_webhook_url_routes_are_no_store`. Live: webhook URL shown only to the manager, wrong secret gave HTTP 404 (`command-log.txt`) |
| AC-SYNC-06 | PASS | `test_sync_06_contact_count_and_estimate_dry_run_then_tick`. Live: card shows "4 respond.io contacts. Full sweep about 1 min." then "5 respond.io contacts" after the tick |
| AC-SYNC-10 | PASS | `test_sync_10_due_sync_enqueues_exactly_one_job`, `..._not_due_enqueues_nothing`, `..._beat_task_registered_every_60_seconds`, `..._job_type_constant`. Live: the beat stand-in `run_due.py` started exactly one job per sweep (`{'started': 1}`) |
| AC-SYNC-11 | PASS | `test_sync_11_poll_creates_new_contacts_and_skips_untouched_histories`. Live: new contact Eka created with 1 message, "+1 contacts" (`05-after-sync-now-1280.png`) |
| AC-SYNC-12 | PASS | `test_sync_12_hints_tick_fetches_flagged_and_creates_unknown`. Live: curl hint for Aisyah, next sweep ran a `hints` job, her message count 2 to 3, hints table emptied (`08-after-webhook-hint-1280.png`) |
| AC-SYNC-13 | PASS | `test_sync_13_full_sweep_rechecks_everyone_and_stamps_on_completion[due,never]`, `test_sync_13_recent_full_sweep_is_not_repeated`. Live: a recent full sweep is not repeated, which is why Aisyah's new message was not picked up until the hint |
| AC-SYNC-14 | PASS | `test_sync_14_second_identical_tick_writes_nothing`, `..._native_whatsapp_id_is_skipped_and_counted`, `..._synced_rows_store_the_whatsapp_id_in_payload` |
| AC-SYNC-15 | PASS | `test_sync_15_synced_messages_follow_the_read_only_history_rules`. Live: not observed (no realtime client attached) |
| AC-SYNC-16 | PASS | `test_sync_16_skipped_channel_then_mapped_relinks_on_next_tick` |
| AC-SYNC-17 | PASS | `test_sync_17_mapping_follows_the_newest_done_real_api_run` |
| AC-SYNC-18 | PASS | `test_sync_18_tick_waits_while_a_migration_job_runs`, `..._migration_create_is_409_while_a_sync_job_runs` |
| AC-SYNC-19 | PASS | `test_sync_19_one_bad_contact_does_not_stop_the_tick` |
| AC-SYNC-20 | PASS | `test_sync_20_source_wins_overwrites_non_empty_and_never_clears`, `..._no_change_no_write`, `..._lifecycle_and_assignee_follow_source_only_when_mapped` |
| AC-SYNC-21 | PASS | `test_sync_21_one_off_migration_stays_fill_if_empty`; the existing migration suites stay green (293 passed, below) |
| AC-SYNC-30 | PASS | `test_sync_30_webhook_stores_one_hint_and_calls_nothing`. Live: HTTP 200 `{"ok":true}`, no respond.io call in the request |
| AC-SYNC-31 | PASS | `test_sync_31_wrong_secret_unknown_stopped_inactive_module_are_uniform_404`, `..._secret_compared_in_constant_time`, security `test_n1_unknown_sync_id_is_the_same_uniform_404`. Live: wrong secret gives 404 `{"detail":"Not Found"}`; after Stop the hint URL is no longer accepted by the backend tests |
| AC-SYNC-32 | PASS | `test_sync_32_unusable_bodies_never_500_and_store_nothing`, `..._hints_are_deduped_per_contact`, `..._pending_hints_capped_at_5000`, security `test_s2_deeply_nested_json_is_204_and_stores_nothing` |
| AC-SYNC-33 | PASS | `test_sync_33_payload_is_never_written_only_the_contact_id` |
| AC-SYNC-40 | PASS (BE) / DEFERRED (live) | `test_sync_40_token_rejected_pauses_emails_creator_and_resume_restarts[401,403]`, security `test_s4_paused_email_html_escapes_the_workspace_name`. Live: not run (no way to make the local fake reject the token without a code change); the card's paused state was shown via the user Pause, and the token_rejected text by vitest |
| AC-SYNC-41 | PASS (BE) | `test_sync_41_rate_limited_tick_records_error_and_stays_active`. Live: not run |
| AC-SYNC-42 | PASS | `test_sync_42_pause_resume_run_now`, `..._run_now_is_409_while_a_tick_is_running`, `..._running_tick_stops_at_its_next_checkpoint_when_paused`. Live: Sync now, Pause, Resume clicked (`06-paused-1280.png`, `07-resumed-1280.png`, `13-paused-375.png`) |
| AC-SYNC-43 | PASS | `test_sync_43_stop_runs_one_final_tick_then_sets_csw_and_stops`, `..._stop_end_to_end_in_eager_mode`, `..._nothing_ever_stops_a_sync_automatically`. Live: Stop confirm then Stopped (`09-stop-confirm-1280.png`, `10-stopped-1280.png`, `14-stop-confirm-375.png`, `15-stopped-after-confirm-375.png`); jobs `poll`, `hints`, `final` all done; 2 respond.io contacts got a `csw_expires_at` (the two with an incoming message in the last 24 h) |
| AC-SYNC-44 | PASS (BE) | `test_sync_44_deleted_connection_pauses_with_reason_never_deletes`, `..._trashed_workspace_pauses_with_reason_never_deletes`. Live: not run |
| AC-SYNC-50 | PASS | vitest `canOfferSync (AC-SYNC-50)`, `shows Start syncing to managers when no sync exists, and starts one`, `hides Start syncing from read-only users`. Live: `03-done-start-syncing-1280.png` |
| AC-SYNC-51 | PASS | vitest `active: status line, actions, contact count, webhook URL`. Live (first run and re-run): status line, Sync now / Pause / Stop syncing (cutover), contact count and sweep estimate, webhook URL with Copy and Rotate link (`05-after-sync-now-1280.png`, `12-active-375.png`, `r2-01-active-1280.png`, `r2-02-after-sync-now-1280.png`, `r2-10-active-375.png`, `r2-10b-active-card-375.png`). Re-run at 1280: input 722 px wide, Copy and Rotate link on the same row; at 375: input 286 px full width, Copy and Rotate link wrap to their own row, Sync now / Pause / Stop wrap below |
| AC-SYNC-52 | PASS | vitest `paused token_rejected shows the reason and Resume`, `Stop opens a confirm dialog, then reads Stopped after the final tick`, `stopped shows "Stopped <time>"`. Live: Paused with Resume (`06-paused-1280.png`, `r2-06-paused-1280.png`, `r2-12-paused-375.png`), Stop confirm (`r2-07-stop-confirm-1280.png`, `r2-13-stop-confirm-375.png`), "Stopped 04 Nov 2026, 05:17" (`r2-08-stopped-1280.png`, `r2-14-stopped-after-confirm-375.png`). Rotate link opens a confirm dialog "Rotate webhook link?" (`r2-04-rotate-confirm-1280.png`, `r2-11-rotate-confirm-375.png`); after confirm the card shows a new URL, the old URL returned HTTP 404 and the new one HTTP 200 by curl (`command-log.txt`, `r2-05-after-rotate-1280.png`). 409 path: with a tick running that the open card did not know about, Sync now gave the toast "A sync is already running. Try again when it finishes." (`r2-03-409-sync-now-1280.png`). With the tick known, Sync now is shown disabled with a spinner instead |
| AC-SYNC-53 | PASS (vitest) / not exercised live | vitest `renders the failure sample with the failures table`, `running tick disables Sync now`. Live: the failures table did not render, because the one failing tick ran before its error reached the sample (card showed the error line "The respond.io API address is not allowed." instead). Polling not timed live |
| AC-SYNC-54 | PASS | Two recorded agent-browser runs at 1280 and 375: start, status line, Sync now, Pause, Resume, hint, Rotate, Stop, Stopped. `scrollWidth` vs `innerWidth` at 375, re-run: 360/375 (stopped, active, paused, stopped after confirm), 375/375 with a dialog open; no sideways scroll. At 1280: 1280/1280 (stopped). The wide counts-report table scrolls inside its own container (existing behaviour) |

## Suites

- BE sync files: `.venv/bin/python -m pytest -q tests/test_omnichannel_migration_sync*.py` : 54 passed (47 of mine plus 7 security).
- BE migration and jobs regression: `pytest -q -n auto --dist loadfile tests/test_omnichannel_*migration*.py tests/test_background_jobs.py` : 293 passed.
- FE: `npx vitest run migration-sync-card.test.tsx` : 10 passed.
- Not run: the full backend suite and the full vitest suite (CI runs them).
- Live Postgres: `python -m scripts.bootstrap_db` against the throwaway role and db ran clean; module revision `0024_omni_migration_sync` is in `app_omnichannel.alembic_version_omnichannel`, tables `migration_syncs` and `migration_sync_hints` exist.

## Live run (what was clicked)

Signed in as demo@example.com, then clicked: sidebar Omnichannel > Migration > New migration, chose the respond.io connection, target workspace, channel map, Run dry run (Done, 4 contacts, 8 messages), Start migration (Done), Start syncing. The beat does not run in eager dev, so `run_due.py` (a scratch script, not committed) called `run_due_syncs` as a stand-in. Respond.io was a local Python fake serving the `/v2` paths the client uses, with 4 synthetic contacts (+60 12-000 0001 to 0004). Between ticks I added a message to Aisyah and a new contact Eka through the fake's control endpoint.

Sequence: Sync now click, beat, reload: "+1 contacts, +1 messages" and Eka exists. Pause, Resume. curl POST of a hint for Aisyah to the webhook URL read from the card (200); wrong secret (404); `hints` job ran; Aisyah's message count 2 to 3; hints table empty. Stop syncing (cutover), confirm, Stopped; final job done. Start syncing again at 375 re-activated the row; Pause, Resume, Stop confirm at 375, Stopped.

## Findings and deviations

1. The URL guard and my setup. The stack I started was built from ac21fda9, which had no base-URL guard, so a connection with `baseUrl` `http://127.0.0.1:9100/v2` was accepted. Head now has the guard at save time and at connect time (`test_s3_private_or_http_base_url_is_refused_at_save`). On head the same local fake is refused, as intended. I did not patch repo code. The beat stand-in script bypassed the guard in its own process only (scratch harness). The connection was created through the API, not Settings > Integrations, because of this. The live run therefore proves the flows, not the guard. The guard is covered by the security tests only.
2. The working tree moved during the run (security commits 0954e9a8 and 47501917, and uncommitted edits by another seat). The live uvicorn and the built frontend are at ac21fda9 behaviour; the report's live statements are about that build.
3. Before I bypassed the guard in the harness, ticks failed with `The respond.io API address is not allowed.` (clean, shown on the card, sync stayed Active), and a few later attempts showed `Job crashed (UrlGuardError)` in `background_jobs`. Those crashes came from my patched client (guard transport still active at connect), not from an unpatched head, and head has `test_s3_tick_with_a_private_base_url_fails_the_tick_without_crashing`. Reported for completeness; not a claimed defect.
4. Cosmetic: right after Start syncing the card reads "Next sync <now>" (a time that has already passed) until the first tick, because a new sync is due immediately and eager dev has no beat. In production the 60 s beat clears this within a minute.
5. Harness note: the first agent-browser click on Start syncing at the page bottom did not fire until the button was scrolled to the middle of the viewport. The same button works with a real click after `scrollIntoView`; not treated as an app defect.
6. Not in this lane: the finished migration's detail page labels columns "Would create" / "Would update" for a real run (existing page, left as is).

## DEFERRED

- AC-SYNC-40, 41, 44 live runs (token rejected, rate limit, deleted connection): need a fake that rejects or a destructive change on a shared tenant; covered by BE tests.
- Live check that synced messages arrive without a realtime push or workflow (AC-SYNC-15): needs a connected realtime client; covered by BE tests.
- Webhook signature verification: backlog item in the plan, not built.
- Removed stack: the throwaway Postgres role/db and the servers on :8001, :3001 and :9100 were stopped after the run.

## Re-run on the round 2 build

Fresh throwaway Postgres (`bootstrap_db`, migration 0024 applied), fresh `rm -rf .next && npm run build`, a fresh local synthetic respond.io, all signed in as demo@example.com with real clicks (Omnichannel > Migration > New migration > Run dry run > Start migration > Start syncing). New files are prefixed `r2-` under `52-evidence/continuous-sync/`; the earlier files are kept.

- **Guard handling (no app code patched).** The respond.io connection was created through the API with the public `https://api.respond.io/v2` base URL, then its `baseUrl` in `config_json` was changed directly in the throwaway DB to the local fake (`http://127.0.0.1:9100/v2`). The guard still refuses that address at connect time, so the backend was started through a scratch launcher (`serve.py`, not committed) and the beat stand-in (`run_due.py`, not committed) that replace the guard functions in their own process. The guard itself is not exercised by this run; it is covered by the security tests.
- **Rotate.** Rotate link opened the confirm dialog; after Rotate link in the dialog the card showed a new URL, the old URL returned 404 and the new URL 200.
- **409.** Triggered by inserting a running sync job row in the throwaway DB after the page had loaded, then clicking Sync now on the card. The server answered 409 and the toast read "A sync is already running. Try again when it finishes."
- **Webhook row at 375.** The input is full width (286 px) and Copy / Rotate link wrap onto the next row; no sideways scroll.
- **Not re-checked live:** the webhook hint to next-sweep flow (covered in the first run), token_rejected / rate limit / deleted connection (backend tests).
