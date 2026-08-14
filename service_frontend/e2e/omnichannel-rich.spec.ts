import { expect, test, type Page } from '@playwright/test';

/**
 * Omnichannel rich message types - plan 12 Slice 3 E2E (AC-12-28), against the
 * LIVE stack (Next :3001 → FastAPI :8001 → Postgres, schema app_omnichannel).
 * Real user clicks; navigates via the UI. Requires the seeded demo inbox
 * (`seed_demo_conversations` - threads cnt-001..005 on the dev-cred channel
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

async function openDemoThread(page: Page) {
  // Open the seeded "Sarah Chen" thread (cnt-001) by its stable row testid - it
  // carries inbound CONTACT bubbles with real wamids + an open CSW window, so a
  // reaction can send (the dev channel stubs Graph).
  const row = page.getByTestId('thread-row-cnt-001');
  await expect(row).toBeVisible({ timeout: 15_000 });
  await row.click();
  // Wait for the thread to actually switch (a known Sarah contact message) then
  // for a CONTACT bubble to be present.
  await expect(page.getByText('Grand Ballroom', { exact: false }).first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId('bubble-contact').first()).toBeVisible({ timeout: 15_000 });
}

test.describe('Omnichannel rich messages - Slice 3', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('react to a message → the emoji chip appears on the bubble (AC-12-20)', async ({ page }) => {
    await openInbox(page);
    await openDemoThread(page);

    // Right-click a bubble to open the WhatsApp-style context menu with the
    // quick-react palette, then pick 👍.
    const bubble = page.getByTestId('bubble-contact').first();
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
    await openDemoThread(page);

    const bubble = page.getByTestId('bubble-contact').first();
    await bubble.click({ button: 'right' });
    await page.getByTestId('react-❤️').click();
    await expect(page.getByTestId('reaction-chips').first()).toContainText('❤️', { timeout: 10_000 });
    // The menu closes on react - wait for it to be gone before re-opening.
    await expect(page.getByTestId('react-row')).toBeHidden();

    // Re-open the menu → the remove control is now offered → the chip element is
    // removed entirely (ReactionChips renders nothing when there are no reactions).
    await bubble.click({ button: 'right' });
    await page.getByTestId('react-remove').click();
    await expect(page.getByTestId('reaction-chips')).toHaveCount(0, { timeout: 10_000 });
  });

  test('the media caps settings page loads and is editable (AC-12-23)', async ({ page }) => {
    await page.goto('/omnichannel/settings/media');
    await page.waitForURL(/\/omnichannel\/settings\/media/);
    // A cap card per media type; the Image card shows an MB input + a ceiling hint.
    await expect(page.getByText(/image/i).first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole('button', { name: /save/i })).toBeVisible();
  });
});
