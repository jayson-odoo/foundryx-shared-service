# Slice 18 — workflow test-trigger data test report

Date: 2026-08-26  
Scope: `18-workflow-test-trigger-data.md` / `18-workflow-test-trigger-data-acceptance-criteria.md`

## Execution summary

The focused slice suites and the clean frontend production build are green.
The full frontend lint command still reports unrelated baseline errors outside
this slice.

Commands run from the repository worktree:

| Command | Result |
|---|---|
| `cd service_backend && source .venv/bin/activate && python -m pytest -q tests/test_workflow_test_trigger_data.py` | **PASS** — 17 passed, 13 dependency deprecation warnings, 16.14s |
| `cd service_frontend && npm test -- --run app/'(protected)'/workflows/components/run-dialog.test.tsx app/'(protected)'/workflows/components/use-workflow-form.test.tsx services/workflow-service.real.test.ts` | **PASS** — 3 files, 9 tests |
| `cd service_frontend && npx eslint 'app/(protected)/workflows/components/run-dialog.tsx' 'app/(protected)/workflows/components/use-workflow-form.tsx' 'app/(protected)/workflows/components/run-dialog.test.tsx' 'app/(protected)/workflows/components/use-workflow-form.test.tsx' 'components/platform/workflow-runs/run-replay.tsx' 'components/platform/workflow-runs/workflow-runs.tsx' 'components/ui/accordion-menu.tsx' 'services/workflow-service.real.ts' 'services/workflow-service.ts' 'services/workflow-service.real.test.ts' 'types/workflows.ts' 'e2e/workflow-test-trigger.spec.ts'` | **PASS** — no output/errors |
| `cd service_frontend && mv .next /tmp/foundryx-service-frontend-next-verify-2 && npm run build` | **PASS** — fresh production build; compiled, type-checked, generated 111 static pages, and completed route optimization. One existing invalid CSS media-query warning. |
| `cd service_frontend && npm run lint` | **FAIL (baseline/unrelated)** — 11 errors in existing cluster-e/terminology E2E helpers and import mock; 3 unrelated warnings. No slice-18 file reported. |
| `git diff --check` | **PASS** |

The full backend command `cd service_backend && source .venv/bin/activate &&
python -m pytest -q` was started but stopped after reaching approximately 31%
because it produced broad pre-existing failures in `tests/test_autocount_pipeline.py`
(window assertion/activity-log expectations) and SQLite module-schema bootstrap
errors. The focused slice suite remained green.

The implementation handoff also reports:

* `npx playwright test e2e/workflow-test-trigger.spec.ts` — **PASS**, 2 real-click
  tests at 1280px and 375px, including stub-AI and one outbound sandbox reply.
* The Playwright run used isolated stub transport; no public webhook/inbound
  path was used.

Late review safety evidence: the sandbox-only send runner race/active-channel
focused tests are green; the Workflow Runs status filter focused RTL/ESLint
check is green and uses `SearchSelect`; and the `WorkflowService` mock
interface fix has focused test/lint/diff-check green. These are included in
the final diff and do not alter the unrelated full-lint baseline failures.

## Acceptance-criteria matrix

| AC | Evidence | Status |
|---|---|---|
| AC-OA-24 | `run-dialog.test.tsx` (6) covers trigger-aware dialog, searchable source controls, required message. | **PASS** |
| AC-OA-25 | `test_workflow_test_trigger_data.py`; request contains typed trigger IDs/message and backend derives canonical record data. | **PASS** |
| AC-OA-26 | Backend adversarial tests plus dialog state/filter tests; sandbox and tenant-scoped validation. | **PASS** |
| AC-OA-27 | Backend provenance assertions (`is_test`, draft version null/zero) and run-list UI coverage. | **PASS** |
| AC-OA-28 | Backend canonical context/output assertions in focused suite. | **PASS** |
| AC-OA-29 | Focused backend assertions verify no inbound persistence/public dispatch/fan-out. | **PASS** |
| AC-OA-30 | Backend action path plus frontend warning coverage; live E2E reports stub AI and one sandbox outbound reply. | **PASS** |
| AC-OA-31 | Focused backend suite rejects blank/oversized, forged/cross-tenant, stale, inactive, trashed, non-sandbox, and mismatched data before run creation. | **PASS** |
| AC-OA-32 | `run-dialog.test.tsx` and `use-workflow-form.test.tsx` cover prerequisite/empty states, reset, exact request, and manual regression. | **PASS** |
| AC-OA-33 | Backend 17 focused pytest + frontend 9 focused Vitest green; RED/GREEN test files are present in the diff. | **PASS** |
| AC-OA-34 | Reported real-click Playwright PASS at 1280px and 375px; fresh `npm run build` now passes after the mock interface fix. | **PASS** |

## RED/GREEN evidence and follow-up

The new backend and frontend test files are present as the RED-first tracers
and pass against the implementation (GREEN). The mock service now conforms to
the interface, and the fresh build confirms the production typecheck. This
verification agent made no product-code changes.
