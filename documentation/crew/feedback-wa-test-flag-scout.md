# FEEDBACK-WA-TEST-FLAG - scout notes

Lane: why a real WhatsApp feedback filing (FB-0022) shows no Share / Follow button.

## Shared Service side (origin/main b0a55d2a)

- Share + Follow are hidden only for `idea.isTest`
  (`service_frontend/components/platform/idea-portal/idea-page.tsx`), and the
  backend refuses test items (`services/portal.py` `_follow_target`,
  `services/share_links.py` `get_or_create_share_link` / share resolve).
- SS never decides `is_test` itself. All three intake endpoints copy the
  caller's body flag verbatim (`modules/ideation/routers/intake.py:46`,
  `:89`, `:115`; schema default `False` in `schemas.py:704`, `:810`, `:834`).
  It is stamped once on the draft's creation turn and kept for the item's life
  (`services/intake.py` creation path).
- Nothing in SS can clear `is_test` on an existing item (no admin un-mark,
  no endpoint).

(Caller side + fix proposal: see the PR thread.)
