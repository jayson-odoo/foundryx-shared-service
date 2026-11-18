# Lane L-D: Lead Capture screens (Keys, Delivery, Fields and map) - behaviour card

UAC: AC-64-57 (`documentation/plans/sprint-5/64-lead-capture-acceptance-criteria.md` on PR #236).
Owner rulings: 17 Nov 12:20 "no backend configuration should be needed", 12:25 "serve multiple products",
15:27 product-interest map dropped, 16:16 developer/location map reverted (Meta answers stay in lead Notes).
Mock: `documentation/plans/meta-leads/mock/lead-capture-ld-screens.html` (v1, fake data).
Crew ruling (PR #259): option (a) - thin signed-in staff routes for receivers + "Send test push", and
revoke/remove through the core grace-window engine.

## Who and where

- The product's admin (any user of the product's company holding the Lead Capture permissions).
- Sidebar block **Lead Capture** (shown only while Lead Capture is installed for the company) with three
  pages, each pruned by its own permission: Keys `/lead-capture/keys`, Delivery `/lead-capture/delivery`,
  Fields `/lead-capture/fields`.
- Everything is the signed-in company's own data. A second product = a second company, its own pages.

## Keys (`lead_capture.keys.manage`)
- Standard list: Name, Key (masked `fxl_live_****1234`), Created, Last used, Status (Active / Revoked).
  One toolbar row: Search, Filters (Status), Columns, Export, **Create**. Every column sorts; the list state
  rides the address bar.
- Create: popup asks Name -> Create -> the full key shows once with Copy; closing clears it.
- Row menu: Revoke (grace window, can be undone during the countdown). Revoked keys stay listed.

## Delivery (`lead_capture.view`; changes `lead_capture.manage`)
- First choice, one of two: **Push to my system** or **Pull only**. Only the chosen path shows.
  The first view follows the stored state: receivers exist = Push, none = Pull only.
  - Pull only: the leads address with Copy (`/api/v1/lead-capture/leads`, read with the key).
    Choosing Pull only while receivers exist asks "Switch to pull only?" and removes them.
  - Push: list of receivers: URL, Events, Added, Last delivered. Toolbar: Search, Filters (Events),
    Columns, Export, **Create**.
- Create: popup asks URL + Events (New lead ticked; Lead updated, Source updated) -> the signing
  secret shows once with Copy. A refused URL shows the plain reason under the field.
- Row menu: Send test push (one signed sample lead, `isTest: true`, to that receiver only; toast "Test push
  sent." or the plain reason), Remove (grace window).

## Fields (`lead_capture.view`; changes `lead_capture.manage`)
- **Lead fields** card: the product's own list (Key, Label, Type) in an editable line grid; line menu =
  Move up / Move down / Remove; Add field; Save (enabled when changed); "Use defaults" (shown when a list is
  saved) clears back to Name, Phone, Email, Lead notes. Bad / duplicate keys are named next to the field on
  Save.
- **Form maps** list: one row per (Page, form) the company knows: forms with a "Map fields" notice and forms
  with a map ("All forms" when an every-form map exists). Columns: Page, Form, Mapped questions, Answers in
  notes, Status (Needs mapping / Mapped). Create = Add form (Page + Instant Form ID, digits only).
- Click a row: centred popup "Map fields: <form>": each question (real labels from Meta, L-A) with a
  searchable picker of the product's fields. The default entry names what happens without a map: a
  standard question reads "Name (automatic)" etc., any other "Leave in lead notes". Save clears the form's
  "Map fields" notice.
- Generic only: any question to any field the product defines. No product-interest or developer logic.

## States (every load ends in content, empty, no-access or error + Try again)
- Lead Capture not installed: the menu block is hidden and the module keys are revoked, so the pages show
  the standard no-access page.
- No permission: standard no-access page.
- No Page connected yet: Form maps shows the empty list; Add form names the missing Page.
- Meta refused the questions read: the popup shows the plain reason + Try again.

## Backend added in this lane (option (a))
- `GET/POST /lead-capture/webhooks`, `DELETE /lead-capture/webhooks/{id}`, `POST /lead-capture/webhooks/{id}/test`
  (`routers/staff.py`), wrapping the same `delivery_service` functions the gateway uses.
- `delivery_service.send_test_push` + `get_endpoint`; `queue_event` now shares `_queue_to` with it.
- `modules/lead_capture/deferred_actions.py`: `lead_capture_keys.revoke`, `lead_capture_receivers.remove`.
- No new table, permission or gateway change (consumer guide untouched).

## Round 2 (owner 17 Nov 19:32: "we are providing the API and middleware, these UI also need to be built at ecohub")
- Every action on these screens is also on the key-holder gateway, through the same service function (one
  function, two doors): added `GET/POST /api/v1/lead-capture/keys`, `DELETE /api/v1/lead-capture/keys/{id}`
  (`409 key_in_use` for the calling key) and `POST /api/v1/lead-capture/webhooks/{id}/test`. Receivers, fields,
  sources, form questions and field maps already had gateway routes.
- A parity test fails when a staff route has no gateway counterpart (only Page connect stays staff-only, lane L-C).
- Consumer guide updated (routes, errors, Test push, Key). EcoHub how-to: `docs/lead-capture/ecohub-quickstart-screens.md`.

## Round 3 (crew-pass 0a5c355f NOT READY)
- Long text: the shared `ClampedText` one-line mode now cuts with "..." and shows the full text on hover (a single
  unbreakable string such as a URL was clipped mid-letter).
- Keys: Create sits on the toolbar row with Search, Filters, Export, Columns; the grid fits 1280 with the row menu.
- Saving the field list (Save fields or Use defaults) drops map lines that point at a removed field, in the same
  service call for both doors; "Use defaults" asks first; the Form maps list refreshes after a save.
- Lead fields lines stack at phone width; column chooser keeps the column's own label ("Last used").

## Round 4 (crew-pass ea6096e5 NOT READY; merged main with lane L-B #258)
- Hover text starts at the cell's left edge (no longer under the sidebar); Copy works on plain http (fallback copy,
  inline "Could not copy" when nothing works); reload keeps the list page (shared list hook compares by value).
- Form maps: form names from the Page's form list (L-B `GET /sources/{id}/forms`); Add form = Page + Form pickers;
  "All forms" edits its stored lines without a Meta read; a stored map to the automatic field shows that field.
- "Use defaults" = grace-window countdown with Cancel (`lead_capture_fields.reset`, same `set_fields` call).
- Dates dd/mm/yyyy, h:mm am/pm (shared `formatDmyDateTime`); Save fields is secondary (Form maps Create is the one
  filled button); Delivery and Form maps keep their list state in the address bar; "At most 5 receivers.".

## Round 5 (crew-pass 4575cc46 NOT READY; merged main with #253 row menu)
- "Map fields: All forms" lists every question of the Page's forms by Meta's label (each once), plus any stored key no
  form asks any more in plain words ("Full name", "Q budget"); never a raw key. Meta unreadable = the stored lines.
- A refused receiver URL uses the screen's word: "The URL must use https://.", "The URL cannot target localhost.",
  "The URL cannot target a private or reserved IP.", "Enter a valid URL.".
- Right-click / long-press row menu comes from the shared list (#253); Delivery refreshes Push / Pull only after a
  Remove from it.

## Round 6 (crew-pass 041306ae NOT READY)
- Removing the last receiver from any menu switches Delivery to Pull only (no reload).
- A host with a space or "%20" is "Enter a valid URL." (core URL guard: a host is letters, digits, `-`, `_`, `.`, an
  IP literal or an IDN name).
- Keys and Delivery refresh their list after Create / Add through the list's fetcher, not a remount, so a cleared
  search stays cleared.
- A record already gone when a grace-window action is started reads in plain words, never its id: "This receiver
  was already removed.", "This key was already revoked." (core engine: per-action `gone_message`, generic "This
  record no longer exists."). Stale Send test push / Remove: "This receiver was already removed."; an id the company
  never had (e.g. mistyped on the gateway): "This receiver does not exist." (code `endpoint_not_found` either way).
- CI: the AutoCount write-back deadline test runs on a fake clock (it failed on a busy runner).

## Round 7 (crew-pass ffa60e3f NOT READY)
- Any list that writes its state to the address bar keeps the CURRENT search / sort / filter / page when it is mounted
  again on the same page (Delivery: Pull only, then Push to my system). Cause fixed in the shared list: it wrote with
  `history.replaceState(history.state, ...)`, which Next's router does not sync to `useSearchParams()`; it now writes
  with `null`, as the rest of the app does.

