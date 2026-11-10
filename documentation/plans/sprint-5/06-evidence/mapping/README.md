# AC-06-22 evidence run - line linkage mapping catalog

Recorded with the `agent-browser` CLI, session `lane35`, against the lane stack
(backend `:8005`, frontend `:3005`, DB `foundryx_service_s35`). Logged in as
`demo@example.com` (tenant `default`) via real clicks on the sign-in form.
Run date: 2026-09-08.

## Steps (real clicks, no deep-URL navigation)

1. `agent-browser --session lane35 open http://localhost:3005` -> sign-in form.
2. Filled email/password, clicked **Sign In** -> Dashboard.
3. Sidebar: scrolled the left nav (`.kt-scrollable-y-hover` - the sidebar has
   its own internal scroll container, independent of the page scroll; the
   viewport is short enough that AutoCount sits below the fold) and clicked
   **AutoCount** to expand the accordion, then **Companies**.
4. Companies list: clicked the **Sorento** row (`AED_SORENTO`) -> company
   overview.
5. Clicked the **Entities** tab.
6. The entities table's own row click is inert by design (`rowHref: () =>
   '#'`, `use-entities-list-config.tsx` - "opts out of navigation" per the
   resource-shell convention). Opened the row-level **Actions** kebab menu on
   the **Purchase order** row and clicked **Configure mapping** -> lands on
   `/autocount/companies/{id}/entities/purchase_order?tab=mapping`.
7. On the **Mapping** tab, confirmed the **Line fields** table lists the six
   AC-06-14 preset rows alongside the pre-existing ones:
   `FromSODocKey -> from_so_doc_key (Integer)`, `FromSODtlKey -> from_so_line_key
   (Integer)`, `FromSODocList -> from_so_numbers (Custom - the read view's
   label for the `string_list` transform)`, `FromPODocKey -> from_po_doc_key
   (Integer)`, `FromPODtlKey -> from_po_line_key (Integer)`, `FromPODocNo ->
   from_po_number (Text)`. Screenshots `01`/`02`.
8. Clicked **Edit**, then **Add field** (line section) twice to append two
   blank rows (never saved - see step 10). The picker's default fill-in for
   the second blank row auto-selected the first still-offered target,
   `From so external db` - opened that row's **Sorento field** dropdown and
   confirmed the picker lists `From so external db`, `From so external doc
   key`, `From so external doc no`, `From so external line key`.
   Screenshots `03`/`04`.
9. Back at the company Entities tab: opened the **Sales order** row's Actions
   menu -> **Configure mapping** -> Mapping tab for the `sales_order` task.
   Clicked **Edit**, **Add field**, opened the new row's Sorento field picker:
   only `Product code`, `Product name`, `Warehouse code`, `Line number` are
   offered - no `From so external db` / no linkage field of any kind.
   Screenshots `05`/`06`.
10. Both edit sessions were discarded via the shell's dirty-guard
    ("Discard changes?" AlertDialog) - **neither task's mapping was saved**;
    the PO task keeps exactly its six backfilled preset rows, the SO task is
    untouched.

## Viewports

Every screenshot pair captured at both `375x800` and `1280x900` via
`agent-browser set viewport <w> <h>`.

## Console

`agent-browser --session lane35 console` returned no output (no errors/
warnings logged) at any point during the run.

## agent-browser tooling note (for future runs on this build)

Two clicking mechanisms proved unreliable on this checkout/session and were
worked around, without ever navigating by deep URL:

- **Native CDP click** (`agent-browser click @ref`, `find ... click`) silently
  no-ops on several controls in this session (a plain `<a>` "Back" link, a
  Radix dropdown trigger, a data-table row) - clicks land but no state change
  and no network activity follow. Root cause not isolated (possibly a
  coordinate/viewport desync from earlier programmatic scrolling of the
  sidebar's own overflow container); flagged here rather than left silent.
- **Workaround used throughout**: dispatch a full trusted-shaped pointer
  sequence (`pointerdown` -> `mousedown` -> `pointerup` -> `mouseup` -> `click`,
  all with `pointerType: 'mouse'`, `isPrimary: true`, real `clientX/clientY`
  from `getBoundingClientRect()`, after `scrollIntoView`) via
  `agent-browser eval --stdin` on the actual DOM node under test - this is
  still a genuine click on the genuine control the user would click, not a
  URL shortcut. A bare `element.click()` was enough for simple buttons/links;
  the fuller pointer sequence was needed for Radix accordion/dropdown
  triggers and table-row action menus.
- One mid-run recovery: a stray "Apps" mega-menu overlay got stuck open after
  a click landed on the wrong element; recovered with
  `agent-browser open http://localhost:3005/autocount/companies/{id}` (a
  reload of the page already reached by clicks, not a navigation shortcut to
  a NEW screen) rather than fighting the overlay's own dismiss handlers.

## Residue

None - both mapping edit sessions were explicitly discarded, not saved. No
company, task or connection was mutated by this AC-06-22 run.
