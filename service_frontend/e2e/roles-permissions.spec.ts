import { expect, test, type Page } from '@playwright/test';

/**
 * Roles & Permissions + Impersonation E2E - real user clicks against the live
 * stack (Next :3001 → FastAPI :8001 → Postgres). Navigates by clicking the UI;
 * never URL-jumps into protected pages (per governance). Requires the backend up
 * + seeded (`python -m scripts.bootstrap_db`) - demo@example.com is Admin (all
 * permissions); KT Demo (demo@kt.com) is a Member with no permissions.
 */

async function login(page: Page) {
  await page.goto('/signin');
  await page.getByPlaceholder('Your email').fill('demo@example.com');
  await page.getByPlaceholder('Your password').fill('demo1234');
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));
}

async function gotoSubmenu(page: Page, name: 'Users' | 'Roles') {
  const link = page.getByRole('link', { name, exact: true });
  if (!(await link.isVisible().catch(() => false))) {
    await page.getByText('User Management', { exact: true }).click();
  }
  await link.click();
}

async function gotoRoles(page: Page) {
  await gotoSubmenu(page, 'Roles');
  await expect(page).toHaveURL(/\/user-management\/roles$/);
  await expect(page.getByText('Manage roles and the permissions they grant across the system.')).toBeVisible();
}

test.describe('Roles & Permissions', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('navigates to the roles list with counts', async ({ page }) => {
    await gotoRoles(page);
    // Unique seeded-role descriptions (unambiguous across the page).
    await expect(page.getByText('Full system access with all permissions')).toBeVisible();
    await expect(page.getByText('Read-only access to dashboards and reports')).toBeVisible();
  });

  test('searches roles by assigned user and by permission key', async ({ page }) => {
    await gotoRoles(page);
    const search = page.getByPlaceholder('Search roles…');

    // Admin has the demo user assigned → matches a user search.
    await search.fill('Demo');
    await expect(page.getByText('Full system access with all permissions')).toBeVisible();

    // Only Admin holds orders.approve → permission search isolates it.
    await search.fill('orders.approve');
    await expect(page.getByText('Full system access with all permissions')).toBeVisible();
    await expect(page.getByText('Read-only access to dashboards and reports')).toHaveCount(0);
  });

  test('opens a role form with the three tabs + record nav', async ({ page }) => {
    await gotoRoles(page);
    await page.getByText('Read-only access to dashboards and reports').click();
    await expect(page).toHaveURL(/\/user-management\/roles\/.+/);
    await expect(page.getByRole('tab', { name: /permissions/i })).toBeVisible();
    await expect(page.getByRole('tab', { name: /assigned users/i })).toBeVisible();
    await expect(page.getByRole('tab', { name: /settings/i })).toBeVisible();
    await expect(page.getByText(/\d+ \/ \d+/)).toBeVisible();
  });

  test('shows the permission catalog grouped under the Permissions tab', async ({ page }) => {
    await gotoRoles(page);
    await page.getByText('Full system access with all permissions').click();
    // Resource rows from the synced catalog, incl. custom-action resources.
    await expect(page.getByText('Orders & Delivery').first()).toBeVisible();
    await expect(page.getByText('Reports & Analytics').first()).toBeVisible();
  });

  test('creates a role then deletes it', async ({ page }) => {
    await gotoRoles(page);
    await page.getByRole('button', { name: /add role/i }).click();
    await expect(page).toHaveURL(/\/user-management\/roles\/new$/);

    // Create opens on Settings (name first).
    await page.getByPlaceholder('e.g. Event Manager').fill('E2E Temp Role');
    await page.getByRole('button', { name: /^Create$|^Save$/ }).click();

    await expect(page.getByRole('heading', { name: 'E2E Temp Role' })).toBeVisible();

    // Delete via the form "…" action menu (custom role → deletable).
    await page.getByRole('button', { name: 'Actions' }).click();
    await page.getByRole('menuitem', { name: /delete role/i }).click();
    await page.getByRole('button', { name: /delete role/i }).click();

    await expect(page).toHaveURL(/\/user-management\/roles$/);
    await page.getByPlaceholder('Search roles…').fill('E2E Temp Role');
    await expect(page.getByText('E2E Temp Role')).toHaveCount(0);
  });
});

test.describe('Impersonation', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('impersonate a no-permission user → no-access page → exit restores access', async ({
    page,
  }) => {
    // Go to Users, open KT Demo's row actions, Impersonate.
    await gotoSubmenu(page, 'Users');
    await expect(page).toHaveURL(/\/user-management\/users$/);
    await page.getByPlaceholder('Search users…').fill('kt');
    // Wait for the filtered list to settle (other rows gone) so the row + its
    // action menu don't detach mid-click as the table re-renders.
    await expect(page.getByText('demo@kt.com')).toBeVisible();
    await expect(page.getByText('demo@example.com')).toHaveCount(0);

    const row = page.getByRole('row', { name: /KT Demo/ });
    await row.getByRole('button', { name: 'Actions' }).click();
    await page.getByRole('menuitem', { name: 'Impersonate' }).click();
    await page.getByRole('button', { name: 'Impersonate' }).click(); // confirm

    // Banner appears; the current (Users) page now shows the friendly gate.
    await expect(page.getByText(/You are impersonating/)).toBeVisible();
    await expect(
      page.getByRole('heading', { name: /don.t have access to this page/i }),
    ).toBeVisible();

    // Exit → access restored.
    await page.getByRole('button', { name: /exit impersonation/i }).click();
    await expect(page.getByText(/You are impersonating/)).toHaveCount(0);
    await expect(page.getByPlaceholder('Search users…')).toBeVisible();
  });
});
