# Plan 49: callback URL check before database work on key routes

UAC: `49-key-url-check-first-acceptance-criteria.md`. Size S. Branch `crew/ss-key-url-check-first`.

| Area | File | Change |
|---|---|---|
| Key routes | `modules/omnichannel/routers/api_v1.py` (create, PATCH), `services/webhook_service.py` (`create`, `update`) | Check the URL before the first query, or release the read transaction before the check; keep plan 43's lock order after it |
| Tests | new test file | Spy on the URL check and assert no transaction or checked-out connection at that moment |
| Proof | real server, slow resolver | Before and after numbers |

Slices: S1 tester red, coder. S2 lead real-server proof. S3 reviewer plus security-reviewer.
