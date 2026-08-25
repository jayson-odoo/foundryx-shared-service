import { expect, test, type Page } from '@playwright/test';

/**
 * Sprint-3/03 (F2) slice 2 - fixed-canvas (badge/ticket/cert) designer, live
 * stack.
 *
 * Preconditions (stack already up; this spec starts NOTHING):
 *   - backend :8001 on the sprint-3/03b branch, migrated + seeded - a
 *     platform-tier BADGE template named "Attendee badge" (key `badge.attendee`,
 *     context `badge.preview`, type `badge`) is present.
 *   - frontend prod build served on :3001 (same checkout).
 *
 * Demo login `demo@example.com` / `demo1234` on the bare host = the `default`
 * tenant. This spec VIEWS + edits a DRAFT of the seeded badge (no save, no
 * shared-state mutation) so it stays parallel-safe.
 *
 * Journeys:
 *   1. Open the badge → the Konva CanvasEditor mounts (palette + canvas stage).
 *   2. Edit → palette click-to-add a Text element → the inspector opens for it.
 *   3. Preview → the in-app sheet renders the server canvas HTML (the QR is a
 *      real server-generated <svg>; the {{attendeeName}} sample resolves).
 *   4. Download PDF → a `.pdf` download starts.
 *   5. Responsive - editor + preview render without horizontal overflow at
 *      375px AND 1280px (CLAUDE.md both-sizes mandate).
 */

const DEMO_EMAIL = 'demo@example.com';
const DEMO_PASSWORD = 'demo1234';

async function login(page: Page) {
  await page.goto('/signin');
  await page.getByPlaceholder('Your email').fill(DEMO_EMAIL);
  await page.getByPlaceholder('Your password').fill(DEMO_PASSWORD);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'), { timeout: 30_000 });
}

async function gotoTemplatesByClick(page: Page) {
  const width = page.viewportSize()?.width ?? 1280;
  if (width < 1024) {
    await page.locator('[data-slot="sheet-trigger"]').first().click();
    await page.getByText('Settings', { exact: true }).first().click();
  } else {
    await page.getByRole('button', { name: /settings/i }).first().click();
  }
  const link = page.getByRole('link', { name: 'Templates', exact: true }).first();
  await expect(link).toBeVisible({ timeout: 10_000 });
  await link.click();
  await expect(page.locator('h1', { hasText: 'Templates' })).toBeVisible({ timeout: 20_000 });
}

/** Open the seeded "Attendee badge" template by clicking its list row. */
async function openBadge(page: Page) {
  await page.getByText('Attendee badge', { exact: true }).first().click();
  await expect(page).toHaveURL(/\/settings\/templates\/[0-9a-f-]+(\?|$)/, { timeout: 20_000 });
  await expect(page.getByRole('heading', { name: 'Attendee badge', level: 1 })).toBeVisible();
  await page.getByRole('tab', { name: 'Design' }).click();
  await expect(page.getByTestId('canvas-editor')).toBeVisible();
}

/** Flip to the Preview toggle and wait for the in-app canvas sheet to render. */
async function openPreview(page: Page) {
  await page.getByTestId('canvas-mode-preview').click();
  const pane = page.getByTestId('pdf-preview-pane');
  await expect(pane).toBeVisible();
  const frame = page.getByTestId('pdf-preview-frame');
  await expect
    .poll(async () => ((await frame.getAttribute('srcdoc')) ?? '').length, { timeout: 20_000 })
    .toBeGreaterThan(50);
  return { pane, frame };
}

test.describe.configure({ timeout: 120_000 });

test.describe('F2 slice 2 - fixed-canvas badge designer (live stack)', () => {
  test('Open badge → Konva editor mounts (palette + canvas)', async ({ page }) => {
    await login(page);
    await gotoTemplatesByClick(page);
    await openBadge(page);

    await expect(page.getByTestId('canvas-palette')).toBeVisible();
    // The Konva stage renders in a real browser (canvas).
    await expect(page.getByTestId('canvas-stage')).toBeVisible({ timeout: 15_000 });
  });

  test('Edit → palette click-to-add opens the inspector for the new element', async ({ page }) => {
    await login(page);
    await gotoTemplatesByClick(page);
    await openBadge(page);

    await page.getByRole('button', { name: /^edit$/i }).click();
    // Add a Text element - it auto-selects, so the inspector appears.
    await page.getByTestId('palette-add-text').click();
    await expect(page.getByTestId('canvas-inspector')).toBeVisible();
    await expect(page.getByLabel('Text content')).toBeVisible();
  });

  test('Preview renders the server canvas sheet (real QR svg + sample fact)', async ({ page }) => {
    await login(page);
    await gotoTemplatesByClick(page);
    await openBadge(page);

    const { frame } = await openPreview(page);
    const srcdoc = (await frame.getAttribute('srcdoc')) ?? '';
    // QR is server-generated as an inline <svg>; the attendeeName sample resolves.
    expect(srcdoc).toContain('<svg');
    expect(srcdoc).toContain('Alex Tan');

    await expect(
      page.frameLocator('[data-testid="pdf-preview-frame"]').locator('.badge-side'),
    ).toBeVisible({ timeout: 10_000 });
  });

  test('Download PDF starts a .pdf download', async ({ page }) => {
    await login(page);
    await gotoTemplatesByClick(page);
    await openBadge(page);
    await openPreview(page);

    const downloadPromise = page.waitForEvent('download', { timeout: 30_000 });
    await page.getByRole('button', { name: /download pdf/i }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/\.pdf$/);
  });

  test('Editor + preview render without horizontal overflow at mobile AND desktop', async ({
    page,
  }) => {
    await login(page);

    for (const viewport of [
      { width: 375, height: 800, label: 'mobile' },
      { width: 1280, height: 800, label: 'desktop' },
    ]) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await gotoTemplatesByClick(page);
      await openBadge(page);

      await expect(page.getByTestId('canvas-stage'), `stage @ ${viewport.label}`).toBeVisible({
        timeout: 15_000,
      });

      const designOverflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(designOverflow, `no overflow (design) @ ${viewport.label}`).toBeLessThanOrEqual(1);

      const { pane } = await openPreview(page);
      await expect(pane, `pane @ ${viewport.label}`).toBeVisible();
      const previewOverflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(previewOverflow, `no overflow (preview) @ ${viewport.label}`).toBeLessThanOrEqual(1);
    }
  });
});
