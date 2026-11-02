# Plan 44: source rows the migration cannot read

UAC: `44-migration-unreadable-rows-acceptance-criteria.md`. Size M, no migration. Branch `crew/ss-migration-bad-rows`, after the migration form fix.

## Rulings

- A bad channel, user or contact is skipped with a preflight warning giving the count and each row's vendor id, never a name or phone.
- The dry run may still run, and its report lists what was skipped. The real run shows the same count first. Nothing is auto-mapped.
- A skipped channel blocks the real run unless the operator marks it Skip, because messages would be lost. A skipped user does not.

## Design

```text
helper: parse_rows(rows, Model) -> (parsed, unreadable_ids)
  catches pydantic.ValidationError per row; keeps no values

preflight: channels, users, fields, contact lifecycle scan use it, warnings + unreadableChannelIds
job: channels read at create for mode run; team lookup and report use it
```

## Changes

| Area | File | Change |
|---|---|---|
| Helper | `services/migration_service.py` | One `parse_rows` beside the service. A contact stays per row in the walk |
| Preflight | `migration_service.py:212,217,240,363` | Use it. Line 212 today sits outside any `try` |
| Wire | `schemas.py:2053` | `unreadableChannelIds: List[str] = []` |
| Report | `migration_service.py:745` | Blocker lines per kind, entries in `failures` |
| Reasons | `migration_service.py:1863,2322` | Field names from `exc.errors()`, not `str(exc)`, which holds input values |
| Team lookup | `migration_service.py:2061` | Skip and count |
| Create | `migration_service.py:1102` or `:1270` | Mode `run`: read channels, refuse per AC-44-20 |
| FE | `settings/migration/components` | Channels card rows, Review counts, types, mock |

## Traps

- A stored reason is built from field names or fixed text, never from an exception's own text: `str(ValidationError)` includes the input, and a database error's text includes its statement.
- Reading the source at create is a network call: release the read transaction first, `app.database.release_read_transactions()`, and map a `RespondIoError` to the refusal already used there.
- CSV mode has no channels and is unaffected.
- A real row can have `id` of a wrong type: treat as no usable id. A string of digits parses, so check what `SpaceChannel.id: int` accepts.
- Public repo: test data placeholders only.

## Slices

| Slice | Who | Content |
|---|---|---|
| S1 | tester, coder | Reproduce the 500 with a user with no email, red first, then AC-44-01..22 |
| S2 | tester, coder | AC-44-23, 24 |
| S3 | lead | Targeted mutation, kill |
| S4 | reviewer, security-reviewer | One round. Security because of stored values and an external source |
| S5 | tester | AC-44-25 |

## No motion

No new motion.
