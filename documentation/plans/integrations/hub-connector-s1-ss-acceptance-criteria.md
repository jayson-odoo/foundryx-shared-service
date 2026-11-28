# Hub connector S1 - shared-service side - acceptance criteria (AC-12..AC-19)

Lane HUB-CONNECTOR-S1-SS. Written from the owner rulings in the lane brief (26 Nov ~21:27) and the frozen CRM
connector feed contract (sorento-crm #2801 head ffd73d20, forwarded by crew): the shared service PULLS the CRM feed. Tags: [BE] backend, [FE] frontend, [T] automated test, [E2E] end to end.

Words: a **hub** is a partner platform (first one: EcoHub) that shows our availability to its own customers.
A **hub customer** is a customer company on that hub, recorded in the shared service. The **CRM** feed is read (pulled) by the shared service.

## AC-12 Hub registry [BE][FE][T]
- Given an admin with `hub_connector.manage`, when they create a hub (name, code, receiver URL), then the hub is stored
  for their tenant only and the signing secret is shown ONCE.
- A receiver URL that is not public https is refused with a plain message.
- Hubs list is the standard list (search, sort on the server, Columns, Create), one line per row, row opens the hub.

## AC-13 Per hub + customer policy [BE][FE][T]
- Given a hub, when the admin adds a customer company (code + name), it sees nothing until locations and brands are
  picked; the policy is stored per (hub, customer). Two customers on the same hub can differ.
- Locations and brands are picked from searchable pickers fed by the CRM feed (`/locations`, `/brands`); a code the
  feed never listed is refused.

## AC-14 Price exposure switch [BE][FE][T]
- Every hub has a "Show price" switch, default OFF (EcoHub stays OFF). With it OFF no `list_price` leaves the shared
  service for that hub (preview, read API, webhook). With it ON the feed's `list_price` + `currency` are included.

## AC-15 In stock [BE][T]
- `in_stock` = SUM of `available_qty` (on hand minus reserved) over the customer's chosen locations > 0.

## AC-16 Incoming [BE][T]
- `incoming` = any not-yet-arrived line with an outstanding allocation to a chosen location, OR a line not yet
  allocated (empty `locations`). Yes/no only.

## AC-17 CRM feed pull + hub read API [BE][T]
- The CRM feed is a Settings, Integrations connection (address, company, key; Test reads `/locations`). A sync (every
  10 min and "Sync now") reads locations, brands, all product pages and availability in chunks of 200; products no
  longer listed are removed. A feed error changes nothing and shows its plain reason.
- A hub key (`fxh_live_`, one hub) reads `GET /api/v1/hub-connector/products?customer=` - only that hub's active
  customers; any other customer is the same 404. Per-key request budget; bad keys throttled per IP.

## AC-18 Outbound webhooks (shared service -> hub) [BE][T]
- After a sync or a policy change, every active hub customer whose view changed gets ONE signed
  `availability.updated` POST with rows `{code,name,brand_name,in_stock,incoming}` (+ price behind the switch),
  `removed` codes, an increasing `sequence`, and `full` for complete views. Oldest first per customer.
- The receiver URL is re-checked before every attempt; failures retry on a ladder, then fail and queue the full view
  once; "Send again" sends the current full view. Every attempt is visible on the hub's Deliveries tab.

## AC-19 End to end with a stub hub [E2E][T]
- With a fake CRM feed and a stub hub: two customers on one hub with different locations and brands each receive
  exactly their view, signature verified, price absent while the switch is OFF; a stock change reaches only the
  customer it affects; a product leaving the feed is removed.
