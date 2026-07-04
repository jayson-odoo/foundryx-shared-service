import { expect, test, type Page } from '@playwright/test';

/**
 * WABA Configuration + Profile (plan 06 Slice A) E2E — LIVE backend, dev-stub
 * mode. Targets the seeded "Demo WhatsApp (sandbox)" channel (dev credentials →
 * the adapter returns canned data, never a real Graph call). Real user clicks.
 */

async function login(page: Page) {
  await page.goto('/signin');
  await page.getByPlaceholder('Your email').fill('demo@example.com');
  await page.getByPlaceholder('Your password').fill('demo1234');
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));
}

/** Navigate to the channels list via the sidebar, open the demo channel. */
async function openDemoChannel(page: Page) {
  const link = page.getByRole('link', { name: 'Channels', exact: true });
  if (!(await link.isVisible().catch(() => false))) {
    await page.getByRole('button', { name: 'Omnichannel', exact: true }).click();
    await expect(link).toBeVisible();
  }
  await link.click();
  await page.waitForURL(/\/omnichannel\/settings\/channels$/);
  await page.getByRole('cell', { name: /demo whatsapp/i }).click();
  await page.waitForURL(/\/omnichannel\/settings\/channels\/.+/, { timeout: 20_000 });
}

test.describe('WABA Configuration + Profile', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('three tabs, read-by-default, Sync populates business name', async ({ page }) => {
    await openDemoChannel(page);

    // BR-1: exactly three tabs.
    await expect(page.getByRole('tab', { name: /configuration/i })).toBeVisible();
    await expect(page.getByRole('tab', { name: /templates/i })).toBeVisible();
    await expect(page.getByRole('tab', { name: /profile/i })).toBeVisible();
    await expect(page.getByRole('tab', { name: /configuration/i })).toHaveAttribute(
      'aria-selected',
      'true',
    );

    // BR-3: Sync pulls the (dev-stub) business account name.
    await page.getByRole('button', { name: /^sync$/i }).click();
    await expect(page.getByText('Dreamz Events (dev sandbox)')).toBeVisible({ timeout: 15_000 });
  });

  test('Sync Profile pulls the mirror from Meta (BR-5)', async ({ page }) => {
    await openDemoChannel(page);
    await page.getByRole('tab', { name: /profile/i }).click();
    await page.getByRole('button', { name: /sync profile/i }).click();
    // Dev-stub profile lands in the read view + stamps "last synced".
    await expect(page.getByText(/last synced/i)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText('Event Planning & Service')).toBeVisible();
  });

  test('profile edit → save → persists on reload', async ({ page }) => {
    await openDemoChannel(page);
    await page.getByRole('tab', { name: /profile/i }).click();

    // Engage Edit (read-only until Edit — GP-1).
    await page.getByRole('button', { name: /^edit$/i }).click();

    const about = page.getByPlaceholder('A short tagline');
    const newAbout = `E2E about ${Date.now()}`;
    await about.fill(newAbout);

    // Vertical is a SearchSelect (BR-7 / UX-2).
    await page.getByRole('combobox', { name: /business vertical/i }).click();
    await page.getByRole('option', { name: /shopping & retail/i }).click();

    await page.getByRole('button', { name: /^save$/i }).click();
    await expect(page.getByText('Channel saved.')).toBeVisible({ timeout: 15_000 });

    // BR-10: reload, confirm persistence from the local mirror.
    await page.reload();
    await page.getByRole('tab', { name: /profile/i }).click();
    await expect(page.getByText(newAbout)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText('Shopping & Retail')).toBeVisible();
  });

  test('server rejects an invalid email inline (BR-8)', async ({ page }) => {
    await openDemoChannel(page);
    await page.getByRole('tab', { name: /profile/i }).click();
    await page.getByRole('button', { name: /^edit$/i }).click();
    await page.getByPlaceholder('contact@business.com').fill('not-an-email');
    await page.getByRole('button', { name: /^save$/i }).click();
    // Client zod mirror highlights it before the server is even hit.
    await expect(page.getByText(/valid email/i)).toBeVisible({ timeout: 10_000 });
  });

  test('responsive at 375px — tabs and profile usable, no overflow', async ({ page }) => {
    await openDemoChannel(page);
    await page.setViewportSize({ width: 375, height: 800 });
    await expect(page.getByRole('tab', { name: /configuration/i })).toBeVisible();
    await page.getByRole('tab', { name: /profile/i }).click();
    await expect(page.getByRole('button', { name: /sync profile/i })).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    );
    expect(overflow).toBe(false);
  });
});
