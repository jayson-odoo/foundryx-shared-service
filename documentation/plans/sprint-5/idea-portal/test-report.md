# IDEA-PORTAL test execution report

Branch `crew/idea-portal`, PR #123. Run on 13 Oct 2026.

Environment: a sandbox with Postgres 16 and Redis. Backend on :8001. A freshly rebuilt production frontend on :3001.

Data:
- Real ideas IDEA-0010 and IDEA-0014.
- Filler ideas IDEA-S01..S04, tagged `[sample]`.

Browser pass:
- Real clicks with Playwright and Chromium.
- 1280 and 375 px.
- Screenshots in `evidence/browser/`.

Automated:
- Backend `tests/test_ideation_portal.py`: 40 tests.
- Wider backend regression run: 1251 passed.
- Frontend: idea-portal component, service and auth tests, the sign-in page and `safe-callback` (76 tests), plus every `*inventory*` and `*guard*` test.

Migration 0017: verified on Postgres. See `evidence/migration-0017-postgres.md`.

| AC | Result | Evidence |
|---|---|---|
| AC-P-01 staff session | PASS | `test_ac_p_01_*`, `test_sec_staff_without_manage_is_not_manager`. Browser: Staff sign in leads to the Roadmap. |
| AC-P-02 Sorento CRM session | PASS | `test_ac_p_02_*`. Browser: `/embed/ideas/portal#token=` shows the roadmap with no tenant header (`p-embed-*.png`). |
| AC-P-03 no dealer sign-in | PASS | `test_ac_p_03_no_dealer_sign_in` (owner Q1) |
| AC-P-04 portal token only | PASS | `test_ac_p_04_*`: missing, core, expired and forged tokens, module inactive; a portal token can't reach staff endpoints. |
| AC-P-10 visibility | PASS | `test_ac_p_10_*`: draft, test, merged child (resolves to the survivor), other tenant, CRM product scope. |
| AC-P-11 hidden | PASS | `test_ac_p_11_*`. Browser: the "Hide from portal" switch toggles. |
| AC-P-12 managers | PASS | `test_ac_p_02_crm_session`, `test_sec_crm_manager_only_when_claim_is_true`, `test_sec_staff_without_manage_is_not_manager` |
| AC-P-20 roadmap columns | PASS | `test_ac_p_20_*`. Browser: Under review 3 / Planned 1 / In progress 1 / Complete 1. |
| AC-P-21 unmapped status | PASS | `test_ac_p_21_*` |
| AC-P-22 cards, mine | PASS | `test_ac_p_22_*`, `test_review_staff_owns_what_they_submit` |
| AC-P-30 feedback list | PASS | `test_ac_p_30_*`, `test_sec_column_list_capped`. Browser: 6 rows. |
| AC-P-31 submit | PASS | `test_ac_p_31_*`, `test_sec_submit_throttled`. Browser: submitted "Dealer delivery photo proof" → idea page, New, "Your idea". |
| AC-P-40 changelog | PASS | `test_ac_p_40_*` |
| AC-P-41 changelog note | PASS | `test_ac_p_41_*`. Browser: a note saved on the delivered idea shows on the Changelog. |
| AC-P-50 idea page | PASS | `test_ac_p_50_*` (no PII or dropped fields), component tests. Browser: the Business problem shows. |
| AC-P-51 vote | PASS | `test_ac_p_51_*`, `test_review_legacy_down_vote_switches_to_up`. Browser: upvote 0 → 1. |
| AC-P-52 voters | PASS | `test_ac_p_52_*`, `test_review_whatsapp_voter_is_a_dealer` |
| AC-P-53 comments | PASS | `test_ac_p_53_*`, `test_sec_comment_author_first_name_only`. Browser: comment, reply, like. |
| AC-P-54 activity | PASS | `test_ac_p_54_*`, including a real status transition through the bus subscriber, and `groupFeed` (local-day upvote grouping). |
| AC-P-60 layout | PASS | No horizontal scroll: scrollWidth was 1280 at 1280 and 375 at 375 on roadmap, feedback, changelog and idea pages. |
| AC-P-61 sign-in screen | PASS | Browser `p-signin-1280.png`. The sign-in page now honours a same-origin `callbackUrl` (unit test includes open-redirect cases). |
| AC-P-62 Sorento iframe | PASS | Browser: embed roadmap, open IDEA-0014, upvote. |
| AC-P-63 E2E pass | PASS | The full script above, run from the user's view with real clicks. |
| AC-P-70 security review | PASS | Findings 1-6 fixed in `da2f7f96`. See the open items below. |

## Open / accepted

- **No server-side revocation list for portal tokens.** They are bounded instead:
  - staff tokens last 12h, are bound to the signed-in staff user on the client, and the user and permission are re-checked on every request;
  - CRM tokens last 2h, and the embed connection is re-checked on every request.
- **Ideas created before this change have no `submitter_user_id`.** Operator-created rows only stored a name, so they don't show "Yours" for staff. Ownership is never inferred from a name.
- **Status history before the deploy is partial.** It only exists for ideas whose requester had a phone, because that is all `idea_status_events` recorded. The backfill copies everything that exists.
- **Sorento side:** point `components/ideas/IdeationEmbed.tsx` (or a new tab) at `/embed/ideas/portal`. Sorento CRM users get manager rights only when Sorento sends `ideas_manage: true`.
- **IDEA-CORE fields:** Desired outcome, Use cases and Current workaround are read from IDEA-CORE's columns once they ship (`desired_outcome`, `use_cases`, `current_workaround`), and from `captured_json` until then.
