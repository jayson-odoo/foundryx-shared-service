# Test report: BR "Send to build" (lane BR-TO-CREW, branch crew/br-send-to-build, head 473cec0e)

Run 30 Sep 2026 by the tester. Evidence: `ideation-br-send-to-build-evidence/` (screenshots + `run.md`).

## Headline
First pass (10:2x) was blocked (no GitHub connection, empty Build repository). After the owner connected GitHub and set the repository, the
deferred parts were re-run on BR "Evidence run 1027" (evidence 21-30, `run.md` re-run section). GitHub issue created and closed: **jayson-odoo/crew-intake-sandbox#2**.
Defects: D1 (product create duplicate), D2 (header status stale after the Trace tab refetch). No FAIL against an AC.

## Counts
PASS 23, FAIL 0, DEFERRED 0.

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
| STB-07 | PASS | disabled state 01-*, 02-* (menu Edit, Grilling, Ready, Delete); enabled 21-*; sent state chip + "Sent 30 Sept 2026, 16:37 by Demo User" 24-* at 1280 and 375, no h-scroll; menu Edit first 26-* |
| STB-08 | PASS | 22-AC-STB-08-confirm-1280/375.png: repo jayson-odoo/crew-intake-sandbox, Linked ideas 0, "6 of 6 complete"; Cancel closes, confirm fires one send (single issue #2) |
| STB-09 | PASS | pytest test_ideation_send_to_build.py; live: 23/24-*.png toast, status Sent to build, chip "crew-intake-sandbox #2"; issue #2 created with label crew-intake, title = BR title |
| STB-10 | PASS | pytest + `gh issue view 2`: label crew-intake, six sections in template order, Linked ideas, Links, last two lines `<!-- br-id: adb23a2d-... -->` `<!-- br-product: 37068122-... -->`; chip opens new tab (25-*; GitHub shows 404 to the unauthenticated headless browser on the private repo) |
| STB-11 | PASS | pytest test_ideation_send_to_build.py; reload 26-*.png: no Send button, chip present, Edit in menu |
| STB-12 | PASS | pytest test_ideation_send_to_build.py |
| STB-13 | PASS | pytest test_ideation_br_statuses_build.py; menu on a draft BR correctly offers no send-to-build edge (02-*) |
| STB-14 | PASS | pytest (send_to_build / statuses files); admin holds the permission (button rendered) |
| STB-15 | PASS live + pytest | mint/plaintext once/Copy/Done/prefix only 05-07; row Actions > Revoke countdown 9s, row gone 08-10; revoked key -> 401 |
| STB-16 | PASS | pytest test_ideation_build_writeback.py; live: no key 401, wrong key 401 (same envelope), random BR 404, empty stage 422. Live 201 PASS in the re-run (PR+CI, seq 6; Merged, seq 7) |
| STB-17 | PASS | pytest test_ideation_build_writeback.py; live merged -> 201 statusMoved true, header Delivered after reload (29-*), menu Edit/Archived/Delete |
| STB-18 | PASS | pytest test_ideation_build_writeback.py; live: revoked key 401, unsent BR 404 (never distinguished from foreign) |
| STB-19 | PASS | empty state 03-*; after PR+CI: summary Issue #2 / Stage PR+CI / PR #1410 / Open test copy + timeline Sent, PR+CI with links (27-*, 1280+375); after merge: Stage Merged and third green Merged entry (28-*); refetch on tab switch worked (no reload needed for the Trace panel) |
| STB-20 | PASS | full run: sidebar > BR > Send > confirm > chip > issue tab > two curl events > Trace > Delivered, 1280 and 375 (21-30), no horizontal scroll |
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
- D2 (low, FE): after a `merged` event, switching tabs refetches the Trace panel (Stage Merged, green entry) but the header status still reads "Sent to build" until a full reload (28 vs 29). AC-STB-19 only requires the tab to refetch, so not an AC fail; the header/detail query is not invalidated alongside it.
- N1 (environment, resolved): first pass ran before the owner connected GitHub / set the repository.
- N2 (tooling): agent-browser CDP clicks are ignored on this build (motion wrappers); pointer-sequence dispatch via eval was used for every click.

## Left behind
BR "Evidence run 1027" (now Delivered, id adb23a2d-1c49-404e-8ec6-9a10b4c883a1). Keys evidence-1027, -b, -c all revoked; revoked key -> 401 (30-*). Sandbox issue #2 closed. Browser session brtc closed.


## Coordinator notes (30 Sep, after run 2)

- D1 (product dialog saved the product despite an invalid Build repository; second Save duplicated it) is FIXED in commit 72a5fd44 (client-side owner/repo check before create, dialog switches to edit mode if the server still rejects the repository); the run-2 mention repeats the run-1 observation.
- D2 (header keeps "Sent to build" after a merged write-back until a full reload; the Trace tab itself refetches) is recorded as backlog BL-SS-299.
- Owner hand test of PR 99 (laneboard/scripts/99.md): PASS ("ss#99 is ok").
