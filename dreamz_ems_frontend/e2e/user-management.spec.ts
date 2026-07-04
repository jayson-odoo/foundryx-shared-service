import { expect, test, type Page } from '@playwright/test';

/**
 * User Management E2E — real user clicks against the live stack
 * (Next :3001 → FastAPI :8001 → Postgres). Navigates by clicking the UI;
 * never URL-jumps into protected pages (per governance). Requires the backend
 * up + seeded (`python -m scripts.bootstrap_db`).
 */

async function login(page: Page) {
  await page.goto('/signin');
  await page.getByPlaceholder('Your email').fill('demo@example.com');
  await page.getByPlaceholder('Your password').fill('demo1234');
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));
}

async function gotoUsers(page: Page) {
  // "User Management" is a collapsible parent; expand it (if needed) then click
  // the "Users" submenu link — all real clicks, no URL jumping.
  const usersLink = page.getByRole('link', { name: 'Users', exact: true });
  if (!(await usersLink.isVisible().catch(() => false))) {
    await page.getByText('User Management', { exact: true }).click();
  }
  await usersLink.click();
  await expect(page).toHaveURL(/\/user-management\/users$/);
  await expect(page.getByText('demo@example.com')).toBeVisible();
}

test.describe('User Management', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('navigates to the users list via the sidebar', async ({ page }) => {
    await gotoUsers(page);
    await expect(page.getByText('Manage users, their roles and access.')).toBeVisible();
    // Seeded demo user is present.
    await expect(page.getByText('demo@example.com')).toBeVisible();
  });

  test('searches users by name', async ({ page }) => {
    await gotoUsers(page);
    await page.getByPlaceholder('Search users…').fill('manager');
    await expect(page.getByText('manager@dreamz.com')).toBeVisible();
    await expect(page.getByText('demo@example.com')).toHaveCount(0);
  });

  test('opens a user form via row click and shows record navigation', async ({ page }) => {
    await gotoUsers(page);
    await page.getByText('Demo User').click();
    await expect(page).toHaveURL(/\/user-management\/users\/.+/);
    // Identifier header + tabs.
    await expect(page.getByRole('heading', { name: 'Demo User' })).toBeVisible();
    await expect(page.getByRole('tab', { name: /profile/i })).toBeVisible();
    // Record-nav pager carried from the list (e.g. "1 / 5").
    await expect(page.getByText(/\d+ \/ \d+/)).toBeVisible();
  });

  test('edits a user and saves', async ({ page }) => {
    await gotoUsers(page);
    await page.getByText('Event Staff').click();
    await page.getByRole('button', { name: /^Edit$/ }).click();

    const nameInput = page.getByRole('textbox').first();
    await nameInput.fill('Event Staff QA');
    await page.getByRole('button', { name: /^Save$/ }).click();

    await expect(page.getByRole('heading', { name: 'Event Staff QA' })).toBeVisible();

    // Revert to keep the dataset clean.
    await page.getByRole('button', { name: /^Edit$/ }).click();
    await page.getByRole('textbox').first().fill('Event Staff');
    await page.getByRole('button', { name: /^Save$/ }).click();
    await expect(page.getByRole('heading', { name: 'Event Staff' })).toBeVisible();
  });

  test('switches to the Trashed view', async ({ page }) => {
    await gotoUsers(page);
    await page.getByText('Trashed', { exact: true }).click();
    // The list reloads in trashed scope (no crash; toolbar still present).
    await expect(page.getByPlaceholder('Search users…')).toBeVisible();
  });
});
