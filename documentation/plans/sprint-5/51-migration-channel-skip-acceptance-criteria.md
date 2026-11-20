# 51 - Migration: skip channel setup now, connect later - acceptance criteria

Lane SS-CHANNEL-SKIP. The owner is migrating a workspace from respond.io before its
WhatsApp number is connected in the target workspace. The migration must run without a
target channel and the channel must be connectable afterwards.

## Slice 1 - skip now

- AC-SKIP-01 [FE] Given a source channel with no compatible connected target channel,
  When the Channels section renders, Then the row shows "No channel connected" and a
  "Connect channel" action that opens the Channels page, and its picker reads
  "Skip for now".
- AC-SKIP-02 [BE][T] Given every channel in the map has a null target, When the operator
  saves (dry run) and then starts the run, Then the job is created (no 422) and contacts
  and history import without channel identities.
- AC-SKIP-03 [FE][T] Given every channel is skipped, When the operator clicks Save,
  Then the form submits (no client-side block).

## Slice 2 - connect later

- AC-SKIP-04 [BE][T] Given a finished migration that skipped a channel, When the
  channel is connected and the migration runs again with the channel mapped, Then every
  previously migrated contact gets its channel identity and no message is duplicated.
- AC-SKIP-05 [BE][T] Given a migrated contact with no channel identity and no active
  channel in the workspace, When an agent or a workflow sends to it, Then the send is
  refused with "No active channel is connected to this workspace." (no 500, no silent
  drop).
- AC-SKIP-06 [BE][T] Given messages imported while their source channel was skipped,
  When the migration runs again with that source channel mapped to a connected channel,
  Then every earlier message from that source channel carries the channel, messages
  from a still-skipped channel or with no source channel stay without one, the dry run
  previews the count (messages Update) without writing, and a third run changes nothing.
