# UAC - Meetings S4: Minutes

Plan: `PLAN-meetings-s4-minutes.md`. Spine gate: minutes render for 10 real meetings; tenant
language honoured.

**AC-S4-1 auto chain** - Given a meeting whose `meetings.transcribe` job succeeds, then a
`meetings.minutes` job is enqueued automatically, and on its success the meeting status is
`ready`. Transcribe still sets `transcribed` itself (the hop belongs to the minutes job).

**AC-S4-2 minutes row** - Given a transcribed meeting, when minutes generate, then exactly one
new `minutes` row exists with the next `(meeting_id, version)`, `created_by="llm"`,
`sections_json` containing all five M14 sections (`summary`, `decisions`, `action_items`,
`open_questions`, `topic_notes` - empty lists allowed), and `prompt_version_id`,
`llm_provider`, `llm_model` recorded.

**AC-S4-3 action items** - Given generated minutes containing action items, then matching
`action_items` rows exist (`text` required, `owner_email` and `due_on` nullable, stored raw),
and `POST /action-items/{id}/toggle` sets `done_at` and clears it on the second call.

**AC-S4-4 language honoured** - Given a tenant whose `minutes_language` is `zh`, when minutes
generate for a meeting with an English transcript, then the minutes prose is Chinese while the
transcript segments remain verbatim and unchanged. (Gate criterion; verified on a real meeting.)

**AC-S4-5 LLM resolution** - Given `tenant_settings.llm_connection_id` set to an active `llm`
connection, minutes use that connection's provider and credentials; given it unset, the platform
default (`meetings_llm_provider`/`_model`/`_api_key`, default `gemini` / `gemini-3.5-flash`) is used; given
neither a usable connection nor a platform key, the job FAILS with a clear error, the meeting
stays `transcribed`, and nothing crashes the worker. An undecryptable connection stamps the
connection `error` (google_dwd pattern).

**AC-S4-6 activity log** - Every LLM call (success and failure) writes one `integration_activity`
row: `source="meetings"`, operation `minutes_generate`, latency_ms, status; logging failures
never fail the job.

**AC-S4-7 structured output discipline** - Given an LLM response that is not valid JSON or
misses the section shape, then exactly one corrective retry happens; a second bad response fails
the job with the validation error in the job log. No partially-written minutes row survives a
failed run.

**AC-S4-8 read + edit versions** - `GET /meetings/{id}/minutes` returns the latest version with
its action items and the version list; `PUT` with edited sections creates the NEXT version with
`created_by=<user id>` and leaves every prior version readable; re-running the minutes job also
appends (never overwrites). Every response field is asserted in a test (response_model drops
undeclared fields).

**AC-S4-9 registry semantics** - Prompt versions are immutable append-only (no update/delete
route); publish repoints the label row and takes effect on the next job without a restart
(cache busted); with an empty registry the resolver serves the hardcoded `meetings_minutes`
fallback and the job still succeeds.

**AC-S4-10 editor gating** - The prompt editor pages and routes are usable by a platform-tenant
admin; a non-platform user sees no menu entry and gets a permission-gated page/403 on the API.
Editor can: list prompts, view version history and a version body, create a new version, publish
to `production`.

**AC-S4-11 gate** - Minutes rendered for 10 real meetings (gate recordings + re-runs of already
transcribed meetings), each passing AC-S4-2 shape checks; at least one meeting demonstrates
AC-S4-4.

**AC-S4-12 job registration** - The `meetings.minutes` handler is registered in every worker
entrypoint that registers `meetings.transcribe`; a job enqueued while the handler is missing
stays Pending (documented worker-restart note in DEPLOY.md).

**AC-S4-13 manual regenerate** - `POST /meetings/{id}/minutes/regenerate` (manage permission)
enqueues a minutes job that appends the next version; a second call while one is
pending/running returns 409 and enqueues nothing.
