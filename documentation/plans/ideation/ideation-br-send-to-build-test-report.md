# Test report: BR "Send to build" (lane BR-TO-CREW, branch crew/br-send-to-build, head 473cec0e)

Run 30 Sep 2026 by the tester. Evidence: `ideation-br-send-to-build-evidence/` (screenshots + `run.md`).

## Headline
The live Send flow could NOT run: the copy has no GitHub connection and the Sorento CRM product has an empty Build repository
(the brief said it was set; it is not). AC-STB-08/19(populated)/20 are DEFERRED and the live halves of 09/10/11/17 are unproven; the blocker is the owner pasting the
GitHub token (Settings > Integrations > Connect integration > GitHub) and typing jayson-odoo/crew-intake-sandbox into the product's
Build repository. One real defect found (product create + invalid Build repository, see D1).

## Counts
PASS 20, FAIL 0, DEFERRED 3 (AC-STB-08, 19, 20). Several PASS rows are pytest-only with the live half deferred (09, 10, 11, 17, 07 chip state), flagged in the table.

## Suites
`cd service_backend && .venv/bin/python -m pytest -q tests/test_ideation_send_to_build.py tests/test_ideation_build_writeback.py tests/test_ideation_build_repo.py tests/test_ideation_br_statuses_build.py tests/test_ideation_github_provider.py`
-> `236 passed, 12 warnings in 50.10s`. Frontend vitest NOT run (crew rule: no frontend runs in the lane worktree while the copy is up; CI covers it).

## AC table
| AC | Result | Evidence |
|---|---|---|
| STB-01 | PASS | pytest test_ideation_build_repo.py (236 passed); live 422 inline on "not-a-repo": 12-AC-STB-02-invalid-repo-1280/375.png |
| STB-02 | PASS (with D1) | field present next to Product domain base, empty on Sorento CRM: 11-*.png; inline error 12-*.png; valid save 13-*.png; no help copy. Defect D1 on create |
| STB-03 | PASS | pytest test_ideation_build_repo.py |
| STB-04 | PASS | pytest test_ideation_github_provider.py; live: GitHub in the provider picker (16-*.png); no active connection row to inspect (needs the owner token) |
| STB-05 | PASS | pytest test_ideation_github_provider.py (live Test not run: no connection) |
| STB-06 | PASS | pytest test_ideation_send_to_build.py; live blockers render: "Missing: Success metric, Scope, Constraints", then "Set the build repository on the product Sorento CRM" (01-*, 04-*) |
| STB-07 | PASS (disabled state) | 01-*, 02-* (menu: Edit, Grilling, Ready, Delete) at 1280 and 375, no h-scroll. Chip state not seen live (needs a sent BR) |
| STB-08 | DEFERRED | button never enabled (no GitHub connection, no repo). Blocker above |
| STB-09 | PASS (pytest) / live DEFERRED | pytest test_ideation_send_to_build.py; no issue created in crew-intake-sandbox |
| STB-10 | PASS (pytest) | pytest test_ideation_send_to_build.py; `gh issue view` not possible, no issue |
| STB-11 | PASS (pytest) | pytest test_ideation_send_to_build.py; UI reload check DEFERRED with 09 |
| STB-12 | PASS | pytest test_ideation_send_to_build.py |
| STB-13 | PASS | pytest test_ideation_br_statuses_build.py; menu on a draft BR correctly offers no send-to-build edge (02-*) |
| STB-14 | PASS | pytest (send_to_build / statuses files); admin holds the permission (button rendered) |
| STB-15 | PASS live + pytest | mint/plaintext once/Copy/Done/prefix only 05-07; row Actions > Revoke countdown 9s, row gone 08-10; revoked key -> 401 |
| STB-16 | PASS | pytest test_ideation_build_writeback.py; live: no key 401, wrong key 401 (same envelope), random BR 404, empty stage 422. Live 201 DEFERRED (needs a sent BR) |
| STB-17 | PASS (pytest) | test_ideation_build_writeback.py; live merged->Delivered DEFERRED |
| STB-18 | PASS | pytest test_ideation_build_writeback.py; live: revoked key 401, unsent BR 404 (never distinguished from foreign) |
| STB-19 | DEFERRED (populated) | empty state PASS live: "Not sent to build yet." 03-*.png at 1280 and 375. Summary card + timeline not seen |
| STB-20 | DEFERRED | full send/issue/write-back/Delivered run blocked. Partial 375+1280 coverage in 01-04, 10, 12 |
| STB-21 | PASS | pytest test_ideation_send_to_build.py |
| STB-22 | PASS | pytest test_ideation_send_to_build.py / test_ideation_build_writeback.py |
| STB-23 | PASS | documentation/engineering/ideation-build-handoff.md exists (not re-audited line by line) |

## Defects
- D1 (medium, FE): `service_frontend/app/(protected)/products/product-form-dialog.tsx` lines ~139-160. On CREATE the product is POSTed first
  (`createProduct`), then `setDelivery` runs; an invalid Build repository returns 422 AFTER the product exists. The dialog stays open on
  "Add product", so the next Save creates a SECOND product. Repro: Add product, kind Software, name X, Build repository "not-a-repo", Add
  product (inline error shown, product X already saved), fix the value, Add product again: two X rows (14-DEFECT-duplicate-product-1280.png).
  Fix: validate `^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$` client-side before createProduct, and/or after a create success switch the form to edit
  of `saved.id` when setDelivery fails. Cleanup: both duplicates deleted via the UI.
- N1 (environment): the copy's Sorento CRM Build repository is empty, contrary to the brief; not changed by me.
- N2 (tooling): agent-browser CDP clicks are ignored on this build (motion wrappers); pointer-sequence dispatch via eval was used for every click.

## Deferred / what unblocks
GitHub connection (owner token) + Sorento CRM Build repository = jayson-odoo/crew-intake-sandbox. Then re-run steps 2, 3, 5(c,e) of the brief:
send, chip, issue check via gh, write-back 201/Delivered, Trace at 375/1280, close the issue in the sandbox.

## Left behind
BR "Evidence run 1027" (draft, id adb23a2d-1c49-404e-8ec6-9a10b4c883a1). Key evidence-1027 revoked. Browser session brtc closed.
