import { expect, test, type Page } from '@playwright/test';

/**
 * Omnichannel — Embed access CONFIG SCREEN E2E (sprint-4/11H, AC-11H-18).
 *
 * The operator-facing setup surface at Omnichannel ▸ Settings ▸ Embed access
 * (/omnichannel/settings/embed, gated workspaces.manage). Real user clicks —
 * navigates via the sidebar menu, never a URL shortcut.
 *
 * Live test data (already provisioned, DO NOT MUTATE): connection
 * `conn-embed-live` (provider omnichannel_shared), embedSecret already Set,
 * allowedOrigins include http://localhost:3009 (a live test parent depends on
 * it) and https://crm.acme.com. This spec adds/removes only a timestamped
 * throwaway origin and NEVER rotates the secret or touches :3009.
 */

const CONNECTION_ID = 'conn-embed-live';
const KEEP_ORIGIN = 'http://localhost:3009';
const CRM_ORIGIN = 'https://crm.acme.com';

async function login(page: Page) {
  await page.goto('/signin');
  await page.getByPlaceholder('Your email').fill('demo@example.com');
  await page.getByPlaceholder('Your password').fill('demo1234');
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));
}

async function gotoEmbedAccess(page: Page) {
  const link = page.getByRole('link', { name: 'Embed access', exact: true });
  if (!(await link.isVisible().catch(() => false))) {
    await page.getByRole('button', { name: 'Omnichannel', exact: true }).click();
    await expect(link).toBeVisible();
  }
  await link.click();
  await page.waitForURL(/\/omnichannel\/settings\/embed/);
  // Wait for the loaded panel (connection id card).
  await expect(page.getByRole('textbox', { name: 'connection id' })).toBeVisible();
}

function snippetPre(page: Page) {
  return page.locator('pre').first();
}

test.describe('Embed access — config screen (AC-11H-18)', () => {
  test('renders the config surfaces, frontend-origin snippet, route/workspace switch, rotate control (1280px)', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await login(page);
    await gotoEmbedAccess(page);

    // ── Connection id + copy control ──────────────────────────────────────
    const connInput = page.getByRole('textbox', { name: 'connection id' });
    await expect(connInput).toHaveValue(CONNECTION_ID);
    await expect(page.getByRole('button', { name: 'Copy connection id' })).toBeVisible();

    // ── Embed secret: "Set" + Rotate control (present + labelled, NOT clicked)
    await expect(page.getByText('Embed secret', { exact: true })).toBeVisible();
    await expect(page.getByText('Set', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Rotate secret' })).toBeVisible();

    // ── Allowed-origins editor lists the current origins ──────────────────
    await expect(page.getByText('Allowed origins', { exact: true })).toBeVisible();
    await expect(page.getByText(KEEP_ORIGIN, { exact: true })).toBeVisible();
    await expect(page.getByText(CRM_ORIGIN, { exact: true })).toBeVisible();

    // ── Iframe-snippet card ───────────────────────────────────────────────
    await expect(page.getByText('Iframe snippet', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Copy iframe snippet' })).toBeVisible();

    // ── Snippet uses the FRONTEND origin, not the backend :8001 ───────────
    const threadSrc = `http://localhost:3001/embed/omnichannel/thread?c=${CONNECTION_ID}`;
    await expect(snippetPre(page)).toContainText(threadSrc);
    await expect(snippetPre(page)).not.toContainText(':8001');

    // ── Switch route thread ⇄ inbox → src updates ─────────────────────────
    await page.getByRole('combobox', { name: 'Snippet view' }).click();
    await page.getByRole('option', { name: 'Full inbox' }).click();
    await expect(snippetPre(page)).toContainText(
      `http://localhost:3001/embed/omnichannel/inbox?c=${CONNECTION_ID}`,
    );
    await page.getByRole('combobox', { name: 'Snippet view' }).click();
    await page.getByRole('option', { name: 'Single thread' }).click();
    await expect(snippetPre(page)).toContainText(threadSrc);

    // ── Switch workspace → the assertion-workspace comment updates ─────────
    const wsCombo = page.getByRole('combobox', { name: 'Snippet workspace' });
    await wsCombo.click();
    const options = page.getByRole('option');
    const count = await options.count();
    if (count > 1) {
      const before = await snippetPre(page).textContent();
      // pick a different workspace than the currently-selected first one
      await options.nth(1).click();
      await expect(async () => {
        expect(await snippetPre(page).textContent()).not.toBe(before);
      }).toPass();
    } else {
      // Single workspace on this tenant — close the popover; the workspaceId
      // still rides the snippet comment (asserted below).
      await page.keyboard.press('Escape');
    }
    await expect(snippetPre(page)).toContainText('workspaceId for your assertion:');
  });

  test('renders + frontend-origin snippet at 375px (responsive)', async ({ page }) => {
    // Navigate via real clicks at desktop width (the sidebar lives behind a
    // mobile toggle at 375px), THEN shrink to verify the surface reflows.
    await page.setViewportSize({ width: 1280, height: 900 });
    await login(page);
    await gotoEmbedAccess(page);
    await page.setViewportSize({ width: 375, height: 812 });

    // Core surfaces still present + usable on a narrow viewport.
    await expect(page.getByRole('textbox', { name: 'connection id' })).toHaveValue(
      CONNECTION_ID,
    );
    await expect(page.getByRole('button', { name: 'Rotate secret' })).toBeVisible();
    await expect(page.getByText(KEEP_ORIGIN, { exact: true })).toBeVisible();
    await expect(page.getByText('Iframe snippet', { exact: true })).toBeVisible();
    await expect(snippetPre(page)).toContainText(
      `http://localhost:3001/embed/omnichannel/thread?c=${CONNECTION_ID}`,
    );

    // No horizontal page scroll at 375px (steady-state; allow the resize reflow
    // to settle rather than sampling a single transient frame).
    await expect(async () => {
      const overflow = await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(1);
    }).toPass({ timeout: 5000 });
  });

  test('adds then removes an allowed origin, persisting across reload (does not touch :3009)', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await login(page);
    await gotoEmbedAccess(page);

    const newOrigin = `https://qa-${Date.now()}.example.com`;

    // ── Add ───────────────────────────────────────────────────────────────
    await page.getByRole('textbox', { name: 'New allowed origin' }).fill(newOrigin);
    await page.getByRole('button', { name: 'Add', exact: true }).click();
    await expect(page.getByText(newOrigin, { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Save origins' }).click();
    await expect(page.getByText('Allowed origins saved.')).toBeVisible();

    // Persisted across a reload (refetched from the backend).
    await page.reload();
    await expect(page.getByText(newOrigin, { exact: true })).toBeVisible();
    await expect(page.getByText(KEEP_ORIGIN, { exact: true })).toBeVisible(); // untouched

    // ── Remove ────────────────────────────────────────────────────────────
    await page.getByRole('button', { name: `Remove ${newOrigin}` }).click();
    await expect(page.getByText(newOrigin, { exact: true })).toHaveCount(0);
    await page.getByRole('button', { name: 'Save origins' }).click();
    await expect(page.getByText('Allowed origins saved.')).toBeVisible();

    await page.reload();
    await expect(page.getByText(newOrigin, { exact: true })).toHaveCount(0);
    // The live test parent's origin survived the whole round-trip.
    await expect(page.getByText(KEEP_ORIGIN, { exact: true })).toBeVisible();
  });
});
