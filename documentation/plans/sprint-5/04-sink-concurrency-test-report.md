# Per-connection Sorento push concurrency - test execution report

Lane `feat/sink-concurrency-ui` (off `fix/push-marks-per-chunk` 73ffba71). Coder commits: `073fa931` (sink + provider), `688e2fec` (frontend `effectiveValue` fallback), `210fdb4b` (docs). Tester commits: `51670259` (red tests), `6ac02fc2` + `a736a6c3` (field-order pins), this report.

Verified 2026-09-07 by the tester seat, from the user's perspective, on a fresh production build of the worktree frontend (`:3004`) against the worktree backend (`:8004`), shared local Postgres, demo tenant (`demo@example.com`). Browser = `agent-browser` headless, viewports 1280x800 and 375x812. Evidence: `04-evidence/sink-concurrency/`.

## Verdicts (one line per contract line of the brief)

| # | Contract line | Verdict | Evidence |
|---|---|---|---|
| AC-SC-01 | `sorento_provider.fields()` gains a select `sinkConcurrency` (`SINK_CONCURRENCY_KEY`), options `1..4` labelled `1 (sequential)`, `2`, `3`, `4`, no stored default | PASS | `GET /integrations/providers` on :8004 returns the field with those labels and no `defaultValue`; unit `test_provider_exposes_the_sink_concurrency_select_without_a_stored_default` |
| AC-SC-02 | Unset = platform default (`settings.autocount_sink_concurrency`), shown in read mode as the effective value (`storedOrEffective` pattern) | PASS | Read mode with nothing stored shows `Push concurrency: 1 (sequential)` (02, 1280); the provider field carries `effectiveValue "1"`; vitest `an unset value shows the EFFECTIVE platform default the field carries` |
| AC-SC-03 | Edit form offers the select with `1 (sequential)`..`4` | PASS | 03 (1280, list open: `1 (sequential)`, `2`, `3`, `4`), 09 (375, list open) |
| AC-SC-04 | Save `2`; read mode shows `2` | PASS | `PATCH /integrations/connections/<id>` 200, toast `Connection saved.`, read mode `Push concurrency: 2` (04 at 1280, 07 at 375); API row `sinkConcurrency: "2"` |
| AC-SC-05 | Edit again, clear/unset if the UI allows, read mode shows the effective platform default | N/A (UI has no unset) | The `SearchSelect` has no clear affordance and the option list has no blank entry (probed in edit mode: zero sibling buttons, options exactly the four values). The effective display itself is covered by AC-SC-02 (02). Once a value is stored the operator picks `1 (sequential)` explicitly, which is the documented fallback path |
| AC-SC-06 | Set back to `1`, save | PASS | PATCH 200, toast, read mode `Push concurrency: 1 (sequential)` (06); API row `sinkConcurrency: "1"` |
| AC-SC-07 | `SorentoSink` resolves connection value if present and valid, else settings; clamped to 1..4 and `len(chunks)` | PASS | Saved-row seam check while the row held `2`: `sorento_sink_from_connection(row.config_json, ...)` then 800 records / 4 chunks -> `ThreadPoolExecutor(max_workers=2)` opened once; unit tests cover unset -> settings, call-time read, clamp to chunks, clamp to 4 |
| AC-SC-08 | Invalid stored values (`0`, `9`, `abc`, `None`) fall back to settings and warn once per sink, never raise | PASS (unit) | `test_an_invalid_stored_value_falls_back_to_settings_and_warns_once[zero/nine/abc/none/blank]` |
| AC-SC-09 | Connection PATCH with an out-of-range `sinkConcurrency` rejected 422 | N/A | No provider-level config validation hook exists on the PATCH path (`IntegrationProvider` = `fields`/`test`; `integration_service.update` merges config verbatim). Out-of-range values are pinned at the sink-side fallback (AC-SC-08). Backlog candidate |
| AC-SC-10 | `write_batch` and `delete_batch` honour it; `dry_run` unchanged | PASS | Same saved-row seam check: `write_batch` -> `[2]`, `delete_batch` -> `[2]`, `dry_run` -> `[]` (no executor); unit tests for each |
| AC-SC-11 | Tenant scoping: the sink reads the tenant's own connection row | PASS (unit) | `test_sink_for_company_reads_the_setting_from_the_tenants_own_connection`: own row's `3` used; a connection owned by another tenant referenced by the company is refused |
| AC-SC-12 | Responsive: surface verified at 375 AND 1280 | PASS with note | 07/08/09 at 375: read row, edit form and open list all usable. Note: at 375 the option list's viewport shows one item at a time with scroll chevrons (09); all four values are reachable by scrolling. Not a blocker; a taller list viewport on narrow screens would read better |

Backend unit file `tests/test_autocount_sink_concurrency_setting.py`: 15 passed. Frontend `connection-schema.test.ts`: 18 passed. Field-order pins re-run: 29 passed across the provider/concurrency files.

## Evidence index (`04-evidence/sink-concurrency/`)

| File | What it shows |
|---|---|
| `01-integrations-list-1280.png` | Settings > Integrations list with the Sorento connection row |
| `02-read-mode-unset-1280.png` | Read mode before any value is stored: `Push concurrency 1 (sequential)` (effective platform default) |
| `03-edit-options-1280.png` | Edit mode with the concurrency list open: `1 (sequential)`, `2`, `3`, `4` |
| `04-read-mode-2-1280.png` | Read mode after saving `2` |
| `05-edit-mode-2-1280.png` | Edit mode prefilled with the stored `2` |
| `06-read-mode-back-to-1-1280.png` | Read mode after setting back to `1 (sequential)` |
| `07-read-mode-2-375.png` | Read mode at 375 (value `2`) |
| `08-edit-mode-2-375.png` | Edit mode at 375 |
| `09-edit-options-2-375.png` | Option list open at 375 |

## Environment findings (fixed during this run; all outside product code)

1. **Shared local Postgres was four core revisions behind main.** Stamped `conn_erp_llm_s501`; branch head `bgjob_heartbeat_orphan` (#56). Every connection PATCH on any post-#56 backend 500'd with `UndefinedColumn: background_jobs.heartbeat_at` (raised in `_guard_not_migrating`). Fixed with `alembic upgrade head` (core only) from the worktree venv: `b7c1d2e3f4a5`, `82497a2fcea3`, `teams_core_s428`, `bgjob_heartbeat_orphan`. No reseed. Lesson recorded in `process-lessons.md`.
2. **Worktree frontend was baked against :8001.** `service_frontend/.env.local` was a symlink to the main checkout's file (`NEXT_PUBLIC_BACKEND_API_URL=:8001`, `NEXTAUTH_URL=:3001`). Replaced with a real per-worktree file (`:8004` / `:3004`, secrets copied), `rm -rf .next && npm run build`, `npm start -- -p 3004` restarted (only the process whose cwd was this worktree's `service_frontend`).
3. **CORS blocked origin :3004.** The symlinked backend `.env` sets `CORS_ORIGINS=3000,3001,3002`, overriding the code default that includes 3004; preflight from the page was 400 and every client fetch failed silently (`TypeError: Failed to fetch`, no console error). The :8004 uvicorn (cwd this worktree) was restarted with `CORS_ORIGINS` extended to include `http://localhost:3004`.
4. **agent-browser caveats on this UI.** The row Actions kebab sits off-screen at 1280 (table wider than the viewport); the connection form is a route (`/settings/integrations/<id>?edit=1`), so navigation was used instead. The `SearchSelect` popover did not open on synthesized clicks/keyboard; a DOM `click()` on the trigger and on the cmdk option element did, and the option list was then confirmed through the accessibility tree (`listbox` with four `option` nodes). The Save button (`type=submit`, not inside a `form`) submitted only via a DOM `click()`; locator clicks produced no request. Screenshots and the PATCH log lines are the evidence, not the click mechanism.
5. `lsof -ti :PORT` lists client sockets too (the headless Chrome helper connected to :3004 showed up); filter with `-sTCP:LISTEN` before killing anything.

## Residue

The `Sorento Local (SRT proof)` connection (`ac444945-...`) now stores `sinkConcurrency: "1"` (it had no value before); behaviour is identical to unset. Two servers were restarted in this worktree: frontend `:3004` (pid of `npm start`) and backend `:8004` (uvicorn with the extended `CORS_ORIGINS`); the worktree's `.env.local` is now a real file (gitignored). The local Postgres is at core head `bgjob_heartbeat_orphan`.
