# S4 smoke - omnichannel contact data model (plan 25)

Coder smoke, not the formal E2E (that's the tester's job). Run via
`agent-browser --session s25` against the fresh build on `:3003` (this
worktree, PID confirmed via `lsof -p <pid> | grep cwd`) and the fixed backend
on `:8004` (PID 33727, untouched). Login `demo@example.com` / `demo1234`,
default tenant, workspace "General" (`1d591b7a-c500-42cd-a820-caa3fa877966`).

## Steps + evidence (1280px unless noted)

1. `01-lifecycle-tab-1280.png` - Settings > Workspaces > General > Lifecycle
   tab renders the REAL seed graph (5 stages: New Lead / Hot Lead / Payment /
   Customer / Cold Lead) via the core status-engine `EntityFlow` +
   `useStatusGraph('omnichannel_contact_lifecycle', workspaceId)`. Badge
   "Customized" here just reflects `graph.source === 'tenant'` -
   `omnichannel_contact_lifecycle` is a SCOPED entity (per-workspace,
   materialized at workspace creation), so it is tenant-owned from birth and
   never forks from a platform default; the badge is not evidence of a
   two-tier fork on this graph (see BL-SS-065).
2. `02-contact-fields-tab-1280.png` - Contact fields tab lists 2 pre-existing
   REAL fields (Lead Source, Age Probe) from the live backend (S1).
3. `03-contact-field-added-1280.png` - added a `list` field "Preferred
   Channel" (options WhatsApp/Email) through the dialog; slug auto-derived
   to `preferredChannel`; toast "Field created." + row appears - real POST.
4. `04-tags-tab-1280.png` - Tags tab lists 1 pre-existing REAL tag (VIP,
   contactsCount 1 - already assigned to a seeded contact).
5. `05-tag-created-1280.png` - created tag "Hot Prospect" (emoji, hex colour
   `#EF4444` via a swatch) - real POST, toast "Tag created.".
6. `06-inbox-1280.png` - Inbox thread list shows REAL lifecycle badges per
   seeded contact (Sarah Chen = won "Customer", Priya Raj = "Hot Lead",
   Daniel Lee = "New Lead", Marcus Wong = "Customer" + VIP tag chip) - proves
   F2 (mock -> real swap) end-to-end, not just at the service layer.
7. `07-thread-open-1280.png` / `08-contact-panel-1280.png` - opened Priya Raj
   (cnt-003), toggled the Contact panel - Details tab renders real system
   fields + the two pre-existing custom fields as read-only labels.
8. `09-contact-panel-scrolled-1280.png` - Lifecycle section: "Hot Lead" badge
   + "Move to..." picker. Lifecycle picker opened and listed ONLY the 4
   fireable edges the backend returned (New Lead / Payment / Customer / Cold
   Lead) - foolproof-UI confirmed against real data (AC-CDM-18).
9. `10-lifecycle-moved-1280.png` - moved Priya Raj to "Customer" (a won/
   terminal stage). Contact panel updated to "Customer" + "No further moves
   from this stage." AND the thread-list row's badge updated from Hot Lead to
   Customer in the SAME screenshot - **no manual reload** (AC-CDM-37, the
   `contact.updated` WS push into both `use-messages` and `use-conversations`).
10. `11-tag-added-1280.png` - added "Hot Prospect" to Priya Raj via the Add-tag
    picker - chip appears in the panel AND the thread-list row simultaneously
    (same WS path).
11. `12-details-edit-1280.png` - Details Edit mode: Phone renders as **plain
    read-only text**, never an input (F16/phone fix) - First/Last/Email/
    Language/Country are editable inputs.
12. `13-details-custom-fields-1280.png` - the newly-created "Preferred
    Channel" custom field renders as a real `SearchSelect` (not a bare
    `<select>`) with the two authored options.
13. `14-details-saved-1280.png` - set Preferred Channel = WhatsApp, Save
    succeeded (real PATCH, no 422); confirmed via a direct API call
    (`GET /omnichannel/contacts?search=Priya`) that `customFields.
    preferredChannel = "WhatsApp"`, the tag and lifecycle stage all persisted
    server-side.
14. 409 path - **not driven through the UI** (foolproof-UI hides an
    already-fired edge, by design - Customer has no outgoing moves so there
    is no invalid option to click). Verified the wire contract directly:
    `POST /omnichannel/contacts/cnt-003/lifecycle {toStatusId: <same id>}`
    returned `409 {"detail":{"code":"lifecycle_move_not_allowed","message":
    "No transition from '🤩 Customer' to '🤩 Customer'."}}` - exactly the
    shape `lifecycle-move.tsx`'s F14 fix reads (`error.detail.message`),
    and is exercised end-to-end in
    `lifecycle-move.test.tsx > "renders the structured 409 machine message"`.
15. `15-reload-persists-1280.png` - hard reload (`?thread=cnt-003` deep link)
    keeps the Customer stage, Hot Prospect tag, and Preferred Channel value -
    no client-only state.
16. `16-inbox-375.png` / `17-thread-375.png` - mobile inbox list + Contact
    panel as a full-screen Sheet (per plan 25 D14) reflow cleanly at 375px;
    Details/Lifecycle/Tags sections all usable, no overlap/clipping.
17. `18-workspace-form-375.png` .. `22-lifecycle-375.png` - workspace tab
    strip is a HORIZONTALLY SCROLLABLE `TabsList` at 375px (pre-existing
    shell pattern, confirmed still working: `overflowX:auto`,
    `scrollWidth:786 > clientWidth:343`) - Contact fields / Tags / Lifecycle
    tabs all reachable and render correctly once scrolled into view.

## Console / network

`agent-browser errors` / `console` were empty throughout the run; the
frontend server log (`/tmp/s25-frontend-3003.log`) shows no errors.

## Mock-vs-backend differences reconciled this slice

- `phone` is no longer writable via the internal contact PATCH (backend
  named 422 even if the SAME value is resent, because it gates on
  `model_fields_set`, not a value diff) - the Details form no longer sends it
  at all and renders it as a permanent read-only value.
- Everything else in the S0 mock's contract (`ContactField`/`ContactTag`/
  `ThreadItem`/`LifecycleMove` shapes, the PATCH partial-merge semantics, the
  409 `{code,message}` shape) matched the real backend with no changes
  needed to `types/omnichannel.ts` or the `.real.ts` service implementations
  - S0 was written directly against the plan's §5.1 contract and the S1-S3
  backend held to it.

## Harness gotcha (not a product bug)

`agent-browser`'s ref-based `click` did not auto-scroll the sidebar's own
`kt-scrollable-y-hover` container (a nested `overflow-y: auto`, distinct from
`window`/`document` scroll) before clicking a below-the-fold sidebar link -
the click landed off-viewport and silently no-op'd. Fixed by scrolling that
container via `eval` first. Same class of gotcha for the workspace tab strip
at 375px (a nested `overflow-x:auto`) - scrolled it via `eval` before
clicking the now-visible tab. Neither is a regression in this slice's code.
