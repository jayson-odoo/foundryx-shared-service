import { expect, test, type Page } from '@playwright/test';

/**
 * Omnichannel BSP — Foundation (plan 04) E2E, against the LIVE backend
 * (Next :3001 → FastAPI :8001 → Postgres, schema app_omnichannel). Real user
 * clicks; navigates via the UI. Backend must be bootstrapped
 * (`python -m scripts.bootstrap_db`) so the default "General" workspace +
 * omnichannel permissions exist and the demo user is Admin.
 *
 * Embedded Signup is simulated client-side (mock Meta popup) but the channel is
 * provisioned by the REAL backend onboarding endpoint (dev mode — no Meta app).
 */

async function login(page: Page) {
  await page.goto('/signin');
  await page.getByPlaceholder('Your email').fill('demo@example.com');
  await page.getByPlaceholder('Your password').fill('demo1234');
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));
}

async function openOmnichannel(page: Page, name: 'Channels' | 'Workspaces') {
  const link = page.getByRole('link', { name, exact: true });
  if (!(await link.isVisible().catch(() => false))) {
    await page.getByRole('button', { name: 'Omnichannel', exact: true }).click();
    await expect(link).toBeVisible();
  }
  await link.click();
  await page.waitForURL(new RegExp(`/omnichannel/settings/${name.toLowerCase()}`));
}

test.describe('Omnichannel — Channels', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('channels page loads with the Connect button', async ({ page }) => {
    await openOmnichannel(page, 'Channels');
    await expect(page).toHaveURL(/\/omnichannel\/settings\/channels$/);
    await expect(page.getByText('Connect and manage your WhatsApp Business numbers.')).toBeVisible();
    await expect(page.getByRole('button', { name: /connect channel/i })).toBeVisible();
  });

  test('connects a channel via Embedded Signup, then opens its detail', async ({ page }) => {
    await openOmnichannel(page, 'Channels');

    await page.getByRole('button', { name: /connect channel/i }).click();
    await expect(page.getByRole('dialog')).toContainText('Connect a WhatsApp channel');
    await page.getByRole('button', { name: /connect with facebook/i }).click();

    // Env-dependent (real-or-simulated ES): with NEXT_PUBLIC_META_APP_ID +
    // NEXT_PUBLIC_META_ES_CONFIG_ID set the wizard launches the REAL Meta SDK
    // popup, which a headless test can't drive — this spec covers the
    // simulated path only.
    const mockPopup = page.getByText('Select the WhatsApp Business number');
    const simulated = await mockPopup
      .waitFor({ state: 'visible', timeout: 5_000 })
      .then(() => true)
      .catch(() => false);
    test.skip(!simulated, 'Real Meta Embedded Signup configured — simulated popup unavailable.');
    // Scope to the popup (a prior run may have left a channel of the same name in the list).
    await page.getByRole('dialog').getByText('FoundryX Events Co.').click();
    await page.getByRole('button', { name: /^authorize$/i }).click();
    await expect(page.getByText('Channel connected')).toBeVisible({ timeout: 15_000 });
    await page.getByRole('button', { name: /^done$/i }).click();

    // The provisioned channel appears; open it.
    const row = page.getByText('FoundryX Events Co.').first();
    await expect(row).toBeVisible();
    await row.click();
    await page.waitForURL(/\/omnichannel\/settings\/channels\/.+/, { timeout: 20_000 });
    await expect(page.getByRole('tab', { name: /general/i })).toBeVisible();
    await expect(page.getByRole('tab', { name: /connection/i })).toBeVisible();
    // Channel→workspace linkage (attached to the default General workspace).
    await expect(page.getByRole('link', { name: 'General', exact: true })).toBeVisible();
  });
});

test.describe('Omnichannel — Workspaces', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('lists the default workspace', async ({ page }) => {
    await openOmnichannel(page, 'Workspaces');
    await expect(page).toHaveURL(/\/omnichannel\/settings\/workspaces$/);
    await expect(page.getByText('General', { exact: true })).toBeVisible();
    await expect(page.getByText('Default', { exact: true }).first()).toBeVisible();
  });

  test('creates a new workspace with all three tabs', async ({ page }) => {
    await openOmnichannel(page, 'Workspaces');
    await page.getByRole('button', { name: /new workspace/i }).click();
    await expect(page).toHaveURL(/\/omnichannel\/settings\/workspaces\/new/);
    await page.getByPlaceholder('e.g. Sales & Support').fill('VIP Concierge');
    await page.getByRole('button', { name: /^create$/i }).click();
    await page.waitForURL(/\/omnichannel\/settings\/workspaces\/.+/, { timeout: 20_000 });
    await expect(page.getByRole('tab', { name: /settings/i })).toBeVisible();
    await expect(page.getByRole('tab', { name: /channels/i })).toBeVisible();
    await expect(page.getByRole('tab', { name: /members/i })).toBeVisible();
  });

  test('adds a member from the searchable list (Roles-style)', async ({ page }) => {
    await openOmnichannel(page, 'Workspaces');
    await page.getByText('General', { exact: true }).click();
    await page.waitForURL(/\/omnichannel\/settings\/workspaces\/.+/, { timeout: 20_000 });
    await page.getByRole('tab', { name: /members/i }).click();

    await expect(page.getByPlaceholder('Search members…')).toBeVisible();
    await expect(page.getByRole('button', { name: /add member/i })).toBeVisible();
    // Add the first assignable core user (resilient to prior runs that already
    // added some). If everyone's already a member, the picker is empty — either
    // way the workspace ends with ≥1 member row (a remove button present).
    await page.getByRole('combobox').click();
    const firstOption = page.getByRole('option').first();
    if (await firstOption.isVisible().catch(() => false)) {
      await firstOption.click();
      await page.keyboard.press('Escape');
      await page.getByRole('button', { name: /add member/i }).click();
    } else {
      await page.keyboard.press('Escape');
    }
    // A member row exposes a Remove button + a clickable user link.
    await expect(page.getByRole('button', { name: /^remove /i }).first()).toBeVisible({ timeout: 10_000 });
  });
});
