# S6 evidence run log - issue #94 ideation round 2

Lane: DB `foundryx_service_ir2` (Postgres localhost:5432), Redis db 5, backend :8016, frontend :3016 (`npx next start -p 3016`, standalone build warning is harmless). All timestamps in this run use `20260928-1218` (UTC-ish tag) for created names.

## Bootstrap (AC-94-18 live run)

```
DATABASE_URL=postgresql://foundryx:foundryx@localhost:5432/foundryx_service_ir2 REDIS_URL=redis://localhost:6379/5 \
ENVIRONMENT=development CELERY_TASK_ALWAYS_EAGER=true THROTTLE_IP_MAX_FAILS=200 \
.venv/bin/python -m scripts.bootstrap_db
```
Tail of output:
```
ideation: grill agent seeded for 0 tenant(s)
omnichannel: demo conversations seeded
omnichannel: demo AI workflow seeded
omnichannel: demo progress-update workflow seeded
bootstrap complete: migrated + seeded + modules
```
Confirmed live: `select version_num from app_ideation.alembic_version_ideation;` -> `0012_ideation_merge_rank_events` (31 chars, matches AC-94-18).

## Environment corrections needed for this lane (not product bugs)

- `service_frontend` had no `.env.local` in this worktree; started `next start` with `NEXT_PUBLIC_BACKEND_API_URL`/`BACKEND_API_URL=http://localhost:8016`, `NEXTAUTH_URL=http://localhost:3016`, `NEXTAUTH_SECRET=<reused main checkout's dev secret>` as env vars (no file written).
- Backend `cors_origins`/`cors_origin_regex` default to ports 3000-3005; this lane runs 3016, so the backend was started with `CORS_ORIGINS` widened to include `http://localhost:3016` and `CORS_ORIGIN_REGEX` widened to `30[0-9][0-9]`. Without this the App Store catalog (and everything else cross-origin) silently renders "No records" (preflight `OPTIONS` 400) - this is an env-only fix, not a code change.
- Ideation module was NOT installed for the seeded `default` tenant; installed through the UI (App Store card > Install) as instructed. `omnichannel` was already ACTIVE (dev seed).
- `agent-browser click @ref` intermittently no-ops on this build's motion-wrapped dialogs/menus (same class of issue as the documented plan-23 motion-wrapper gotcha) - worked around with a `pointerdown->mousedown->pointerup->mouseup->click` dispatch via `agent-browser eval` on the located element when a plain ref-click did not change page state (verified by re-snapshotting/checking network before treating a click as landed).

## Test data setup (API calls per the brief; journeys themselves are clicks)

- Product `E2E Product 20260928-1218` (Good) and `E2E Software Product 20260928-1218` (Software, delivery base set) created via UI/API.
- 8 ideas Alpha..Hotel captured via the UI capture dialog (real product picks), landing at priority 1..8 (AC-94-44 confirmed live).
- One WhatsApp-style captured idea (`E2E Idea 20260928-1218 WhatsApp Merge Target...`, requester `+60191234567`) minted via the real multi-turn `POST /ideation/intake/create-idea` flow (workspace API key minted through the omnichannel workspace's own "API keys" endpoint, called with curl) - problem -> proposed_solution -> impact -> confirm, exactly mirroring `tests/test_ideation_intake_contract.py`'s `_complete_flow` helper. Became `IDEA-0001`, track link token `ePbI7viDzuWJ47FrR9hlRAIwJTxASJQB`.
- Idea `India` captured on the Software product to give the WhatsApp idea a same-product merge partner (AC-94-04 rejects a cross-product merge - confirmed this rule holds: Golf/Hotel on the other product were NOT selectable survivors for the WhatsApp idea).
- A dedicated tenant `e2eideation1218` (slug) was provisioned via the platform operator API (`POST /platform/tenants`, platform admin `platform@example.com`) for AC-94-59 (the rename forks the tenant's status set). Ideation + omnichannel installed for it via the platform module-install API. One WhatsApp-style idea (`IDEA-0005`, requester `+60197654321`) captured the same way for that tenant, to have a real "New" idea to advance/rename-check.
- An ideation embed connection (`e2e-embed-20260928-1218`, no product scope) was created through Ideation > Embed connections (UI). The host assertion (JWT, `iss=sorento`, `aud=ideation-embed`, `typ=assertion`, short `exp`) was minted locally with `python-jose` using the connection's own plaintext signing secret (shown once at creation) and exchanged via `POST /embed/session` for a short-lived embed token, then that token was placed in the `#token=` URL fragment to open `/embed/ideas` - this is the same handshake `docs/reference` describes the host (sorento) performing; nothing here bypasses verification (a wrong secret / wrong issuer / wrong audience was confirmed to be rejected with `invalid_assertion` while building this).

## Screenshots

See file names `AC-94-NN-*-{1280,375}.png` in this directory, one pair (at least) per AC. `_debug_*.png` are working screenshots from diagnosing the App Store/CORS issue above, kept for transparency.

## status-events feed (AC-94-61..66 live curl)

After: unmerge IDEA-0001 -> stage move IDEA-0001 (New -> Triaged) -> re-merge IDEA-0001 into IDEA-0004, waited >5s (settle window) then:

```
GET /ideation/intake/status-events?after=0&limit=100   (default tenant workspace key)
```
Returned, in ascending `seq` order: `merged` (seq 1, the earlier merge into India) -> `unmerged` (seq 3) -> `status_changed` (seq 4, `from_status_label: "New"`, `status_label: "Triaged"`) -> `merged` (seq 5, `merged_into: {ideaNumber: IDEA-0004, title: India}`). Exact key set on every row: `event_id, seq, kind, occurred_at, idea_id, idea_number, idea_title, product_id, status_label, from_status_label, track_url, requester_phone, merged_into, separated_from, is_test` - matches AC-94-63 field for field. `seq=2` is absent from this tenant's feed (it belongs to the OTHER tenant's stage-move event below), which is itself evidence the sequence counter is shared but the feed is correctly tenant-scoped (AC-94-66).

The SAME query with the dedicated tenant's own workspace key returned exactly one row, `seq=2`, `status_changed`, `from_status_label: "New"`, `status_label: "Discussed-20260928-1218"` (the renamed status, AC-94-50/59 cross-validated through the event feed independently of the UI).

Full JSON captured in this session's scratchpad; reproduced verbatim in the test report.

## Known FAIL found during this run (not fixed - tester does not touch app code)

**The Triage board page crashes** (`Ideation > Triage board`, both the `default` tenant with real captured ideas and the dedicated `e2eideation1218` tenant) with a client-side exception (`TypeError: Cannot read properties of undefined (reading 'map')`, thrown from a shared vendor chunk, not an ideation-owned source file per the visible stack) immediately on render, showing the app's generic "Something went wrong" error boundary. The `GET /ideation/ideas/board` API response itself is well-formed (columns array present, each column carries a `ideas` array, checked by hand against the AC-94-54 shape) - the failure is in the frontend board render/Kanban wiring, not the API. This blocks the board-column visual leg of AC-94-59 and the board surface of AC-94-58/AC-94-74 (screenshot `AC-94-58-board-crash-1280.png`). Confirmed independently correct via the API response and via the status-events feed that the renamed label does reach the data layer.
