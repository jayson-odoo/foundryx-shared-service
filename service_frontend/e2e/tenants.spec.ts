import { expect, test, type Page } from '@playwright/test';

/**
 * Platform Console → Tenants E2E (plan 07 Phase C) — real user clicks against
 * the LIVE stack (Next :3001 → FastAPI :8001 → Postgres). Requires the backend
 * up + bootstrapped (`python -m scripts.bootstrap_db`).
 *
 * Tenant resolution is subdomain-based (plan 07 §6): the operator signs in at
 * platform.localhost; a provisioned tenant's admin at <slug>.localhost
 * (browsers resolve *.localhost to 127.0.0.1). Navigates by clicking the UI;
 * never URL-jumps into protected pages (per governance).
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

async function gotoTenants(page: Page) {
  // Scope to the sidebar — detail pages carry a second "Tenants" breadcrumb
  // link (strict-mode collision); expand the group if collapsed.
  const link = page
    .getByLabel('Tenant Management')
    .getByRole('link', { name: 'Tenants', exact: true });
  if (!(await link.isVisible().catch(() => false))) {
    await page.getByText('Tenant Management', { exact: true }).click();
  }
  await link.click();
  await expect(page).toHaveURL(/\/platform\/tenants$/);
  await expect(
    page.getByText('Manage tenants on this deployment — provision, suspend and archive tenants.'),
  ).toBeVisible();
}

function rowByName(page: Page, name: string) {
  return page.getByRole('row', { name: new RegExp(name) });
}

/** Search and wait for the filtered list to settle (other rows gone) so the
 *  row + its action menu don't detach mid-click as the table re-renders. */
async function searchAndSettle(page: Page, slug: string) {
  await page.getByPlaceholder('Search tenants…').fill(slug);
  await expect(page.getByText('FoundryX EMS')).toHaveCount(0);
  await expect(rowByName(page, slug)).toBeVisible();
  // Outlast the trailing debounced refetch — it re-renders the rows and would
  // detach a just-opened action menu mid-click.
  await page.waitForTimeout(800);
}

test.describe('Platform Console — Tenants (live stack)', () => {
  test('operator sees the console; seeded tenants listed', async ({ page }) => {
    await loginOperator(page);

    // Platform menu section is visible to the operator…
    await expect(page.getByText('Platform', { exact: true })).toBeVisible();
    await gotoTenants(page);

    // …listing the seeded tenants, with the platform badge on the operator
    // row. SEARCH first — a fullyParallel run provisions sibling e2e tenants
    // mid-suite that crowd seeded rows off page 1 (created-desc default).
    await page.getByPlaceholder('Search tenants…').fill('FoundryX');
    await expect(page.getByText('FoundryX EMS')).toBeVisible();
    await expect(
      rowByName(page, 'FoundryX Platform').getByText('Platform', { exact: true }),
    ).toBeVisible();
  });

  test('tenant admin has no Platform menu and no console access', async ({ page }) => {
    await login(page, 'http://localhost:3001', 'demo@example.com', 'demo1234');
    await page.waitForURL((url) => !url.pathname.startsWith('/signin'));

    await expect(page.getByText('Tenant Management', { exact: true })).toHaveCount(0);
    await expect(page.getByText('Platform', { exact: true })).toHaveCount(0);
  });

  test('platform tenant row has no lifecycle actions', async ({ page }) => {
    await loginOperator(page);
    await gotoTenants(page);

    // Search first — sibling specs' tenants can push this row off page 1.
    await page.getByPlaceholder('Search tenants…').fill('FoundryX Platform');
    const platform = rowByName(page, 'FoundryX Platform');
    await platform.getByRole('button', { name: 'Actions' }).click();
    await expect(page.getByRole('menuitem', { name: 'Suspend' })).toHaveCount(0);
    await expect(page.getByRole('menuitem', { name: 'Archive' })).toHaveCount(0);
    await expect(page.getByRole('menuitem', { name: 'Edit' })).toBeVisible();
  });

  test('provision → suspend blocks login → reactivate → archive', async ({ page }) => {
    const slug = `e2e-${Date.now()}`;
    const name = `E2E ${slug}`;
    const adminEmail = `admin@${slug}.example.com`;

    await loginOperator(page);
    await gotoTenants(page);

    // Provision.
    await page.getByRole('button', { name: /add tenant/i }).click();
    await expect(page).toHaveURL(/\/platform\/tenants\/new$/);
    await page.getByPlaceholder('e.g. Acme Events').fill(name);
    await page.getByPlaceholder('e.g. acme-events').fill(slug);
    await page.getByPlaceholder('e.g. Kay Meister').fill('E2E Admin');
    await page.getByPlaceholder('admin@tenant.com').fill(adminEmail);
    await page.getByPlaceholder('At least 8 characters').fill('ChangeMe1!');
    await page.getByRole('button', { name: /^create$/i }).click();
    await expect(page).toHaveURL(/\/platform\/tenants\/(?!new)/);
    await expect(page.getByRole('heading', { name })).toBeVisible();

    // The new tenant's admin signs in at its subdomain.
    const tenantBase = `http://${slug}.localhost:3001`;
    await login(page, tenantBase, adminEmail, 'ChangeMe1!');
    await page.waitForURL((url) => !url.pathname.startsWith('/signin'));

    // Operator suspends it.
    await loginOperator(page);
    await gotoTenants(page);
    await searchAndSettle(page, slug);
    const row = rowByName(page, name);
    await row.getByRole('button', { name: 'Actions' }).click();
    await page.getByRole('menuitem', { name: 'Suspend' }).click();
    await expect(page.getByText('Suspend this tenant?')).toBeVisible();
    await page.getByRole('button', { name: 'Suspend tenant' }).click();
    await expect(row.getByText('Suspended')).toBeVisible();

    // Suspended tenant's admin can no longer sign in.
    await login(page, tenantBase, adminEmail, 'ChangeMe1!');
    await expect(page).toHaveURL(/\/signin/);

    // Reactivate restores access.
    await loginOperator(page);
    await gotoTenants(page);
    await searchAndSettle(page, slug);
    await row.getByRole('button', { name: 'Actions' }).click();
    await page.getByRole('menuitem', { name: 'Reactivate' }).click();
    // Graph-driven actions (sprint-2/01) confirm every transition.
    await page.getByRole('button', { name: 'Reactivate tenant' }).click();
    await expect(row.getByText('Active', { exact: true })).toBeVisible();

    await login(page, tenantBase, adminEmail, 'ChangeMe1!');
    await page.waitForURL((url) => !url.pathname.startsWith('/signin'));

    // Archive: leaves the Active view, lands in the Archived view.
    await loginOperator(page);
    await gotoTenants(page);
    await searchAndSettle(page, slug);
    await row.getByRole('button', { name: 'Actions' }).click();
    await page.getByRole('menuitem', { name: 'Archive' }).click();
    await expect(page.getByText('Archive this tenant?')).toBeVisible();
    await page.getByRole('button', { name: 'Archive tenant' }).click();
    await expect(page.getByText(name)).toHaveCount(0);

    await page.getByPlaceholder('Search tenants…').clear();
    await page.getByRole('radio', { name: 'Archived' }).click();
    await page.getByPlaceholder('Search tenants…').fill(slug);
    await expect(page.getByText(name)).toBeVisible();

    // ---- Delete permanently (BL-035): typed slug confirm, irreversible ----
    await page.waitForTimeout(800);
    await rowByName(page, name).getByRole('button', { name: 'Actions' }).click();
    await page.getByRole('menuitem', { name: 'Delete permanently' }).click();
    await expect(page.getByText('Delete permanently?')).toBeVisible();
    // Button stays disabled until the slug is typed exactly.
    const confirmButton = page.getByRole('button', { name: 'Delete forever' });
    await expect(confirmButton).toBeDisabled();
    await page.getByLabel('Confirmation text').fill(slug);
    await confirmButton.click();
    await expect(page.getByText(name)).toHaveCount(0);
    // Gone from BOTH views — the spec cleans its own residue.
    await page.getByRole('radio', { name: 'Active' }).click();
    await page.getByPlaceholder('Search tenants…').fill(slug);
    await expect(page.getByText(name)).toHaveCount(0);
  });

  test('bulk archive works across mixed Active + Suspended selections', async ({ page }) => {
    // Same semantic action via DIFFERENT edges (active→archived vs
    // suspended→archived) — label-grouped actions keep the bulk menu alive.
    const ts = Date.now();
    const slugA = `e2e-bulk-a-${ts}`;
    const slugB = `e2e-bulk-b-${ts}`;

    await loginOperator(page);
    for (const [slug, name] of [
      [slugA, `E2E Bulk A ${ts}`],
      [slugB, `E2E Bulk B ${ts}`],
    ]) {
      await gotoTenants(page);
      await page.getByRole('button', { name: /add tenant/i }).click();
      await page.getByPlaceholder('e.g. Acme Events').fill(name);
      await page.getByPlaceholder('e.g. acme-events').fill(slug);
      await page.getByPlaceholder('e.g. Kay Meister').fill('E2E Admin');
      await page.getByPlaceholder('admin@tenant.com').fill(`admin@${slug}.example.com`);
      await page.getByPlaceholder('At least 8 characters').fill('ChangeMe1!');
      await page.getByRole('button', { name: /^create$/i }).click();
      await expect(page).toHaveURL(/\/platform\/tenants\/(?!new)/);
    }

    // Suspend B so the selection mixes statuses.
    await gotoTenants(page);
    await searchAndSettle(page, slugB);
    await rowByName(page, slugB).getByRole('button', { name: 'Actions' }).click();
    await page.getByRole('menuitem', { name: 'Suspend' }).click();
    await page.getByRole('button', { name: 'Suspend tenant' }).click();
    await expect(rowByName(page, slugB).getByText('Suspended')).toBeVisible();

    // Select both (search narrows to the pair) → bulk Archive appears.
    await page.getByPlaceholder('Search tenants…').fill(`e2e-bulk`);
    await expect(rowByName(page, slugA)).toBeVisible();
    await page.waitForTimeout(800);
    await rowByName(page, slugA).getByRole('checkbox').check();
    await rowByName(page, slugB).getByRole('checkbox').check();
    await page.getByRole('button', { name: 'Bulk actions' }).click();
    await page.getByRole('menuitem', { name: 'Archive' }).click();
    await page.getByRole('button', { name: 'Archive tenant' }).click();
    await expect(rowByName(page, slugA)).toHaveCount(0);
    await expect(rowByName(page, slugB)).toHaveCount(0);

    // Cleanup: bulk delete from the Archived view (typed DELETE).
    await page.getByRole('radio', { name: 'Archived' }).click();
    await page.getByPlaceholder('Search tenants…').fill('e2e-bulk');
    await expect(rowByName(page, slugA)).toBeVisible();
    await page.waitForTimeout(800);
    await rowByName(page, slugA).getByRole('checkbox').check();
    await rowByName(page, slugB).getByRole('checkbox').check();
    await page.getByRole('button', { name: 'Bulk actions' }).click();
    await page.getByRole('menuitem', { name: 'Delete permanently' }).click();
    await page.getByLabel('Confirmation text').fill('DELETE');
    await page.getByRole('button', { name: 'Delete forever' }).click();
    await expect(rowByName(page, slugA)).toHaveCount(0);
    await expect(rowByName(page, slugB)).toHaveCount(0);
  });

  test('reserved slug rejected at validation', async ({ page }) => {
    await loginOperator(page);
    await gotoTenants(page);
    await page.getByRole('button', { name: /add tenant/i }).click();

    await page.getByPlaceholder('e.g. Acme Events').fill('Bad Slug Co');
    await page.getByPlaceholder('e.g. acme-events').fill('platform');
    await page.getByPlaceholder('e.g. Kay Meister').fill('Bad Admin');
    await page.getByPlaceholder('admin@tenant.com').fill('bad@bad-co.com');
    await page.getByPlaceholder('At least 8 characters').fill('ChangeMe1!');
    await page.getByRole('button', { name: /^create$/i }).click();

    await expect(page.getByText('This slug is reserved.')).toBeVisible();
    await expect(page).toHaveURL(/\/platform\/tenants\/new$/);
  });
});
