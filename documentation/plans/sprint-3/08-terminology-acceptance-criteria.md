# Sprint 3 · Plan 08 — Terminology · User Acceptance Criteria

**Plan:** `08-terminology.md` · **Foundation:** F10 (first of F10→F8→F9→F4)
**Gate role:** must MERGE green before plan 09 starts (continuous 08→11 objective).

Each criterion is **Given / When / Then**, traceable to a locked decision (Dn) and one or
more **philosophy pillars**: 🟢 Functional SaaS · 📈 Scalable · 🧭 Guided UX · ✅ Validated.
A criterion is **MET** only when its acceptance test (backend pytest / vitest / Playwright)
is green AND verified at both 375px and 1280px where it renders UI.

---

## 1. Functional SaaS — the feature works end-to-end 🟢

- **AC-08-01 (D6/D7) Rename is instant, no reload, no re-login.**
  *Given* an Admin on `/settings/terminology`, *when* they rename "Form" → "Survey"/"Surveys"
  and Save, *then* the sidebar item, `/forms` list title, breadcrumb, and "Create" button all
  read "Survey(s)" without a page reload or re-login (provider refetch on edit).

- **AC-08-02 (D5/D7) Reset reverts to the code default.**
  *Given* an overridden key, *when* the Admin clicks "Reset to default", *then* the override row
  is deleted (204) and every surface reverts to the `TermDef` default on the next resolve.

- **AC-08-03 (D2/D3) Override requires both singular AND plural, non-blank.**
  *Given* the edit dialog, *when* singular or plural is blank, *then* Save is blocked
  client-side and `PUT` returns 422 server-side (both forms stored explicitly — no auto-plural).

- **AC-08-04 (D6) `GET /terminology` returns the merged map.**
  *Given* a tenant with one override, *when* the client fetches `/terminology`, *then* the
  response = code defaults ⊕ that tenant's override rows, keyed `{key:{singular,plural}}`.

- **AC-08-05 (D7) Missing/unregistered key never renders blank.**
  *Given* a surface resolving an unregistered key, *when* `label(key)` is called, *then* it
  returns a humanized form of the key (never empty string, never a crash).

- **AC-08-06 (D9) Edit is gated `terminology.manage`; read is authenticated-only.**
  *Given* a user without `terminology.manage`, *when* they open `/settings/terminology`, *then*
  the page renders read-only / `NoPermission` and `PUT`/`DELETE` 403; `GET /terminology` works
  for any authenticated user (labels not secret).

## 2. Scalable / multi-tenant 📈

- **AC-08-07 (D4/D5) Strict tenant isolation.**
  *Given* tenant A renames "Form"→"Survey", *when* tenant B (other browser) loads any surface,
  *then* tenant B sees the unchanged default — A's override is invisible to B.

- **AC-08-08 (D6) Delivery is one cached config endpoint, NOT the JWT.**
  *Given* a rename, *then* no token is reissued and no field is added to the JWT (a rename must
  not force re-login); the `TerminologyProvider` fetches once + refetches on edit.

- **AC-08-09 (D1/D2/D10) Mechanism is core + module-extensible, not EMS-specific.**
  *Given* the registry, *when* a module calls `register_term(TermDef)` at install, *then* its
  entities appear on the settings page and resolve through `useTerminology` with zero core edits
  (same seam EMS uses in plan 11 for `project`/`profile`).

- **AC-08-10 (D8) All three menu arrays + both renderers resolve `termKey`.**
  *Given* a relabelable entry tagged `termKey` in `MENU_SIDEBAR`, `MENU_MEGA`, `MENU_MEGA_MOBILE`,
  *when* rendered on desktop and mobile, *then* every surface shows `labelPlural(termKey)` (static
  `title` fallback); `filterMenu` visibility behavior is unchanged.

## 3. Guided UX 🧭

- **AC-08-11 (D9) Settings page is self-evident, no instructional copy.**
  *Given* `/settings/terminology`, *then* it lists every `TermDef` (Entity · Group/module ·
  Default · Current label · Edit/Reset) on the Resource shell with loading/empty/error states —
  controls speak for themselves (foolproof-UI mandate; no how-to text).

- **AC-08-12 The current vs default label is always visible** so the operator sees exactly what
  the rename changes before/after Save.

- **AC-08-13 (house mandate) Responsive.** The settings table reflows / horizontally scrolls
  cleanly at 375px and 1280px — no clipped controls, no horizontal page scroll.

## 4. Validated quality ✅

- **AC-08-14 Backend tests green** (`tests/test_terminology.py`): registry seed present · merged
  map = defaults⊕overrides · PUT upsert + 422 unknown-key + blank-reject · DELETE reset →
  fallback · tenant isolation · perm gate (manage for PUT/DELETE, authenticated GET).

- **AC-08-15 Frontend tests green** (vitest): `use-terminology` resolves override > default >
  humanized-fallback · `t(key,count)` singular/plural · provider refetch after `setTerm`.

- **AC-08-16 E2E green** (`e2e/terminology.spec.ts`, real clicks, both viewports): ① rename
  Form→Survey → assert all four surfaces → Reset reverts; ② second provisioned tenant unaffected.

- **AC-08-17 House rules honored:** no DB/raw SQL in the router · schemas inherit `ApiModel`
  (camelCase) · UTCDateTime import added to the autogen migration · `terminology.manage` in
  `permissions.csv` + `tenant_admin_grant`.

- **AC-08-18 Code review approved** before merge to `main`; test report `08-terminology-test-report.md`
  written.

---

## Definition of Done (plan 08)
All AC-08-* MET · suites green · E2E report filed · reviewer approved · merged to `main`.
**Continuity gate:** plan 09's history-list title resolves through this terminology layer — do
not start 09 until AC-08-09 (module-extensible registry) and AC-08-16 (E2E) are green.
