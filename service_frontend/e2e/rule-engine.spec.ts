import { expect, test, type Page } from '@playwright/test';

/**
 * Rule Engine E2E (sprint-2/02) - real user clicks against the LIVE stack.
 * Requires backend up + bootstrapped.
 *
 * Covers the full loop: build a condition on a transition edge (drawer
 * RuleBuilder) → the Rules observability page lists it + deep-links back →
 * the console hides the rule-blocked action for a non-qualifying record
 * while qualifying records still pass → cleanup.
 *
 * Parallel-safety: the condition is `Slug is not <e2e-tenant-slug>` on the
 * platform Active → Suspended edge - TRUE for every record except the
 * spec's own timestamped tenant, so concurrent specs that suspend their own
 * tenants are unaffected. Cleanup removes the condition either way.
 */

const PLATFORM_HOST = 'http://platform.localhost:3001';

async function loginOperator(page: Page) {
  await page.goto(`${PLATFORM_HOST}/signin`);
  await page.getByPlaceholder('Your email').fill('platform@example.com');
  await page.getByPlaceholder('Your password').fill('platform1234');
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));
}

async function openPlatformEnginesChild(page: Page, label: string) {
  const link = page.getByRole('link', { name: label, exact: true });
  if (!(await link.isVisible().catch(() => false))) {
    await page.getByText('Platform Engines', { exact: true }).click();
  }
  await link.click();
}

async function gotoTenantsList(page: Page) {
  // Sidebar accordion: expanding another group collapses this one.
  const link = page
    .getByLabel('Tenant Management')
    .getByRole('link', { name: 'Tenants', exact: true });
  if (!(await link.isVisible().catch(() => false))) {
    await page.getByText('Tenant Management', { exact: true }).click();
  }
  await link.click();
  await expect(page).toHaveURL(/\/platform\/tenants$/);
}

async function provisionTenant(page: Page, name: string, slug: string) {
  await gotoTenantsList(page);
  await page.getByRole('button', { name: /add tenant/i }).click();
  await page.getByPlaceholder('e.g. Acme Events').fill(name);
  await page.getByPlaceholder('e.g. acme-events').fill(slug);
  await page.getByPlaceholder('e.g. Kay Meister').fill('E2E Admin');
  await page
    .getByPlaceholder('admin@tenant.com')
    .fill(`admin@${slug}.example.com`);
  await page.getByPlaceholder('At least 8 characters').fill('ChangeMe1!');
  await page.getByRole('button', { name: /^create$/i }).click();
  await expect(page).toHaveURL(/\/platform\/tenants\/(?!new)/);
}

async function openSuspendEdgeDrawer(page: Page) {
  await openPlatformEnginesChild(page, 'Status Engine');
  await expect(page).toHaveURL(/\/platform\/status-engine$/);
  await page
    .getByRole('row', { name: /Tenant/ })
    .getByText('Tenant', { exact: true })
    .click();
  await expect(page.getByTestId('entity-flow')).toBeVisible();
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  // SVG edge labels need a dispatched click (Playwright hit-testing misses).
  await page
    .getByText('Suspend', { exact: true })
    .first()
    .dispatchEvent('click');
  await page
    .getByTestId('edge-toolbar')
    .getByRole('button', { name: 'Edit' })
    .click();
  await expect(page.getByText(/Transition - Active → Suspended/)).toBeVisible();
}

test.describe('Rule Engine (live stack)', () => {
  test('edge condition: build → observe on Rules page → console enforcement → cleanup', async ({
    page,
  }) => {
    const ts = Date.now();
    const slug = `e2e-rule-${ts}`;
    const name = `E2E Rule ${ts}`;

    await loginOperator(page);

    // A dedicated tenant the condition will single out (spec isolation).
    await provisionTenant(page, name, slug);

    // ---- Build the condition in the edge drawer ----
    await openSuspendEdgeDrawer(page);
    await page.getByRole('button', { name: /add condition/i }).click();

    // Fact: Tenant record · Slug (facts arrive from GET /rule-facts).
    await page.getByRole('combobox', { name: 'Fact' }).click();
    await page.getByPlaceholder('Search fields…').fill('Slug');
    await page.getByRole('option', { name: 'Slug' }).click();
    // Operator: "is not" - passes for everyone EXCEPT the e2e tenant.
    await page.getByRole('combobox', { name: 'Operator' }).click();
    await page.getByRole('option', { name: 'is not', exact: true }).click();
    await page.getByPlaceholder('Value').fill(slug);
    await page
      .getByRole('button', { name: 'Save', exact: true })
      .last()
      .click();
    await expect(page.getByRole('dialog')).toHaveCount(0);

    // Round-trip: reopen - the condition persisted server-side.
    await page
      .getByText('Suspend', { exact: true })
      .first()
      .dispatchEvent('click');
    await page
      .getByTestId('edge-toolbar')
      .getByRole('button', { name: 'Edit' })
      .click();
    await expect(page.getByRole('combobox', { name: 'Fact' })).toHaveText(
      /Slug/,
    );
    await expect(page.getByPlaceholder('Value')).toHaveValue(slug);
    await page.getByRole('button', { name: 'Close' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);

    // ---- Rules observability page lists it + deep-links back ----
    await openPlatformEnginesChild(page, 'Rules');
    await expect(page).toHaveURL(/\/platform\/rules$/);
    const ruleRow = page.getByRole('row', { name: /Active → Suspended/ });
    await expect(ruleRow).toBeVisible();
    await expect(ruleRow.getByText(/Slug is not/)).toBeVisible();
    await ruleRow.getByText('Status transition').click();
    await expect(page).toHaveURL(/\/platform\/status-engine\/tenant/);

    // ---- Enforcement: the non-qualifying tenant loses the Suspend action ----
    await gotoTenantsList(page);
    await page.getByPlaceholder('Search tenants…').fill(slug);
    const row = page.getByRole('row', { name: new RegExp(name) });
    await expect(row).toBeVisible();
    await page.waitForTimeout(800);
    await row.getByRole('button', { name: 'Actions' }).click();
    // Rule-blocked edge is HIDDEN (like role-blocked); unconditional Archive stays.
    await expect(page.getByRole('menuitem', { name: 'Archive' })).toBeVisible();
    await expect(page.getByRole('menuitem', { name: 'Suspend' })).toHaveCount(
      0,
    );
    await page.keyboard.press('Escape');

    // ---- Cleanup: remove the condition; Suspend returns for the tenant ----
    await openSuspendEdgeDrawer(page);
    await page.getByRole('button', { name: 'Remove condition' }).click();
    await expect(
      page.getByText('No conditions - always allowed', { exact: false }),
    ).toBeVisible();
    await page
      .getByRole('button', { name: 'Save', exact: true })
      .last()
      .click();
    await expect(page.getByRole('dialog')).toHaveCount(0);

    await gotoTenantsList(page);
    await page.getByPlaceholder('Search tenants…').fill(slug);
    await expect(
      page.getByRole('row', { name: new RegExp(name) }),
    ).toBeVisible();
    await page.waitForTimeout(800);
    await page
      .getByRole('row', { name: new RegExp(name) })
      .getByRole('button', { name: 'Actions' })
      .click();
    await expect(page.getByRole('menuitem', { name: 'Suspend' })).toBeVisible();
  });

  test('tenant admin reaches the Rules page (rules.read via Admin grant)', async ({
    page,
  }) => {
    await page.goto('http://localhost:3001/signin');
    await page.getByPlaceholder('Your email').fill('demo@example.com');
    await page.getByPlaceholder('Your password').fill('demo1234');
    await page.getByRole('button', { name: /sign in/i }).click();
    await page.waitForURL((url) => !url.pathname.startsWith('/signin'));

    await page.getByText('Settings', { exact: true }).click();
    await page.getByRole('link', { name: 'Rules', exact: true }).click();
    await expect(page).toHaveURL(/\/settings\/rules$/);
    // No tenant-owned conditioned edges exist - empty list, not NoPermission.
    await expect(
      page.getByText('You don’t have access to this page'),
    ).toHaveCount(0);
    await expect(page.getByPlaceholder('Search rules…')).toBeVisible();
  });
});
