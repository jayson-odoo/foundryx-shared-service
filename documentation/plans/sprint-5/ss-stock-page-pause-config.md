# SS-STOCK-PAGE-PAUSE-CONFIG - owner-set pause between AutoCount pages

Size S. Follows SS-STOCK-BAL-SOOTHE (#360).

## Ask (owner 27 Nov)
The pause between AutoCount page requests is set in the app, by the owner, up to minutes.
Owner change 27 Nov ~09:40: the default is **0 s** ("then you let me control"), also for
connections saved without a value.

## Where it lives today (#360)
- Setting: per AutoCount REST connection, `config_json.pagePauseSeconds`, next to `pageSize`
  (`modules/autocount/provider.py` fields), read by `http_source/gentle.py gentle_settings`.
- Pause: `http_source/source.py _walk_path_serial` (main walk, page > 1 only).
- Overlap guard: already exists - `scheduler.py _sweep_one` (in-flight job -> `skipped` run row).

## Change
1. Range 0-90 s (was 0-10), default 0 (was 1); out-of-range rejected at save with a message saying why
   (crew 27 Nov: capped at 90 s so a ~70-page stock run stays under the 2 h job limit).
2. The pause sleeps in short slices; between slices the run beats its heartbeat and stops at once
   when the job was aborted / swept (a long pause never crosses the 15 min orphan window).
3. The connection form shows a read-only hint under the field: "About N pages per run - about X min
   per run" from the connection's heaviest task's last run (pages + pause recorded on the run,
   `ac_sync_run.source_pages`/`page_pause_ms`); it says when the estimate passes the 2 h limit, and
   when Max concurrent pages > 1 switches the pause off.
4. The setting stays in `connections.config_json` (no migration for it); additive migration
   `0051_autocount_run_pages` adds the two nullable run columns for the hint.

## Acceptance
- AC-1 setting saved and read; default 0; blank/legacy = 0.
- AC-2 a value outside 0-90 rejected at save, naming the field and the 2 h limit.
- AC-3 the walk pauses N s between pages (not before the first or after the last).
- AC-4 an aborted run stops during the pause instead of sitting it out.
- AC-5 a scheduled tick while the previous run of the same task is in flight is skipped.
- AC-6 the hint shows the last run's page count and the estimated minutes.
