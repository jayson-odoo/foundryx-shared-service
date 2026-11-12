# AutoCount write-back (engineering note)

Contracts of record: `documentation/plans/sprint-5/55-autocount-write-link-contract.md` and `57-autocount-write-qtso-contract.md`. Plan 63: `sprint-5/63-autocount-db1-ready.md`.

- **Optional AutoCount API key.** The autocount connection (auth = none) may carry `apiKey` (secret, encrypted at rest), `apiKeyHeader` (default `X-API-Key`), `apiKeyFormat` (default `{key}`; `Bearer {key}` allowed) and `apiKeyOnReads` (No/Yes, default No: reads carry the header only when Yes). Code: `modules/autocount/write_back/auth.py`. The connection is resolved per action with no cache, so a rotated key applies from the next action. The key is never logged or echoed; an invalid configuration is refused before sending (`AUTH_CONFIG_INVALID`, no value in the text). The CRM never sends or sees it.
- **Write books.** Writes outside the test book are accepted only from the production deploy, with the books listed in `AUTOCOUNT_WRITE_ALLOWED_BOOKS`; `write-capabilities` (57 section 7) reports the effective `book`.
- **Acting user.** Optional `X-Acting-User-Id` and `X-Acting-User-Name` (57 section 2a.1) are stored with `X-Request-ID` on the write action rows and the call log (`write_back/call_log.py`, `person_of`). Invalid or absent = stored empty, never a refusal.
- **AutoCount > Calls.** Read-only view of the per-call log (server-side sort and filter, request and response detail), behind the JWT prefix.
