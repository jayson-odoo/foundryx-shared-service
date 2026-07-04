# Sprint 3 · Plan 05 — Document Sharing (share links + entity-link seam) — User Acceptance Criteria

**Scope:** slice 2 (sharing). Companion to `05-document-mgmt-sharing.md`. Builds on the slice-04 Drive (`04-document-mgmt-drive.md` + `-uat.md`) — folders/files/versions/quota/sniff-floor/CSP-sandbox serve are assumed present and unchanged here. This UAT covers **share links** (mint/list/revoke × 3 tiers × view/edit), the **public pre-auth surface**, the **policy ceiling**, and the **`file_links` polymorphic seam**.

**How to read:** each criterion is **Given / When / Then**, grouped by feature. Every group lists its **edge cases** as their own pass/fail criteria. The **Security** group (§9) and **Traceability** table map each criterion back to the plan's locked decisions (D1–D12) so functionality tallies with the design. A feature is "accepted" only when every criterion passes at **both** a desktop (~1280px) and a mobile (~375px) viewport (house responsive mandate), and the public surface passes white-label + no-product-name checks.

**Personas**
- **Sharer** — holds `documents.share` (+ `documents.read`). Mints/revokes internal & user & public-view links; lists this target's links.
- **Power-sharer** — also holds `documents.manage`. The only persona who can mint **public + edit** links (can't hand out write you lack — D6/D12).
- **Internal viewer** — an authenticated user of the **owning tenant**; not necessarily a Sharer. Opens internal/user links.
- **Outsider tenant user** — authenticated, but on a **different** tenant. Must be denied every share of this tenant.
- **Anonymous visitor** — logged-out browser. Opens public links only; anonymous write only on a live `public+edit` link.
- **Admin (oversight)** — holds `documents.share`; uses `/documents/shares` to see/kill every active link.

**Global preconditions**
- All share rows, allow-list user ids and `file_links` are tenant-scoped; a stored id is validated to the share's tenant at save and tenant-scoped at resolve (sprint-2/01 cross-tenant-leak rule).
- The token is a high-entropy bearer capability, globally unique, self-identifies the tenant (no slug in path/subdomain — D7/D9).
- Tenant policy `document_settings.public_sharing ∈ {off, view, edit}` (default **off**) is the ceiling for the **public tier only** (D5).

---

## 1. Share dialog — minting a link (use case: "share this file/folder, control who + what")

**AC-SHARE-01 — Open the Share dialog**
- Given a Sharer right-clicks (or uses the **…** menu on) a file or folder in the Drive,
- When they choose **Share**,
- Then a dialog opens showing the target name/kind, a **tier** SearchSelect (Internal / Specific users / Public), a **capability** radio (View / Edit), and a **Copy link** affordance — and lists this target's existing links with **Revoke**.

**AC-SHARE-02 — Mint an internal link**
- Given the Sharer selects **tier = Internal**, **capability = View**,
- When they confirm,
- Then a link is generated and **Copy link** copies the URL; the new link appears in the dialog's existing-links list with tier/capability/created shown.

**AC-SHARE-03 — Mint a specific-users link**
- Given the Sharer selects **tier = Specific users**,
- When a **MultiSelect of tenant users** appears, they pick one or more and confirm,
- Then the link is minted and only the named users (authenticated, same tenant) may open it.

**AC-SHARE-04 — Mint a public link (ceiling-aware)**
- Given the tenant policy is **view** or **edit**,
- When the Sharer selects **tier = Public**,
- Then the Public option is enabled; on confirm a public link is minted and copyable; the link opens for an anonymous visitor on the public route.

**AC-SHARE-05 — Optional expiry + password + per-link caps**
- Given any minting flow,
- When the Sharer sets an optional **expiry date**, an optional **password**, and (for public+edit only) **max-uploads** / **max-MB**,
- Then those bounds persist on the share row and are enforced on the public surface (§7, §8).

**AC-SHARE-06 — Edit capability on a file vs folder**
- Given **capability = Edit**,
- Then the dialog copy reflects the target kind: a **file** edit = replace content (appends a version, D3); a **folder** edit = upload new files into the subtree (+ rename within it) — move/delete via link are **not** offered (D3).

**Edge cases**
- **SHARE-E1 Public disabled when ceiling = off:** the **Public** tier option is visibly **disabled + annotated** (e.g. "Public sharing is off — enable in Settings"); it cannot be selected. Internal/user stay available.
- **SHARE-E2 Edit clamped when ceiling = view:** with policy = view, selecting tier = Public **disables the Edit radio** (view only); internal/user tiers may still offer Edit per their own rules.
- **SHARE-E3 Public+edit needs `documents.manage`:** a Sharer **without** `documents.manage` sees the Edit radio **disabled** for the Public tier (annotated "requires manage"); the backend also rejects a direct mint (403).
- **SHARE-E4 No `documents.share`:** a user lacking `documents.share` sees **no Share affordance** at all; a direct mint attempt is rejected 403.
- **SHARE-E5 User-tier allow-list cross-tenant guard:** the MultiSelect lists only this tenant's users; a planted foreign `user_id` is rejected at save (422).
- **SHARE-E6 Blank/invalid expiry or password:** a past-date expiry or empty-but-toggled password is blocked at the dialog (confirm disabled) — never mints a broken link.

---

## 2. Existing links + revoke (use case: "stop sharing")

**AC-REVOKE-01 — Revoke from the Share dialog**
- Given the dialog lists this target's links,
- When the Sharer clicks **Revoke** on a row,
- Then the link is disabled (soft — keeps audit trail, D8); re-opening the link's URL now resolves to a **uniform 404**.

**AC-REVOKE-02 — Revoke is immediate**
- Given a public link was open in another browser,
- When it is revoked,
- Then the next request (resolve / file fetch / upload) returns 404 — no grace window, no cached access.

**Edge case**
- **REVOKE-E1 Re-mint after revoke:** revoking does not block minting a fresh link to the same target; the new link has a new token and works independently.

---

## 3. `/documents/shares` oversight page (use case: admin kill-switch)

**AC-OVERSIGHT-01 — List every active link**
- Given an Admin opens **Documents → Shares** (gated `documents.share`),
- Then a Resource list shows every active link across the tenant: **target** (name + file/folder icon), **tier**, **capability**, **creator**, **expiry**, **created** — and Active|Revoked segmenting per the shell.

**AC-OVERSIGHT-02 — Row revoke**
- Given a row,
- When the Admin chooses **Revoke**,
- Then that link is disabled and drops from the Active view.

**AC-OVERSIGHT-03 — Bulk revoke (typed-confirm)**
- Given a multi-selection of links,
- When the Admin chooses **Revoke** (bulk),
- Then a `ConfirmActionDialog` requires the typed confirm (e.g. `REVOKE`) before the destructive action; on confirm all selected links are disabled.

**Edge cases**
- **OVERSIGHT-E1 Empty state:** a tenant with no active links shows a clean empty state, not a blank panel.
- **OVERSIGHT-E2 Permission:** a user lacking `documents.share` is bounced to the friendly **NoPermission** page (never a raw 403); the **Shares** menu entry is pruned for them.
- **OVERSIGHT-E3 Expired shown honestly:** an expired-but-not-revoked link reads as closed/expired in the list (consistent with its 404 public behavior), never as "active".

---

## 4. Internal & user-tier access (use case: share inside the org)

**AC-INTERNAL-01 — Internal link, same-tenant user**
- Given an **internal** link,
- When an **Internal viewer** (authenticated, owning tenant) opens it,
- Then they get access at the link's capability (view = preview+download; edit = replace/upload per D3).

**AC-INTERNAL-02 — Internal link, logged-out**
- Given an **internal** link,
- When an **Anonymous visitor** opens it,
- Then access is **blocked** (auth required) — internal ≠ public.

**AC-INTERNAL-03 — Internal link, outsider tenant**
- Given an **internal** link of tenant A,
- When a user authenticated to **tenant B** opens it,
- Then access is **denied** (the `/auth/me` tenant must match the share's tenant — D2).

**AC-USER-01 — User-tier, listed user**
- Given a **user-tier** link,
- When a **named** allow-list member opens it,
- Then access is granted at the link's capability.

**AC-USER-02 — User-tier, non-listed tenant user**
- Given a **user-tier** link,
- When an authenticated same-tenant user who is **not** on the allow-list opens it,
- Then access is **denied** (named-only).

---

## 5. Public route — resolve & state envelope (use case: open a public link)

**AC-PUBLIC-01 — Open a live public file link (white-labeled)**
- Given a live **public + view** file link,
- When an Anonymous visitor opens `/public/documents/{token}`,
- Then they see a **clean, branded** page (tenant logo/colors/name, **minimal chrome — no app sidebar/menus**): the file preview + a **Download** button. No "FoundryX", no provider leakage.

**AC-PUBLIC-02 — Open a live public folder link (Drive-lite)**
- Given a live **public + view** folder link,
- Then the page shows a **read-only Drive-lite** tree/grid of the folder's **current** subtree (live-follow — D4), each file openable/downloadable; no rename/move/delete affordances.

**AC-PUBLIC-03 — Password gate**
- Given a link with a password set,
- When opened,
- Then a **password prompt** page renders first (state `password_required`); a correct password (`POST …/unlock`) reveals the content; a wrong password is rejected and **pumps the share throttle bucket**.

**AC-PUBLIC-04 — Friendly closed/expired state**
- Given a token that **resolves** but the link is expired or otherwise closed-but-known-closeable,
- Then the page shows a **friendly closed/expired message** (200 `state=closed`), not a raw 404 page.

**Edge cases**
- **PUBLIC-E1 Uniform 404 (no enumeration):** an **unknown**, **disabled/revoked**, or **over-ceiling** token returns the **same uniform 404** as a nonexistent one — a visitor cannot distinguish "never existed" from "revoked" from "policy-blocked".
- **PUBLIC-E2 Ceiling flip to off disables public links:** with a live public link, flipping policy → **off** makes the link resolve to **404**; flipping back to view/edit restores it (no re-mint needed) — internal/user links unaffected.
- **PUBLIC-E3 Over-ceiling public+edit:** a `public+edit` link served while policy = view is treated as over-ceiling → 404 (server clamps on every serve, not just at mint — D5).
- **PUBLIC-E4 Single-file share scope:** on a public **file** link, requesting any `file_id` other than the target file = 404 (the share grants exactly one file).
- **PUBLIC-E5 Responsive:** the public page (file view, folder grid, password gate, closed message, upload affordance) is fully usable at ~375px — no clipped controls, full-width dialogs.

---

## 6. Public folder live-follow & ancestry reachability (D4)

**AC-FOLLOW-01 — Added file auto-appears**
- Given a live public folder link to folder X,
- When the owner later adds a file anywhere under X's subtree,
- Then an Anonymous visitor refreshing the public page **sees the new file** (no snapshot, resolved at serve time).

**AC-FOLLOW-02 — Out-of-subtree file is unreachable**
- Given the same folder link,
- When the visitor attempts to fetch a file that is **not** under X (a sibling/ancestor file),
- Then access is **denied** (ancestry walk: reachable iff the link targets the file directly OR an ancestor folder of the file is the link's target).

**Edge case**
- **FOLLOW-E1 Soft-deleted along the path:** a file whose path to the link target passes through a **soft-deleted** folder is **unreachable** (the ancestry walk respects soft-delete).

---

## 7. Public file serving (D6/D9 — CSP-sandbox)

**AC-SERVE-01 — Sandboxed, fresh-URL serving**
- Given a reachable public file,
- When the visitor previews/downloads it,
- Then it is served through the **CSP-sandbox route** (no script execution), ancestry-checked against the share on **every** fetch, and any presigned URL is **never immutable-cached** (re-signed per click).

**Edge case**
- **SERVE-E1 Revoked mid-session:** a file fetch after the link is revoked/expired = 404, even if the page was already loaded.

---

## 8. Public-edit — anonymous write (D6 — the security-heavy surface)

**AC-WRITE-01 — Anonymous upload into a shared folder**
- Given a live **public + edit** folder link and policy = edit,
- When an Anonymous visitor uploads a file via the public page's upload affordance,
- Then (all gates passing) the file is stored into the shared folder and **appears live in the owner's Drive**.

**AC-WRITE-02 — Audited as `share:{token}`**
- Given an anonymous upload,
- Then it is audited with **`actor = "share:{token}"`** (never an auth User) via the BL-084 audit seam, and emits the normal **`file.created`** event with that synthetic actor.

**AC-WRITE-03 — Collision = version append (file edit)**
- Given a **public + edit** file link (replace content) or a folder upload colliding on name,
- When the visitor replaces,
- Then a **new `file_versions` row is appended** — bytes are never destroyed, so even anonymous edit is owner-reversible (D3).

**Security gates (must all hold — D6)**
- **WRITE-E1 Own throttle bucket:** anonymous uploads count against **`THROTTLE_SCOPE_DOC_SHARE`** — never the login or form-public bucket; over-limit = 429 + Retry-After.
- **WRITE-E2 Honeypot:** a non-empty honeypot field → **204, stores nothing** (never tips off the bot).
- **WRITE-E3 Sniff hard-floor:** an exe/HTML/SVG (magic-byte detected) is rejected regardless of declared type — same floor as slice 04.
- **WRITE-E4 Tenant type/size policy:** the target folder's/tenant's allowed-types + size cap apply (rejected with the limit named).
- **WRITE-E5 Quota:** an upload that would exceed the tenant storage quota = **413**.
- **WRITE-E6 Per-link caps:** `max_uploads` and `max_total_mb` on the share row cap abuse **independent** of tenant quota — exceeding either is rejected with a clear reason.
- **WRITE-E7 Edit blocked when capability = view:** any write attempt on a view-only link = denied (no upload affordance shown, backend rejects direct).
- **WRITE-E8 No move/delete via link:** the public+edit surface offers upload (+ rename within subtree) only — no move/delete affordance, and direct attempts are refused (D3).

---

## 9. Security checklist (public surface — plan §97–103; all must hold before accept)

**AC-SEC-01 — Uniform 404** for unknown / expired / disabled / over-ceiling tokens (no enumeration). *(= PUBLIC-E1, E3)*

**AC-SEC-02 — Ceiling clamped server-side** at both **mint** and **every serve** — the client is never trusted. *(= SHARE-E1/E2, PUBLIC-E2/E3)*

**AC-SEC-03 — Anonymous writes** ride own throttle bucket, honeypot, sniff floor, tenant quota + per-link caps, audited `actor=share:{token}`, never an auth User. *(= §8 gates)*

**AC-SEC-04 — Polymorphic-leak discipline:** stored `file_share_users.user_id` and `file_links` ids are validated to the share's tenant at **save** AND tenant-scoped at **resolve** — never resolved unscoped. *(= SHARE-E5, §12)*

**AC-SEC-05 — Serving only via CSP-sandbox**, presigned never immutable-cached, ancestry-checked on every fetch. *(= SERVE-01)*

**AC-SEC-06 — `public+edit` mint requires `documents.manage`** (can't grant write you lack). *(= SHARE-E3)*

---

## 10. Guided process & foolproof-UI (user mandate)

**AC-UX-01 — Only valid options offered:** the Public tier is disabled+annotated when ceiling=off; the Edit radio is disabled when ceiling=view or the user lacks `documents.manage`; the user-tier MultiSelect lists only same-tenant users. The dialog can never be configured into a guaranteed server rejection.

**AC-UX-02 — No instructional/how-to copy:** the Share dialog and public page teach nothing procedurally — controls are labelled (Share, Copy link, Revoke, Download, Upload), states are stated (password prompt, "This link has expired."), with no hint/teaching copy.

**AC-UX-03 — Destructive actions guarded:** bulk revoke uses typed-confirm (`ConfirmActionDialog`); a single revoke is reversible by re-minting (REVOKE-E1) — no destructive action is an unexplained one-way click.

**AC-UX-04 — Feedback at every step:** mint → Copy-link confirmation; revoke → list updates; public upload → progress + final state; wrong password → clear retry message; quota/cap/sniff rejections name the reason.

**AC-UX-05 — Copy-link is one obvious action:** minting yields a single copyable URL with a copy button + copied confirmation — never a raw field the user must hand-select.

---

## 11. Responsive (house mandate)

**AC-RESP-01 — Desktop (~1280px):** Share dialog fields, existing-links list, `/documents/shares` Resource list, and the public file/folder page all fit without horizontal scroll.

**AC-RESP-02 — Mobile (~375px):** the Share dialog is full-width and scrollable; the public folder Drive-lite reflows (grid → fewer columns / list); the password gate, closed message and upload affordance are usable; no clipped/overlapping controls.

---

## 12. `file_links` polymorphic seam (D8 — isolation-tested only)

**AC-LINK-01 — Link / unlink / list API**
- Given the `file_links(entity_type, entity_id, file_id)` API,
- When a row is created/listed/deleted,
- Then it behaves correctly tenant-scoped — link points OUT by string (no FK to domain modules, no import).

**AC-LINK-02 — Polymorphic discipline**
- Given a `file_links` create,
- Then `file_id` is validated to the caller's tenant at save (422 if foreign) and tenant-scoped at resolve.

*(Validated by backend tests only this slice — no real consumer exists until Cluster B / BL-101. The UI surfaces nothing for this seam yet.)*

---

## 13. Cross-cutting edge cases (regression guards)

- **X-E1 Tenant isolation:** no share, allow-list entry, or `file_link` from another tenant is ever resolvable or visible (Phase B backend test; oversight list shows own-tenant only).
- **X-E2 Long target names** in the dialog, links list, oversight list and public page truncate with the full name available (ClampedText/tooltip), never breaking layout.
- **X-E3 Slice-04 suites stay green:** Drive browse/upload/version/trash/quota behavior is unchanged by this slice.
- **X-E4 White-label:** the public page shows the tenant's branding (or its NAME when no logo) and never the FoundryX wordmark; a missing branding asset falls back to the name, not a 500/broken image.
- **X-E5 Token is a bearer capability:** the token grants exactly the share's scope — guessing/altering it = 404; it never widens access beyond its tier/capability/target.

---

## Traceability — acceptance group → plan decision

| Acceptance group | Plan decision(s) |
|---|---|
| §1 Share dialog (mint) | D1 (file or folder), D2 (3 tiers), D3 (view/edit), D5 (ceiling-aware), D7 (token/expiry/password), D11 (UI) |
| §2 Revoke | D8 (soft `is_disabled`, keep audit), D11 |
| §3 Oversight page | D11 (`/documents/shares`), D12 (`documents.share` gate) |
| §4 Internal & user tiers | D2 (internal=own-tenant auth; user=named allow-list), D8 (`file_share_users`) |
| §5 Public resolve / state envelope | D9 (state envelope, uniform-404), D5 (ceiling), D7 (password/expiry), D11 (white-label page) |
| §6 Folder live-follow | D4 (recursive, resolve-time ancestry walk) |
| §7 Public file serving | D6/D9 (CSP-sandbox, presigned-not-cached, ancestry-checked) |
| §8 Public-edit anonymous write | D6 (throttle/honeypot/sniff/quota/per-link caps/audit), D3 (edit=version append) |
| §9 Security checklist | Plan security checklist §97–103 |
| §10 Guided/foolproof UX | Foolproof-UI + no-inline-instructions + only-valid-options mandates |
| §11 Responsive | House responsive mandate |
| §12 `file_links` seam | D8 (polymorphic seam, isolation-tested) |
| §13 Cross-cutting | Tenant-scoping invariant, polymorphic-leak discipline, ClampedText, white-label |

---

## Explicitly OUT of scope (→ backlog — must NOT appear/work yet)

- **BL-101** — wiring `file_links` to Cluster B quotation attach (first real consumer; seam is isolation-tested only here).
- **BL-102** — dedicated `file.shared` workflow trigger (anonymous uploads still fire the normal `file.created` event).
- **BL-103** — share-link analytics / view counts.
- **BL-104** — download-as-PDF watermark on the public view.
- **BL-105** — notify-on-access / access-request flow.

## Acceptance gate

Slice 05 is **accepted** when: every §1–§13 criterion (incl. edge cases) passes at desktop + mobile; the §9 security checklist holds in full; backend pytest covers ceiling-clamp (mint+serve), uniform-404, password+throttle, folder live-follow reachability, public-edit honeypot/sniff/quota/cap, anonymous-write audit + version append, `file_share_users` cross-tenant reject + scoped resolve, `file_links` isolation, revoke-kills-access; Playwright `e2e/documents-sharing.spec.ts` green; Test Execution Report `05-document-mgmt-sharing-test-report.md` filed; code review approved.
