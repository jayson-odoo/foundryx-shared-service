# Lane L-D: Lead Capture screens (Keys, Delivery, Fields and map) - behaviour card

UAC: AC-64-57 (`documentation/plans/sprint-5/64-lead-capture-acceptance-criteria.md` on PR #236).
Owner rulings: 17 Nov 12:20 "no backend configuration should be needed", 12:25 "serve multiple products",
15:27 product-interest map dropped, 16:16 developer/location map reverted (Meta answers stay in lead Notes).
Mock: `documentation/plans/meta-leads/mock/lead-capture-ld-screens.html` (v1, fake data).

## Who and where

- The product's admin (any user of the product's company holding the Lead Capture permissions).
- One page: **Lead Capture** in the sidebar (shown only while Lead Capture is installed for the company),
  `/lead-capture?tab=keys|delivery|fields`. The tab is in the address bar.
- Everything is the signed-in company's own data. A second product = a second company, its own page.

## Tabs

### Keys (`lead_capture.keys.manage`)
- Standard list: Name, Key (masked `fxl_live_ab12...`), Created, Last used, Status (Active / Revoked).
  One toolbar row: Search, Filters (Status), Columns, **Create**.
- Create: popup asks Name -> Create -> the full key shows once with Copy; closing clears it.
- Right-click a row: Revoke (confirm popup). Revoked keys stay in the list with status Revoked.

### Delivery (`lead_capture.view`; changes `lead_capture.manage`)
- First choice, one of two: **Push to my system** or **Pull only**. Only the chosen path shows.
  - Pull only: no receivers. Leads are fetched with the key from `GET /api/v1/lead-capture/leads`.
    Choosing Pull only while receivers exist asks to remove them (confirm popup).
  - Push: list of receivers: URL, Events, Added, Last delivered. Toolbar: Search, Columns, **Create**.
- Create: popup asks URL + events (New lead ticked by default; Lead updated, Source updated) -> the signing
  secret shows once with Copy.
- Right-click a receiver: Send test push, Remove (confirm).
- Send test push: queues one signed test delivery; a toast reports it was sent or names the plain reason.

### Fields (`lead_capture.view`; changes `lead_capture.manage`)
- **Lead fields**: the product's own list (Key, Label, Type) in an editable line grid. With no list saved
  the four defaults show (Name, Phone, Email, Lead notes). Save replaces the list; "Use defaults" clears it.
- **Form maps**: one row per (Page, form) the company knows: forms with a "Map fields" notice and forms that
  already have a map, plus "All forms" per Page. Columns: Page, Form, Mapped (n of m), Status
  (Needs mapping / Mapped). Click a row: centred popup "Map fields":
  - each form question (real labels from Meta, L-A) on its own row with a searchable picker of the
    product's lead fields, or "Leave in lead notes";
  - Save -> the form's "Map fields" notice clears.
  - "Add form" in the toolbar: enter the Instant Form id, the questions load from Meta.
- Generic only: any question to any field the product defines. No product-interest or developer logic.

## States (every load ends in content, empty, no-access or error + Try again)
- Lead Capture not installed: page hidden from the menu; direct URL shows the standard not-installed page.
- No permission: standard NoPermission page per tab.
- No Page connected yet: Form maps shows an empty state (connect is lane L-C).
- Meta refused the questions read: the popup shows Meta's plain reason + Try again.

## Backend needs (asked crew before code)
- Keys, Fields, field map, questions: staff routes exist on main (`routers/staff.py`).
- Delivery: the receiver routes exist only on the key-holder gateway (`routers/gateway.py:56`); the staff
  side has none, and no "Send test push" route exists anywhere. See the crew-ask on the PR.
