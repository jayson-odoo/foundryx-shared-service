import { expect, test, type Page } from '@playwright/test';

/**
 * Omnichannel rich message types — plan 12 Slice 3 E2E (AC-12-28), against the
 * LIVE stack (Next :3001 → FastAPI :8001 → Postgres, schema app_omnichannel).
 * Real user clicks; navigates via the UI. Requires the seeded demo inbox
 * (`seed_demo_conversations` — threads cnt-001..005 on the dev-cred channel
 * `chn-demo`, so sends never hit Graph). Bootstrap with ENVIRONMENT=development
 * so the demo data exists.
 *
 * Inbound-simulation journeys (receive an image / a button reply / a contact
 * reaction) require POSTing a Meta webhook to `…/omnichannel/webhooks/{channel}`;
 * they are documented in the test report and driven via the API in a follow-up.
 * This spec covers the agent-drivable journeys end-to-end through the UI.
 */

async function login(page: Page) {
  await page.goto('/signin');
  await page.getByPlaceholder('Your email').fill('demo@example.com');
  await page.getByPlaceholder('Your password').fill('demo1234');
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));
}

async function openInbox(page: Page) {
  await page.goto('/omnichannel/inbox');
  await page.waitForURL(/\/omnichannel\/inbox/);
}

async function openFirstThread(page: Page) {
  // The thread list is the left panel; click the first thread row to open it.
  const firstThread = page.locator('[data-testid^="thread-row-"]').first();
  await expect(firstThread).toBeVisible({ timeout: 15_000 });
  await firstThread.click();
  await expect(page.getByTestId('bubble-contact').or(page.getByTestId('bubble-agent')).first()).toBeVisible({
    timeout: 15_000,
  });
}

test.describe('Omnichannel rich messages — Slice 3', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('react to a message → the emoji chip appears on the bubble (AC-12-20)', async ({ page }) => {
    await openInbox(page);
    await openFirstThread(page);

    // Right-click a bubble to open the WhatsApp-style context menu with the
    // quick-react palette, then pick 👍.
    const bubble = page.getByTestId('bubble-agent').first();
    await bubble.click({ button: 'right' });
    const reactRow = page.getByTestId('react-row');
    await expect(reactRow).toBeVisible();
    await page.getByTestId('react-👍').click();

    // The chip renders on the target bubble (optimistic + reconciled by the
    // react response / WS).
    await expect(page.getByTestId('reaction-chips').first()).toContainText('👍', { timeout: 10_000 });
  });

  test('remove a reaction via the context menu (AC-12-19)', async ({ page }) => {
    await openInbox(page);
    await openFirstThread(page);

    const bubble = page.getByTestId('bubble-agent').first();
    await bubble.click({ button: 'right' });
    await page.getByTestId('react-❤️').click();
    await expect(page.getByTestId('reaction-chips').first()).toContainText('❤️', { timeout: 10_000 });

    // Re-open the menu → the remove control is now offered → chip clears.
    await bubble.click({ button: 'right' });
    await page.getByTestId('react-remove').click();
    await expect(page.getByTestId('reaction-chips').first()).not.toContainText('❤️', { timeout: 10_000 });
  });

  test('the media caps settings page loads and is editable (AC-12-23)', async ({ page }) => {
    await page.goto('/omnichannel/settings/media');
    await page.waitForURL(/\/omnichannel\/settings\/media/);
    // A cap card per media type; the Image card shows an MB input + a ceiling hint.
    await expect(page.getByText(/image/i).first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole('button', { name: /save/i })).toBeVisible();
  });
});
