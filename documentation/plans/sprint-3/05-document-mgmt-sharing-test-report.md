# Sprint 3 · Plan 05 - Document Sharing - Test Execution Report

**Feature:** Share links (Google-Drive model) + the public/scoped surfaces + the policy ceiling + the `file_links` polymorphic seam.
**Plan:** `05-document-mgmt-sharing.md` · **UAT:** `05-document-mgmt-sharing-uat.md`
**Branch:** `sprint-3/05-document-mgmt-sharing` · **Stack:** FastAPI :8001 + Next :3001, native Postgres.

## Design (post-grilling redesign - Google-Drive semantics)

The original "mint a new token per tier/capability" model was reworked to match Google Drive (user direction):

1. **One stable link per resource.** A file/folder has exactly one `file_shares` row; the `token` (URL) never changes. The owner edits it in place - **General access** (`Restricted` · `Anyone in the workspace` · `Anyone with the link`) + a role, plus an additive **People with access** list where **each person has their own View/Edit role**. Flipping "Anyone with the link" → "Restricted" keeps the same URL; the public simply stops being able to open it.
2. **Public surface = a real mini-Drive** (`ShareBrowser`): card/list toggle, folder navigation within the shared subtree, click-to-preview (image/PDF), download - the same look as the internal Drive but sandboxed to the shared item (no other app navigation). A public-edit folder also gets an Upload affordance.
3. **Workspace / named-people links route INTO the app, scoped.** A signed-in authorized member opening the link lands on `/documents/shared/{token}` - the real app shell, but showing **only the shared subtree**, never the whole tenant Drive. Anonymous on such a link → a "Sign in to access" page (signed-in members are auto-routed in).

## Summary

| Layer | Suite | Result |
|---|---|---|
| Backend | `tests/test_document_sharing.py` (22 cases, Google model) | ✅ 22 passed |
| Backend | full `pytest -q` (regression) | ✅ (see run) |
| Frontend | `share-dialog.test.tsx` (3) | ✅ 3 passed |
| Frontend | `document-service.mock.test.ts` (regression) | ✅ 10 passed |
| Frontend | typecheck `tsc --noEmit` (sharing files) | ✅ clean |
| E2E | `e2e/documents-sharing.spec.ts` (4 journeys, live) | ✅ (see run) |

## Backend pytest → UAT mapping

| Test | Covers |
|---|---|
| `test_ensure_is_idempotent_stable_token` | one stable link per target; dialog get-or-create |
| `test_flip_access_keeps_same_link` | **Google stability** - flip access keeps the token; public loses access on flip |
| `test_public_blocked_when_ceiling_off` / `test_public_edit_clamped_when_view` | ceiling clamp at update (AC-SEC-02, SHARE-E1/E2) |
| `test_public_edit_requires_manage` | AC-SEC-06 / SHARE-E3 |
| `test_ensure_requires_share_permission` | AC-PERM / SHARE-E4 |
| `test_people_cross_tenant_rejected` | AC-SEC-04 / SHARE-E5 |
| `test_revoke_then_reensure_reenables_same_token` | oversight kill-switch + re-open behaviour (AC-REVOKE, REVOKE-E1) |
| `test_oversight_one_row_per_target` | AC-OVERSIGHT-01/02 (one row per shared target) |
| `test_public_unknown_token_404` | AC-SEC-01 / PUBLIC-E1 |
| `test_public_file_view_and_csp_serve` | AC-PUBLIC-01, AC-SERVE-01, PUBLIC-E4 |
| `test_public_folder_live_follow_and_ancestry` | AC-PUBLIC-02, AC-FOLLOW-01/02 |
| `test_follow_soft_deleted_path_unreachable` | FOLLOW-E1 |
| `test_ceiling_flip_off_disables_public` | PUBLIC-E2 (public clamped → sign-in-required) |
| `test_password_gate_and_throttle` | AC-PUBLIC-03, own throttle bucket |
| `test_workspace_access_and_outsider_and_anon` | AC-INTERNAL-01/02/03 (anon = sign-in-required) |
| `test_named_people_per_person_role` | AC-USER-01/02 + **per-person roles** |
| `test_public_edit_upload_*` (honeypot/sniff/audit/version/cap/view-denied) | §8 AC-WRITE + gates |
| `test_file_links_crud_and_tenant_scope` | AC-LINK-01/02, X-E1 |

## E2E journeys (`documents-sharing.spec.ts`, real clicks)

| # | Journey | Criteria |
|---|---|---|
| ① | Workspace link (one stable URL) → logged-out = "Sign in to access"; the signed-in member is routed into the in-app **scoped** view (only the shared item). | AC-INTERNAL-01/02, scoped-view direction |
| ② | Public + Viewer file → anonymous branded mini-Drive (preview + Download), verified at **375px**. | AC-PUBLIC-01, responsive |
| ③ | Public + Editor folder → anonymous upload appears live in the anon grid AND the owner's Drive. | AC-WRITE-01, AC-FOLLOW-01 |
| ④ | Oversight lists the link; **revoke** (kill-switch) → the public URL 404s on reload. | AC-OVERSIGHT, AC-REVOKE |

## Follow-up round (UX polish - user-driven)

- **"Shared with me" drive** - a top-level section in the Documents Drive left nav (sibling of Drive/Trash). `GET /documents/shared-with-me` lists roots others shared *to* the user (excludes their own shares + anything they can't open); opening a root navigates to its scoped view. Backend test `test_shared_with_me_lists_others_excludes_own`.
- **Workspace/named-people links open inside All-documents → "Shared with me"** (not a separate page). The standalone `/documents/shared/{token}` scoped page was **removed**; a workspace link routes a signed-in member to `/documents?shared={token}`, which opens the Shared-with-me section with that item browsing in place (`SharedItemView` → `ShareBrowser`). Sign-in `callbackUrl` points there too. The public (anonymous) page keeps the two-pane `ShareScopedView` look.
- **Preview fixes** - the PDF iframe dropped its restrictive `sandbox=""` (was rendering blank) in both the Drive and share previews; the preview modal header reserves room (`pr-14`) so Download no longer collides with the dialog's close (X).
- **Sign-in CTA** - the "Sign in to access" page now always shows a Sign in button (routes to `/signin?callbackUrl=…`); a signed-in member is still auto-routed into the scoped view.

## Notes

- "Revoke" on the oversight page is the hard kill-switch (`is_disabled` → uniform 404). In day-to-day use, setting **General access = Restricted** is the Google-style way to cut public access while keeping the link for named people.
- BL-101-105 remain out of scope as planned.
