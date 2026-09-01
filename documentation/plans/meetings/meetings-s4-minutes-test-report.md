# Test report - Meetings S4: Minutes

Date: 2026-09-02. Branch `sprint-5/meetings-s4-minutes` (stacked on `sprint-5/meetings-s3-codeswitch`, PR #38).
Live evidence on the pilot stack (`foundryx_meetings_pilot`, Mac Mini), tenant llm connection
`ai-meeting` (gemini / gemini-3.5-flash, key entered by the captain via the Integrations UI,
never exposed to agents).

## Automated

- Registry: `tests/test_ai_prompt_registry.py` 22/22 (post-P3).
- Minutes: `tests/test_meetings_minutes_service.py` + `_routes.py` + extended `test_meetings_stt_jobs.py` 62/62 (post-P3).
- Scoped: `pytest -k "meetings or prompt"` 299 passed (post-P3).
- Full unscoped suite after P2a: 2714 passed, 1 skipped. Post-P2b full run: 2749 passed, 1 skipped (25m19s).
- FE vitest (prompt editor): 6/6. tsc/eslint clean on touched files.

## Live evidence (AC references)

| Check | Result |
|---|---|
| AC-S4-1 auto chain | Wiring unit-tested (transcribe success enqueues exactly one minutes job; failure enqueues none). Full unattended chain calendar->...->ready pending the next real meeting (Sep 2-4 gates) |
| AC-S4-2 minutes row | PASS live - job 82b7743a on meeting 734759ad: minutes v1, created_by=llm, all five sections, prompt_version_id + gemini + gemini-3.5-flash recorded, meeting `ready`, latency 7.5s |
| AC-S4-3 action items | PASS live - meeting f2d20cfe extracted 3 action_items rows; toggle both directions unit-tested |
| AC-S4-4 language honoured | PASS live - minutes_language=zh regenerate produced v2 in Chinese (会议主要讨论了人生的意义...) while v1 English and the verbatim transcript remain untouched |
| AC-S4-5 LLM resolution | PASS live via tenant connection (ai-meeting); env-default and fail-closed paths unit-tested |
| AC-S4-6 activity log | PASS live - integration_activity row source=meetings operation=minutes_generate status=success latency 7394ms |
| AC-S4-7 retry discipline | Unit-tested (one corrective retry on shape failure, transport failure never retries, no partial row) |
| AC-S4-8 versions | PASS live for append-on-rerun (v1 -> v2); PUT-creates-version + every-field assertions unit-tested |
| AC-S4-9 registry semantics | PASS - 20 tests incl. immutability probe; publish repoint + cache bust browser-verified in P2a |
| AC-S4-10 editor gating | PASS - browser-verified (platform admin full flow incl. publish + revert; tenant user: no menu, NoPermission page). Screenshots /tmp/meetings-s4-p2a-*.png |
| AC-S4-11 ten meetings | PARTIAL - minutes generated for the 3 real meetings that exist (734759ad, f2d20cfe, b52930dc; results below). The remaining volume arrives with the Sep 2-4 gate recordings; each new meeting exercises the auto chain end to end |
| AC-S4-12 registration | PASS by construction - handler registered in the module both workers import; worker restart note added to DEPLOY.md; pilot workers restarted on S4 code |
| AC-S4-13 regenerate | Endpoint + 409 unit-tested; live appends proven via job-level re-runs |

Batch results: f2d20cfe -> minutes v1, 3 action items, 8.8s; b52930dc -> minutes v1, 0 action
items, 4.0s; both meetings `ready`. Three for three real meetings, zero failures.

## Environment fixes made along the way (pre-existing, this lane)

- FE `.env.local`: NEXTAUTH_URL/BASE_URL/NEXT_PUBLIC_API_URL pointed at dead :3051, backend URLs
  at :8051, NEXTAUTH_SECRET mismatched the backend JWT_SECRET. All fixed to :3001/:8001/matching
  secret; these silently broke auth + API calls for every AI settings page in this worktree.

## Open

- AC-S4-11 full count: run the auto chain on the Sep 2-4 gate meetings (no code work; volume).
- Phase 3 opus review: DONE - 1 blocker (db.query in router), 8 should-fixes, 3 doc drifts,
  3 test gaps, 7 nits. ALL applied except three recorded as deviations/notes with named
  triggers (structured output_schema mode, Resource-shell list, index-vs-constraint noise).
  Post-fix: scoped 299 green, final full suite result appended below before PR.
