# Plan 44 acceptance criteria: source rows the migration cannot read

## Journey

An admin starts a respond.io migration. One source user has no email, so the row does not fit the shape we read.

1. Preflight still answers. A warning gives the count and each row's source id, never a name or phone.
2. The admin maps what is there. Nothing is mapped for them.
3. A dry run may run. Its report lists what was skipped.
4. Before the real run the same count is on screen. A skipped user does not stop it. A skipped channel does, because its messages would be lost, until the admin marks that channel Skip in the map.

## Rows that cannot be read

| AC | Rule |
|---|---|
| AC-44-01 | [BE] `GET /preflight` with a user row missing `email` answers 200, not 500. That row is left out of `users`, and the other users are listed |
| AC-44-02 | [BE] The same for a channel row, a custom field row and a contact row in the lifecycle scan, each independently of the others |
| AC-44-03 | [BE] `warnings` gains one line per kind with the count and the source ids, at most 20 ids then "and N more". It never holds a name, email, phone or the row's other values. A row with no usable id counts, and shows no id |
| AC-44-04 | [BE] Preflight carries `unreadableChannelIds`, the channel ids it could not read, empty when none. Existing fields are unchanged |
| AC-44-05 | [BE] Nothing is auto-mapped: an unreadable channel gets no map entry from the server |

## Dry run and report

| AC | Rule |
|---|---|
| AC-44-10 | [BE] A dry run proceeds with unreadable rows. Its report lists them in `failures` with entity, source id, and action `skipped`, and a blocker line gives each kind's count, contacts included. A job picked up again after a crash does not list a row twice or count it twice |
| AC-44-11 | [BE] A stored failure reason for a row that cannot be read holds field names only, never the row's values. Covers the existing contact sites at `migration_service.py:1863,2322` as well as the new ones. Its stored source id is the usable id or empty, in the contact walk too, and a contact row that is not an object is skipped without ending the job |
| AC-44-12 | [BE] The team lookup in the job at `migration_service.py:2061` skips a bad user row and counts it, instead of ending the job |

## Real run

| AC | Rule |
|---|---|
| AC-44-20 | [BE] Creating a job with mode `run` while a source channel cannot be read answers 422 with `fieldErrors.channelMap`, naming the count and ids, unless the map holds that channel id with a null target. The check reads the source at that moment |
| AC-44-21 | [BE] A skipped user, field or contact does not block mode `run` |
| AC-44-22 | [BE] A channel row with no usable id cannot be marked Skip, so it blocks mode `run`, and the message says so |
| AC-44-23 | [FE] Channels card: each id in `unreadableChannelIds` shows a row with its source id and "Skip this channel" as the only choice, not chosen by default, and the map has no entry for it until chosen. Choosing it adds that id with a null target. The dry run may run without it. The real run's refusal shows under the card, once, with a preflight loaded, and choosing Skip clears it. A new preflight drops the choice. "This space has no channels to migrate" does not show while an unreadable id is listed |
| AC-44-24 | [FE] Review shows the counts before Start through the dry run's report card: one blocker line each for channels, users, fields and contacts. Start needs that dry run, and there is no second count on screen, so the two cannot differ |
| AC-44-25 | [E2E] Recorded run at 1280 and 375 on a local stack with a patched source client: a user with no email, then a channel that cannot be read |

## Contract

| AC | Rule |
|---|---|
| AC-44-30 | [T] `documentation/engineering/omnichannel-service.md` states the rule. This surface is staff-only, so the consumer guide does not change |
