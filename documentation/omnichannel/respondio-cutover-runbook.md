# respond.io cutover runbook

> Plan 33 (roadmap A6). Covers the customer prerequisites, the WABA number move (the ceremony
> the migration tool does NOT automate), the dry-run-then-run procedure, CSV-mode limits, and
> rollback notes. Read alongside the migration setup form itself (Omnichannel > Migration) -
> this document is the sequence around it, not a UI walkthrough.

## 1. Prerequisites (confirm ALL of these before touching the migration tool)

1. **Plan check.** The respond.io Developer API needs the workspace's **Growth plan or
   above** (Workspace Settings > Plan). A Starter/Team workspace has no API path - drop
   straight to CSV mode (contacts only; no media, no per-channel identities, no message
   history unless the workspace is also on Enterprise for the Messages export).
2. **Access token.** Workspace Settings > Integrations > Developer API > Add Access Token.
   One token per space. Paste it into the workspace's respond.io connection in Settings >
   Integrations; it is stored encrypted and never shown again after saving.
3. **Workspace timezone.** The contacts walk requires a timezone. Note the space's own
   timezone (shown on the respond.io dashboard) and put it on the connection - a wrong
   timezone does not fail loudly, it just shifts which contacts a distinct-lifecycle scan or
   a `messagesSince` floor observes.
4. **Target workspace exists** with its channels already connected (Embedded Signup), its
   lifecycle stages already authored on the workspace's Lifecycle canvas, and its close
   reasons set up. The migration tool MAPS onto these; it never creates a channel, a
   lifecycle stage or a close reason.
5. **Users exist** with the SAME email addresses as the respond.io agents. Email is the only
   join key for assignment - a mismatch leaves the thread unassigned, not wrongly assigned.
6. **Export bundle taken anyway** (belt and braces; a respond.io export stays valid 7 days):
   Contacts export, Conversations export, Messages export (Enterprise plans only) and Failed
   Messages export, plus screenshots of Contact Fields, Tags, Lifecycle, Snippets, Teams and
   the Workflow list. The Snippets screenshot is not optional - there is no snippets API, so
   quick replies come from that screenshot (typed into a 2-column CSV, `shortcut,body`) or a
   hand-made CSV.
7. **Freeze window agreed.** Traffic that lands in respond.io during a run is invisible to
   that run (it walks a stored cursor, not a live feed) and needs a second, later run to pick
   up. Agree a window with the customer during which nobody replies inside respond.io.
8. **Volume estimate.** A rough contact count and message count so the dry-run numbers can be
   sanity-checked against what the customer believes they have.

## 2. The WABA number move (NOT automated by this tool)

Moving a WhatsApp Business number between BSPs is a Meta-side ceremony this tool does not
touch. Order matters:

1. **Keep respond.io live** and run the contacts/history migration (below) while the number
   is still receiving on respond.io's BSP.
2. **Deregister the number** from respond.io's BSP (respond.io support or WABA settings).
3. **Re-onboard the number** through this platform's Embedded Signup (Settings > Channels >
   Connect a number) - this is the SAME flow a brand-new WhatsApp channel uses.
4. **Re-sync WhatsApp templates** on the channel's Templates tab. Budget time for
   re-approval - Meta re-reviews templates under the new BSP; a template that was APPROVED on
   respond.io is not automatically approved here.
5. **Re-point click-to-chat links and QR codes** (marketing collateral, business cards, the
   website) at the number now hosted on this platform - they do not move themselves.
6. **Cut inbound traffic over last**, only once steps 2-5 are confirmed working (send a test
   message to the number and watch it land in this platform's Inbox).

A number can only receive on ONE BSP at a time - there is no dual-receive window. Plan the
freeze (prerequisite 7) to cover this whole sequence, not just the data migration.

## 3. Dry-run-then-run procedure

The tool refuses `Start migration` until a **dry run for the exact same mapping** has
finished inside the last 24 hours (`dry_run_required`). This is not a formality - use the
report.

1. **New migration** > pick **Method**: `respond.io Developer API` (Growth plan+) or
   `CSV export` (no API access, or a Starter/Team plan).
   - API mode: pick the connection, then the target workspace. Map every source channel
     (unmapped/incompatible channels are forced to "Skip"), every agent, every team and every
     observed lifecycle label. Leave `Contacts only` on for a first pass if you want to
     verify the space/mapping before committing to a long message-history walk.
   - CSV mode: upload the contacts export (2500-row cap - the respond.io Contacts module's
     own export ceiling; a file at or over that count may be truncated, and the report says
     so). Map the file's own column headers onto the fixed field list (Contact ID, First
     name, Last name, Phone, Email, Language, Country, Lifecycle) - leave a field "Not
     mapped" to fall back to a case-insensitive guess against the file's own header text.
2. **Run dry run.** Nothing is written; every media fetch is skipped. Read the **Counts
   report**:
   - `Fetched` / `Would create` / `Would update` / `Would skip` / `Errors` per entity.
     `Would update` on a re-run is expected (an existing migrated contact merges, it is not
     duplicated) - a large, unexpected `Would create` number on a SECOND dry run for the same
     mapping usually means the wrong workspace or connection is selected.
   - The **Blockers** list. CSV mode always states three blockers up front (no message
     history, no channel identities, no media) - these are facts about the CSV path, not
     something to fix. A lifecycle-mapping blocker ("N contacts have no lifecycle mapping")
     means those contacts land with no lifecycle stage - map the label or accept the gap.
   - `messagesWithInferredTimestamp` (API mode) - respond.io message items carry no
     timestamp of their own for many inbound messages; a large inferred count is a sign the
     customer's data leans on that behaviour, not a bug in the tool.
3. **Start migration** (now enabled). The SAME mapping runs for real:
   contacts > (identities > messages > media > events, API mode only) > quick replies.
   Progress and a milestone log update while it runs; the page polls and stops polling once
   the job reaches a terminal status.
4. **Check the finished job.** `Done` with `0` failures is the clean case. `N` failures means
   open the per-entity failure table (or download the full `failures.csv` - contains contact
   names, phones and emails, so it is an authed download, never a shared link) and triage row
   by row; a media 404 or a malformed contact row does not fail the whole run.
5. **Re-run for the freeze-window tail.** Any message that arrived in respond.io after the
   cursor needs a second run once the freeze window ends - a plain re-run of the SAME mapping
   is safe (idempotent via `migration_refs`); it will not duplicate anything already landed.

## 4. CSV-mode limits (stated up front, not discovered mid-run)

- **Contacts only** (+ quick replies, if a snippets CSV is supplied) - no message history, no
  per-channel identities, no media, regardless of what the export contains.
- **2500-row cap** on the respond.io Contacts-module export itself; a file at or over that
  count is flagged as possibly truncated.
- **20 MB file cap** on the upload itself (mirrors respond.io's own contacts-import ceiling).
- **Custom fields and tags are not read from this CSV path** - only the dedicated contacts
  import wizard (Contacts > Import) finds-or-creates those from a `cf_<fieldKey>` column; the
  migration tool's CSV mode is identity fields (name/phone/email/language/country/lifecycle)
  plus optional quick replies only.
- A future inbound message from a CSV-migrated contact stitches by **phone or email only**
  (no per-channel identity exists to match on).

## 5. Rollback notes

There is **no rollback** button, by design: deleting migrated rows risks deleting rows a live
agent has since touched (a reply sent, a tag added, a lifecycle change). If a run needs to be
undone:

- **A run still in flight** - Abort it (Actions > Abort on the job, or the job list row menu).
  It stops before its next checkpoint, keeps its partial counts, and a later re-run resumes
  from where `migration_refs` left off - nothing already written is lost or duplicated.
- **A finished run whose mapping was wrong** (wrong workspace, wrong lifecycle map) - there is
  no undo. Fix the mapping and run a fresh dry run; a corrected mapping's contacts MERGE with
  whatever the bad run already created (fill-if-empty only, tags unioned, lifecycle never
  moved) rather than creating a second copy. A field or tag that should not have been created
  needs a manual cleanup pass (Contacts > bulk edit) - the tool does not auto-detect "wrong".
- **A partially-migrated workspace is a supported, working state** - the inbox is usable with
  partial history; there is nothing to "finish" beyond running the tool again.

## 6. What is explicitly out of scope (state this to the customer up front)

Workflows (re-authored by hand - respond.io has no export format this tool can consume),
broadcast history, reports/analytics history, internal comments and closing-note text, AI
agents and knowledge sources, the files library, growth widgets, blocked-contact flags,
collaborators, and contact-merge history. Conversation events (`opened`, `first_agent_reply`,
`closed`, `assigned`, `lifecycle_changed`) are DERIVED from migrated message history and
stamped with the original timestamp, not fetched - respond.io exposes no event or
assignment-log endpoint, so reports on migrated history reconstruct these five event types
only, not a full audit trail.
