import { expect, test, type Page } from '@playwright/test';

/**
 * Sprint-3/03 (F2) slice 1 - document / PDF render, live stack.
 *
 * Preconditions (stack already up; this spec starts NOTHING):
 *   - backend :8001 on the f2-render branch, migrated + seeded - a platform-tier
 *     DOCUMENT template named "Invoice" (key `document.invoice`, context
 *     `document.invoice_preview`) is present.
 *   - frontend prod build served on :3001 (same worktree).
 *
 * Demo login `demo@example.com` / `demo1234` on the bare host = the `default`
 * tenant. This spec only VIEWS the seeded Invoice - no provisioning / no shared
 * state mutated, so it is parallel-safe.
 *
 * Journeys:
 *   1. Design → Preview → the in-app HTML sheet renders (the sandboxed iframe
 *      receives the compiled document HTML and shows real invoice content).
 *   2. Download PDF → a `.pdf` download starts.
 *   3. Responsive - the preview pane renders without horizontal overflow at
 *      375px AND 1280px (CLAUDE.md both-sizes mandate).
 *
 * NOTE: the preview iframe is rendered via `srcDoc` inside a `sandbox=""` frame
 * (our own renderer, not the browser PDF viewer; the same fully-sandboxed
 * pattern as the email preview pane) - so we assert on the populated `srcdoc`
 * HTML sheet + its rendered content, not a `blob:` `src`.
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

/**
 * Navigate to the Templates list by REAL clicks (a real user doesn't type the
 * URL). Two real surfaces, viewport-driven:
 *   - desktop (≥lg): the header "Settings" mega-menu trigger opens the section,
 *     then the gated "Templates" link.
 *   - mobile: the header collapses to a hamburger sheet; open it, expand the
 *     "Settings" accordion, then click "Templates".
 */
async function gotoTemplatesByClick(page: Page) {
  // The header mega-menu is desktop-only (Tailwind `lg` = 1024px); below it the
  // header collapses to a hamburger sheet. Branch on the actual viewport width.
  const width = page.viewportSize()?.width ?? 1280;
  if (width < 1024) {
    // Mobile: open the hamburger sheet, expand the "Settings" accordion.
    await page.locator('[data-slot="sheet-trigger"]').first().click();
    await page.getByText('Settings', { exact: true }).first().click();
  } else {
    // Desktop: the header "Settings" mega-menu trigger reveals the section.
    await page.getByRole('button', { name: /settings/i }).first().click();
  }
  const link = page.getByRole('link', { name: 'Templates', exact: true }).first();
  await expect(link).toBeVisible({ timeout: 10_000 });
  await link.click();
  await expect(page.locator('h1', { hasText: 'Templates' })).toBeVisible({ timeout: 20_000 });
}

/** Open the seeded Invoice document template by clicking its list row. */
async function openInvoice(page: Page) {
  await page.getByText('Invoice', { exact: true }).first().click();
  await expect(page).toHaveURL(/\/settings\/templates\/[0-9a-f-]+(\?|$)/, { timeout: 20_000 });
  // The form opens on the Design tab (initialTabId) for a document template.
  await expect(page.getByRole('heading', { name: 'Invoice', level: 1 })).toBeVisible();
}

/**
 * From an opened Invoice detail: ensure the Design tab is active, flip to the
 * Preview toggle, and wait for the in-app HTML sheet (blob: iframe) to render.
 */
async function openPreview(page: Page) {
  await page.getByRole('tab', { name: 'Design' }).click();
  await expect(page.getByTestId('email-editor')).toBeVisible();
  await page.getByTestId('editor-mode-preview').click();

  const pane = page.getByTestId('pdf-preview-pane');
  await expect(pane).toBeVisible();
  const frame = page.getByTestId('pdf-preview-frame');
  // The pane fills the sandboxed iframe's `srcdoc` with the compiled document
  // HTML once renderHtml() resolves (POST /templates/preview?format=docHtml).
  await expect
    .poll(async () => ((await frame.getAttribute('srcdoc')) ?? '').length, { timeout: 20_000 })
    .toBeGreaterThan(50);
  return { pane, frame };
}

test.describe.configure({ timeout: 120_000 });

test.describe('F2 slice 1 - document / PDF render (live stack)', () => {
  test('Design → Preview renders the in-app HTML sheet', async ({ page }) => {
    await login(page);
    await gotoTemplatesByClick(page);
    await openInvoice(page);

    const { pane, frame } = await openPreview(page);
    await expect(pane).toBeVisible();
    expect(((await frame.getAttribute('srcdoc')) ?? '').length).toBeGreaterThan(50);

    // The compiled sheet shows real document content inside the sandboxed frame.
    await expect(
      page.frameLocator('[data-testid="pdf-preview-frame"]').locator('body'),
    ).toContainText('Invoice', { timeout: 10_000 });

    // The Refresh + Download controls live in the pane.
    await expect(page.getByRole('button', { name: /refresh preview/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /download pdf/i })).toBeVisible();
  });

  test('Download PDF starts a .pdf download', async ({ page }) => {
    await login(page);
    await gotoTemplatesByClick(page);
    await openInvoice(page);
    await openPreview(page);

    const downloadPromise = page.waitForEvent('download', { timeout: 30_000 });
    await page.getByRole('button', { name: /download pdf/i }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/\.pdf$/);
  });

  test('Preview pane renders without horizontal overflow at mobile AND desktop', async ({
    page,
  }) => {
    await login(page);

    for (const viewport of [
      { width: 375, height: 800, label: 'mobile' },
      { width: 1280, height: 800, label: 'desktop' },
    ]) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await gotoTemplatesByClick(page);
      await openInvoice(page);
      const { pane } = await openPreview(page);

      await expect(pane, `pane visible @ ${viewport.label}`).toBeVisible();

      // No horizontal overflow: the document scrollWidth must not exceed the
      // viewport width (a clipped/overflowing control would push it wider).
      const docOverflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(docOverflow, `no horizontal overflow @ ${viewport.label}`).toBeLessThanOrEqual(1);

      // And the pane itself fits inside the viewport horizontally.
      const box = await pane.boundingBox();
      expect(box, `pane box @ ${viewport.label}`).not.toBeNull();
      if (box) {
        expect(box.width, `pane within viewport @ ${viewport.label}`).toBeLessThanOrEqual(
          viewport.width + 1,
        );
      }
    }
  });
});
