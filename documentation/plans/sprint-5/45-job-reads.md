# Plan 45: job reads and stored crash text

UAC: `45-job-reads-acceptance-criteria.md`. Size S to M, no migration, no new permission. Branch `crew/ss-jobs-read`.

## Design

```text
JobHandlerDef(..., read_permission="<module>.<key>")      app/jobs/registry.py
readable_job_types(user) -> set of types whose key is in effective_permission_keys(user)
GET /jobs        -> JobService.list(tenant, types=readable)      empty set -> empty page
GET /jobs/{id}   -> JobService.get(tenant, id); type not readable -> 404 "Job not found."
crash            -> "Job crashed (<ClassName>)."                 app/jobs/service.py
```

## Changes

| Area | File | Change |
|---|---|---|
| Registry | `app/jobs/registry.py` | `read_permission: Optional[str]`; a helper that returns the readable types for a key set |
| Handlers | 14 `JobHandlerDef(` sites | Name the key per AC-45-06 |
| Router | `app/api/v1/jobs.py` | Pass the readable types; no query in the router |
| Service | `app/jobs/service.py` | `list` filters by type set; crash text |
| Tests | new `tests/test_job_reads.py` | Per AC; a registry test over every registered def |

## Traps

- Module handlers register on module load: the registry test must load every module the app loads.
- An empty readable set must not mean "no filter".
- Tenant scope stays as it is; the type filter is added, never replaces it.
- Platform operators read their own tenant's jobs by the same rule.

## Slices

| Slice | Who | Content |
|---|---|---|
| S1 | tester, coder | Red for AC-45-01..07, then code |
| S2 | lead | Kill, targeted mutation |
| S3 | reviewer, security-reviewer | One round |
| S4 | tester | AC-45-08 |
