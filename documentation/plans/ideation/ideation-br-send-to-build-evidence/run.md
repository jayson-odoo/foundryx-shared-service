# Evidence run log, lane BR-TO-CREW (tester), 30 Sep 2026

Stack: FE http://localhost:3103, API http://localhost:8103, session `brtc` (own), tenant default, demo@example.com.
Tooling: agent-browser headless. CDP `click` did not register on the plan-23 motion wrappers, so clicks were dispatched
as pointerdown/mousedown/pointerup/mouseup/click via `agent-browser eval` on the real element (see lane-harness-gotchas).
All navigation by sidebar clicks. Test data: BR "Evidence run 1027" (id adb23a2d-1c49-404e-8ec6-9a10b4c883a1, left as draft).

Blocker found at start: `GET /integrations/connections` has NO github connection, and product Sorento CRM has an EMPTY
Build repository. Send to build cannot be enabled, so steps 2, 3, 5(c,e) were not runnable.

1. Ideation > Business requirements > New requirement > "Evidence run 1027" (Sorento CRM) > Create draft; filled Problem statement,
   Business goal, Stakeholders; Save. Header: Send to build disabled, line "Missing: Success metric, Scope, Constraints". 01-*.
   "..." menu: Edit, Grilling, Ready, Delete. 02-*. Trace tab: "Not sent to build yet." 03-*. 375: header wraps, no h-scroll.
2. Edit > filled the other 3 fields > Save. Button STILL disabled (blocker "Set the build repository on the product Sorento CRM"). 04-*.
   Click-through of the confirm dialog: DEFERRED.
3. Reload/idempotent view: DEFERRED (no issue).
4. List > Build write-back keys > name evidence-1027 > Mint: plaintext fxb_live_... shown once with Copy key; Done; reopen: row shows
   name + 8-char prefix + created only. 05-07.
5. curl (API :8103, BR above): (a) no key -> 401 {"error":{"code":"invalid_api_key"}}; (b) wrong key -> 401 same envelope;
   (c) valid key on a never-sent BR -> 404 {"detail":"Not found."} (expected 201 only after a send; DEFERRED);
   (d) random uuid -> 404; extra: stage "" -> 422 string_too_short. (e) DEFERRED.
6. Dialog row Actions > Revoke: toast "Revoking in 9s" with Cancel, then row gone ("No keys yet."); curl with the revoked key -> 401. 08-10.
7. Products > Sorento CRM > Actions > Edit: fields "Product domain base" and "Build repository" present, Build repository EMPTY (not changed;
   Cancel). 11. Add product "Evidence product 1027" kind Software, Build repository "not-a-repo" > Add product: inline
   "Enter the build repository as owner/repo." 12. Then set jayson-odoo/evidence-throwaway > Add product: dialog closed, and the list
   showed TWO "Evidence product 1027" rows (DEFECT, 14). Both deleted via row Actions > Delete (countdown), Sorento CRM untouched.
8. Settings > Integrations: no GitHub row (DEFERRED). Connect integration > provider picker lists "GitHub" (16). Nothing saved, Test not pressed.

Backend: `cd service_backend && .venv/bin/python -m pytest -q tests/test_ideation_send_to_build.py tests/test_ideation_build_writeback.py
tests/test_ideation_build_repo.py tests/test_ideation_br_statuses_build.py tests/test_ideation_github_provider.py` -> 236 passed, 12 warnings in 50.10s.
Owner BRs (a9d14956..., c9ea6d12...) and the existing connections untouched. My key was revoked. No GitHub issue was created, so none closed.
