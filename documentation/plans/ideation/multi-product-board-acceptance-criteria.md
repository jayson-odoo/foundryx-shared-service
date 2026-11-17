# Multi-product feedback board - behaviour card + acceptance criteria (lane SS-MULTI-PRODUCT-BOARD)

Goal (owner 17 Nov): "the shared service should be able to serve multiple products". One SS feedback
board, served per product: a board opened for product P looks like P and only shows P.

## What the code does today (read, not guessed)

- The board Sorento CRM frames is the **personal-link board** `/public/feedback/board/{token}`
  (`service_frontend/app/(public)/public/feedback/board/[token]/layout.tsx`, `LinkPortalRoot`).
- A personal link (`idea_contact_links`, `modules/ideation/models.py` `IdeaContactLink`) has **no product**:
  one live link per contact, minted from an item by `mint_board_link` (`services/feedback_links.py`).
  So the session principal has `productId = null` (`services/portal.py` `session_for_link`) and the board
  shows every product of the tenant, plus a "Product" row on the item page (`idea-page.tsx:473`).
- Colours come from the HOST tenant's theme (`lib/branding-ssr.ts`, `/public/branding/{slug}/theme.css`),
  so a board on chat.foundryx.my shows the "chat" tenant's orange.
- The embed portal (`/embed/feedback/portal`) already has a product (`EmbedConnection.product_id`), and the
  product filter + product picker already hide when `principal.productId` is set
  (`roadmap-view.tsx:33`, `submit-idea-form.tsx:79`).

## Rules

R1. A personal link belongs to ONE product: the product of the item it was sent for. A contact can hold one
    live link per product (Sorento link and EcoHub link are different links).
R2. A board opened through a product's link (or the product's embed connection) shows only that product's
    items: Feedback list, Roadmap, Changelog, My requests, item pages. Another product's item opened by
    its URL is not found.
R3. A product-scoped board shows no product UI: no "Product" row on the item page, no product filter on the
    Roadmap, no product picker on Submit.
R4. The board's colours and name come from the product's "Feedback board" settings on the Products screen
    (edit product): one brand colour and a board name. Hover/soft shades are derived from the colour.
    The browser tab reads "<board name> feedback".
R5. A product with no board colour/name shows the SS default look (no product colour, tab "Feedback").
R6. The host site's own branding (chat.foundryx.my app, other public pages) is unchanged; only the board takes
    the product's colours.
R7. Nothing is Sorento-specific: EcoHub (or any product) gets the same by filling the same two fields.
R8. Old links minted before this change: when every item that contact submitted belongs to one product, the
    link is stamped with that product (backfill); otherwise it stays unscoped and behaves as today.

## Examples

E1. Sorento has colour #3b82f6, name "Sorento CRM". A dealer opens the board from the CRM: tabs underline,
    "Yours", upvote highlight and buttons are blue; tab title "Sorento CRM feedback"; only Sorento items; the
    item page has no Product row.
E2. EcoHub has colour #16a34a, name "EcoHub". The same dealer gets an EcoHub item update: its link opens a
    green board with only EcoHub items. The Sorento link still opens the blue Sorento board.
E3. Product "Internal tools" has no board settings: its board uses the SS default colour, tab "Feedback",
    still only that product's items, still no Product row.
E4. The operator clears Sorento's colour on the Products screen: the next board load is the SS default look.
E5. A staff user opens /portal/feedback (signed in, all products): unchanged - product filter and Product row
    still there, SS default colours.

## Edge cases

- Colour must be a #rrggbb hex; anything else is refused next to the field.
- A product deleted after its link was sent: the link resolves to an empty board in SS default look
  (never another product's items).
- Text on buttons stays readable: white or near-black foreground is picked from the colour's contrast.
- Old link, contact submitted items on two products (R8 "otherwise"): unscoped, product row visible, SS
  default look - same as today.
- Staff cancel a dealer's link: every live link of that person is cancelled (all products).
- Known limitation: staff move an item to another product after its link was sent. The old product's link
  no longer shows that item (it now belongs to the other product's board); the dealer's next status
  message carries the new product's link. Logged as BL-SS-369 (redirect to the item's current product).
- Embed boards (CRM embed connections) are product-bound already, so they take the product's look too.

## Acceptance criteria

- AC-MPB-1 [BE] Minting a board link for an item stamps the item's product; a second product gets its own live link.
- AC-MPB-2 [BE] A product-scoped link session returns `principal.productId` and only that product's items (list, roadmap, changelog, item page 404 for another product).
- AC-MPB-3 [BE] The session returns `brand {name, color}` from the product's board settings; null when unset.
- AC-MPB-4 [BE] Product delivery settings accept/clear `boardColor` (#rrggbb, 422 otherwise) and `boardName`.
- AC-MPB-5 [BE] Backfill stamps old links whose contact's items are all one product; leaves others null.
- AC-MPB-6 [FE] Product-scoped board hides the item-page Product row.
- AC-MPB-7 [FE] Board with a brand colour sets `--primary` (and derived shades) on the board only; tab title "<name> feedback".
- AC-MPB-8 [FE] Products screen edit dialog has "Board colour" + "Board name".
- AC-MPB-9 [E2E] Two products (blue, green): each link opens its own coloured, single-product board.
