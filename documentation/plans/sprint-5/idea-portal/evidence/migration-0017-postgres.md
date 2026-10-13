# Migration 0017 on live Postgres 16 (sandbox, 13 Oct 2026)

How it was run:
1. Fresh `bootstrap_db` on a throwaway database `fx_portal_test`.
2. Simulated a pre-0017 database:
   - dropped `idea_activity` and `idea_comment_likes`;
   - dropped the columns `ideas.portal_hidden`, `ideas.portal_note`, `idea_votes.voter_name` and `idea_votes.voter_role`;
   - set `alembic_version_ideation` back to `0016_ideation_own_ideas`;
   - inserted two `idea_status_events` rows: one `status_changed` (New → Triaged) and one `merged`.
3. Ran `run_module_migrations(engine, "ideation")` twice.

Result:
- The version is now `0017_ideation_portal`.
- `idea_activity` has exactly 1 row: `ise:ev-1`, status_changed, New → Triaged, `source_event_id=ev-1`. The `merged` event was not copied.
- The second run inserted nothing, so the backfill is idempotent.
- The new columns:
  - `portal_hidden boolean NOT NULL DEFAULT false`
  - `portal_note text NULL`
  - `voter_name` and `voter_role` varchar NULL
- `idea_comment_likes` has `UNIQUE (comment_id, liker_id)`, foreign keys to `ideas` and `idea_comments`, and 3 indexes.
