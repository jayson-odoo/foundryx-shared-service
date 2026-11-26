# Hub connector S1 - shared-service side (lane HUB-CONNECTOR-S1-SS) - working notes

Scope: AC-12..AC-19 of `BRIEF-hub-connector-s1.md` (brief + PLAN live on the CRM docs PR; to be copied here verbatim
once crew forwards them - this sandbox can only reach this repository).

## Owner rulings already known (26 Nov ~21:27)
- ALL transparency controls live in the SHARED SERVICE, per hub customer company: which locations and which brands each
  customer sees (two customers on the same hub can differ).
- Price may sync to SS, but each hub has its own "expose price" switch, default OFF for EcoHub.
- "Got stock" = on hand minus reserved > 0, counted over the available warehouses only.
- "Got incoming" = any not-yet-arrived remainder, including lines not yet allocated to a location (crew Q-A (a)).

## Pieces (SS)
1. Hub registry (a hub = a downstream partner platform that consumes stock/availability).
2. Per hub + customer company policy: locations, brands, price exposure (hub-level switch, default OFF).
3. Admin screen (frontend mock first, then real).
4. Inbound API (CRM pushes stock/incoming facts) + outbound webhooks (to the hub).
5. End-to-end with a stub hub.
