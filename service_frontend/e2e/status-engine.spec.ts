import { expect, test, type Page } from '@playwright/test';

/**
 * Status Engine E2E (sprint-2/01, reworked UI) — real user clicks against the
 * LIVE stack. Requires backend up + bootstrapped (`python -m scripts.bootstrap_db`).
 *
 * Surface shape follows the Resource design language: Platform Engines ▸
 * Status Engine = entity LIST → row click = entity detail FORM (Flow +
 * Statuses tabs) → global Edit toggle unlocks the canvas. Covers: add status
 * via drawer → drag-create a transition → edge select toolbar (Edit/Delete)
 * → notification round-trip → machine-driven suspend → permission gating.
 *
 * Spec isolation: created rows are timestamped + cleaned up; the dedicated
 * tenant carries an `e2e-` slug (residue rule).
 */

const PLATFORM_HOST = 'http://platform.localhost:3001';

async function login(page: Page, base: string, email: string, password: string) {
  await page.goto(`${base}/signin`);
  await page.getByPlaceholder('Your email').fill(email);
  await page.getByPlaceholder('Your password').fill(password);
  await page.getByRole('button', { name: /sign in/i }).click();
}

async function loginOperator(page: Page) {
  await login(page, PLATFORM_HOST, 'platform@example.com', 'platform1234');
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));
}

async function gotoStatusEngineList(page: Page) {
  // "Platform Engines" is a grouping parent — the navigable entry is a child.
  const link = page.getByRole('link', { name: 'Status Engine', exact: true });
  if (!(await link.isVisible().catch(() => false))) {
    await page.getByText('Platform Engines', { exact: true }).click();
  }
  await link.click();
  await expect(page).toHaveURL(/\/platform\/status-engine$/);
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars -- kept as the documented entity-open path for future specs
async function openTenantEntity(page: Page) {
  await gotoStatusEngineList(page);
  // Entity list rides the Resource shell — row click opens the detail form.
  await page.getByRole('row', { name: /Tenant/ }).getByText('Tenant', { exact: true }).click();
  await expect(page).toHaveURL(/\/platform\/status-engine\/tenant/);
  await expect(page.getByTestId('entity-flow')).toBeVisible();
}

async function enterEditMode(page: Page) {
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
}

test.describe('Status Engine (live stack)', () => {
  test('entity list → detail form: graph editing, edge toolbar, notification round-trip', async ({
    page,
  }) => {
    const ts = Date.now();
    const holdLabel = `E2E Hold ${ts}`;
    const holdKey = `e2e_hold_${ts}`;
    const edgeLabel = `Hold ${ts}`;

    await loginOperator(page);

    // List surface: the Tenant entity with its stats.
    await gotoStatusEngineList(page);
    const tenantRow = page.getByRole('row', { name: /Tenant/ });
    await expect(tenantRow.getByText('core')).toBeVisible();
    await expect(tenantRow.getByText('Platform defaults')).toBeVisible();

    // Detail form: seeded graph renders read-only.
    await tenantRow.getByText('Tenant', { exact: true }).click();
    await expect(page).toHaveURL(/\/platform\/status-engine\/tenant/);
    await expect(page.getByTestId('status-node-active')).toBeVisible();
    await expect(page.getByTestId('status-node-suspended')).toBeVisible();
    await expect(page.getByTestId('status-node-archived')).toBeVisible();
    // (The read-only instructional caption was removed by the foolproof-UI
    // no-inline-instructions sweep; read-only state shows as a disabled canvas.)
    // Archived is restorable (sprint-2/02 revision) — outgoing handle present.
    await expect(
      page.getByTestId('status-node-archived').getByTestId('source-handle'),
    ).toHaveCount(1);

    // Edit unlocks the canvas (read-by-default form invariant).
    await enterEditMode(page);
    await expect(page.getByRole('button', { name: /add status/i })).toBeVisible();

    // ---- Add a status via the drawer ----
    await page.getByRole('button', { name: /add status/i }).click();
    await page.getByLabel(/Label/).fill(holdLabel);
    await page.getByRole('switch', { name: 'Blocks access' }).click();
    await page.getByRole('button', { name: 'Create', exact: true }).click();
    const holdNode = page.getByTestId(`status-node-${holdKey}`);
    await expect(holdNode).toBeVisible();
    // The drawer's closing overlay would swallow the canvas drag — wait it out.
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await page.waitForTimeout(400);

    // ---- Draw a transition: drag Active's source handle onto the new node ----
    const sourceHandle = page
      .getByTestId('status-node-active')
      .getByTestId('source-handle');
    const targetHandle = holdNode.getByTestId('target-handle');
    const sourceBox = await sourceHandle.boundingBox();
    const targetBox = await targetHandle.boundingBox();
    if (!sourceBox || !targetBox) throw new Error('canvas handles not measurable');
    await page.mouse.move(sourceBox.x + sourceBox.width / 2, sourceBox.y + sourceBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(targetBox.x + targetBox.width / 2, targetBox.y + targetBox.height / 2, {
      steps: 12,
    });
    await page.mouse.up();

    // The edge drawer opens for the pending connection.
    await expect(page.getByText(new RegExp(`Active → ${holdLabel}`))).toBeVisible();
    await page.getByLabel(/Action label/).fill(edgeLabel);
    await page.getByRole('button', { name: /add notification/i }).click();
    await page.getByPlaceholder(/Subject — e.g./).fill(`{{recordLabel}} held ${ts}`);
    await page.getByPlaceholder('Body…').fill('{{actorName}} performed {{transitionLabel}}.');
    await page.getByRole('button', { name: 'Create transition' }).click();
    await expect(page.getByText(edgeLabel, { exact: true })).toBeVisible();
    await expect(page.getByRole('dialog')).toHaveCount(0);

    // ---- Click the connection → floating toolbar (Edit / Delete) ----
    await page.getByText(edgeLabel, { exact: true }).dispatchEvent('click');
    const toolbar = page.getByTestId('edge-toolbar');
    await expect(toolbar).toBeVisible();
    await toolbar.getByRole('button', { name: 'Edit' }).click();

    // Notification round-trip persisted.
    await expect(page.getByText(new RegExp(`Active → ${holdLabel}`))).toBeVisible();
    await expect(page.getByPlaceholder(/Subject — e.g./)).toHaveValue(
      `{{recordLabel}} held ${ts}`,
    );
    await page.getByRole('button', { name: 'Save', exact: true }).last().click();
    await expect(page.getByRole('dialog')).toHaveCount(0);

    // ---- Tidy: auto-layout re-ranks the graph and keeps everything visible ----
    await page.getByRole('button', { name: 'Tidy' }).click();
    await page.waitForTimeout(500); // layout + fitView animation
    await expect(page.getByTestId('status-node-active')).toBeVisible();
    await expect(holdNode).toBeVisible();
    await expect(page.getByText(edgeLabel, { exact: true })).toBeVisible();

    // ---- Delete the connection from the toolbar ----
    await page.getByText(edgeLabel, { exact: true }).dispatchEvent('click');
    await toolbar.getByRole('button', { name: 'Delete' }).click();
    await expect(page.getByText(edgeLabel, { exact: true })).toHaveCount(0);

    // ---- Cleanup: delete the created status (no records → allowed) ----
    await holdNode.click();
    await page.getByRole('button', { name: 'Delete', exact: true }).click();
    await expect(page.getByTestId(`status-node-${holdKey}`)).toHaveCount(0);
  });

  test('suspend fires through the status machine; engine labels render in the console', async ({
    page,
  }) => {
    const slug = `e2e-se-${Date.now()}`;
    const name = `E2E SE ${slug}`;

    await loginOperator(page);

    // Provision a dedicated tenant (spec isolation — parallel-safe).
    await page.getByText('Tenant Management', { exact: true }).click();
    await page.getByRole('link', { name: 'Tenants', exact: true }).click();
    await page.getByRole('button', { name: /add tenant/i }).click();
    await page.getByPlaceholder('e.g. Acme Events').fill(name);
    await page.getByPlaceholder('e.g. acme-events').fill(slug);
    await page.getByPlaceholder('e.g. Kay Meister').fill('E2E Admin');
    await page.getByPlaceholder('admin@tenant.com').fill(`admin@${slug}.example.com`);
    await page.getByPlaceholder('At least 8 characters').fill('ChangeMe1!');
    await page.getByRole('button', { name: /^create$/i }).click();
    await expect(page).toHaveURL(/\/platform\/tenants\/(?!new)/);

    // Suspend via the console — the backend routes this through the status
    // machine (strict edge Active → Suspended). Scope to the sidebar (the
    // detail page breadcrumb carries a second "Tenants" link).
    await page
      .getByLabel('Tenant Management')
      .getByRole('link', { name: 'Tenants', exact: true })
      .click();
    await page.getByPlaceholder('Search tenants…').fill(slug);
    await expect(page.getByText('FoundryX EMS')).toHaveCount(0);
    const row = page.getByRole('row', { name: new RegExp(name) });
    await expect(row).toBeVisible();
    await page.waitForTimeout(800);
    await row.getByRole('button', { name: 'Actions' }).click();
    await page.getByRole('menuitem', { name: 'Suspend' }).click();
    await page.getByRole('button', { name: 'Suspend tenant' }).click();
    // The badge shows the ENGINE's editable label (server statusLabel).
    await expect(row.getByText('Suspended')).toBeVisible();

    // Suspending twice is impossible — no Suspended → Suspended edge: the
    // action list now offers Reactivate/Archive instead.
    await row.getByRole('button', { name: 'Actions' }).click();
    await expect(page.getByRole('menuitem', { name: 'Suspend' })).toHaveCount(0);
    await expect(page.getByRole('menuitem', { name: 'Reactivate' })).toBeVisible();
  });

  test('tenant admin sees an empty entity list (platform-owned entities hidden)', async ({
    page,
  }) => {
    await login(page, 'http://localhost:3001', 'demo@example.com', 'demo1234');
    await page.waitForURL((url) => !url.pathname.startsWith('/signin'));

    await page.getByText('Settings', { exact: true }).click();
    await page.getByRole('link', { name: 'Statuses', exact: true }).click();
    await expect(page).toHaveURL(/\/settings\/statuses$/);
    // Tenant callers don't see the platform-owned tenant entity; no module
    // has registered a tenant-owned entity yet — the Resource list is empty.
    await expect(page.getByText('No data available')).toBeVisible();
  });

  test('user without statuses.read gets the friendly NoPermission page', async ({ page }) => {
    // demo@kt.com holds only the Member role — no statuses.* keys.
    await login(page, 'http://localhost:3001', 'demo@kt.com', 'demo1234');
    await page.waitForURL((url) => !url.pathname.startsWith('/signin'));

    // Since plan sprint-2/05 (BL-014) the menu entry itself is pruned for a
    // session without statuses.read — a real user can't click their way in.
    await expect(
      page.getByRole('link', { name: 'Statuses', exact: true }),
    ).toBeHidden();

    // The page guard stays the boundary: direct navigation (bookmark/old
    // link) still lands on the friendly NoPermission page, never a raw 403.
    await page.goto('http://localhost:3001/settings/statuses');
    await expect(page.getByText('You don’t have access to this page')).toBeVisible();
  });
});
