# Hub connector S1 - shared-service side - acceptance criteria (AC-12..AC-19)

Lane HUB-CONNECTOR-S1-SS. The brief + PLAN live on the CRM docs PR, which this sandbox cannot reach; these ACs are
written from the owner rulings carried in the lane brief (26 Nov ~21:27) and must be reconciled with the brief's
AC-12..AC-19 wording once crew forwards it. Tags: [BE] backend, [FE] frontend, [T] automated test, [E2E] end to end.

Words: a **hub** is a partner platform (first one: EcoHub) that shows our availability to its own customers.
A **hub customer** is a customer company on that hub. The **CRM** pushes availability facts into the shared service.

## AC-12 Hub registry [BE][FE][T]
- Given an admin with `hub_connector.manage`, when they create a hub (name, code, receiver URL), then the hub is stored
  for their tenant only and the signing secret is shown ONCE.
- A receiver URL that is not public https is refused with a plain message.
- Hubs list is the standard list (search, sort on the server, Columns, Create), one line per row, row opens the hub.

## AC-13 Per hub + customer policy [BE][FE][T]
- Given a hub, when the admin adds a customer company and ticks the locations and brands it may see, then the policy
  is stored per (hub, customer). Two customers on the same hub can have different locations and brands.
- Locations, brands and customers are picked from searchable pickers (name and code) fed by what the CRM pushed.

## AC-14 Price exposure switch [BE][FE][T]
- Every hub has an "Show price" switch, default OFF (EcoHub stays OFF). With it OFF no price leaves the shared
  service for that hub (preview, webhook) even when the CRM pushed one. With it ON the pushed price is included.

## AC-15 Got stock [BE][T]
- For a customer, an item "got stock" when, in at least one of that customer's allowed locations,
  on hand minus reserved is greater than 0. Locations outside the policy never count.

## AC-16 Got incoming [BE][T]
- An item "got incoming" when any not-yet-arrived remainder (> 0) exists in an allowed location OR on a line not yet
  allocated to any location (crew Q-A (a)).

## AC-17 Inbound API (CRM -> shared service) [BE][T]
- `PUT /api/v1/hub-connector/items` and `PUT /api/v1/hub-connector/customers` accept a Bearer `fxh_live_` key that
  resolves to one tenant; nothing in the body chooses the tenant. Bad/revoked key = 401, module off = 403.
- One bad item never fails the batch: the rest are stored and the skipped ones are named in the reply.
- Keys are created and revoked by an admin with `hub_connector.keys.manage`; only a hash is stored.

## AC-18 Outbound webhooks (shared service -> hub) [BE][T]
- After a push, every active hub customer whose view of an item changed gets ONE signed `availability.updated` POST
  (`X-Hub-Connector-Signature: t=<unix>,v1=<HMAC-SHA256(secret, t + "." + body)>`) carrying only its allowed
  brands, the got-stock / got-incoming flags, price only when the hub shows price, and items it may no longer see.
- Only changes are sent; a policy change or "Resync" sends that customer's full view.
- The receiver URL is re-checked before every attempt; failures retry on a ladder, then fail; a failed delivery can
  be sent again. Every attempt is visible on the hub's Deliveries tab.

## AC-19 End to end with a stub hub [E2E][T]
- A stub hub receives the webhook, verifies the signature, and sees exactly the policy-filtered view for two
  customers on the same hub with different locations and brands, price absent while the switch is OFF.
