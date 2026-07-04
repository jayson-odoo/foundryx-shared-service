import { expect, test, type Page } from '@playwright/test';

/**
 * WhatsApp Templates (plan 07 Slice B1) E2E — LIVE backend, dev-stub mode.
 * Real clicks: open the seeded demo channel → Templates tab → build a draft →
 * Save → Submit → Sync(→Approved) → Delete. Desktop + 375px.
 */

async function login(page: Page) {
  await page.goto('/signin');
  await page.getByPlaceholder('Your email').fill('demo@example.com');
  await page.getByPlaceholder('Your password').fill('demo1234');
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));
}

async function openDemoTemplatesTab(page: Page) {
  const link = page.getByRole('link', { name: 'Channels', exact: true });
  if (!(await link.isVisible().catch(() => false))) {
    await page.getByRole('button', { name: 'Omnichannel', exact: true }).click();
    await expect(link).toBeVisible();
  }
  await link.click();
  await page.waitForURL(/\/omnichannel\/settings\/channels$/);
  // The seeded "Demo WhatsApp (sandbox)" channel carries dev credentials, so the
  // adapter dev-stubs the Meta calls even when META_APP_ID is configured.
  await page.getByRole('cell', { name: /demo whatsapp/i }).click();
  await page.waitForURL(/\/omnichannel\/settings\/channels\/.+/, { timeout: 20_000 });
  await page.getByRole('tab', { name: /templates/i }).click();
}

test.describe('WhatsApp Templates', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('build → save draft → submit → sync → delete', async ({ page }) => {
    await openDemoTemplatesTab(page);

    // BR-1: list shows seeded templates with a Status column.
    await expect(page.getByRole('button', { name: /submit template/i })).toBeVisible({ timeout: 15_000 });

    // Build a new draft.
    const name = `loop_tpl_${Date.now()}`;
    await page.getByRole('button', { name: /submit template/i }).click();
    await page.waitForURL(/\/templates\/new$/, { timeout: 45_000 });

    // Two-pane: editor + live preview.
    await page.getByPlaceholder('order_update').fill(name);
    await page.getByPlaceholder(/your order/i).fill('Hello {{1}}, welcome aboard.');
    // Body variable sample (appears once {{1}} is present).
    await page.getByPlaceholder('Sample for {{1}}').fill('Sam');
    // Preview reflects the substituted value live (UX-6).
    await expect(page.getByText('Hello Sam, welcome aboard.')).toBeVisible();

    // Save draft → routes to the edit URL.
    await page.getByRole('button', { name: /save draft/i }).click();
    await expect(page.getByText('Draft saved.')).toBeVisible({ timeout: 15_000 });
    await page.waitForURL(/\/templates\/[^/]+$/, { timeout: 15_000 });

    // Back to the channel → Templates tab → the draft shows as Local draft.
    await page.getByRole('button', { name: /back to channel/i }).click();
    await page.getByRole('tab', { name: /templates/i }).click();
    await expect(page.getByText(name)).toBeVisible({ timeout: 15_000 });
    const row = page.getByRole('row', { name: new RegExp(name) });
    await expect(row.getByText('Draft', { exact: true })).toBeVisible();

    // Submit from the row action → Pending.
    await row.getByRole('button', { name: /actions/i }).click();
    await page.getByRole('menuitem', { name: /submit for review/i }).click();
    await expect(page.getByText(/submitted .*for review/i)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole('row', { name: new RegExp(name) }).getByText('Pending')).toBeVisible({
      timeout: 15_000,
    });

    // Sync (dev) promotes PENDING → Approved.
    await page.getByRole('button', { name: /^sync$/i }).click();
    await expect(page.getByText('Templates synced from Meta.')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole('row', { name: new RegExp(name) }).getByText('Approved')).toBeVisible({
      timeout: 15_000,
    });

    // Delete → gone.
    const row2 = page.getByRole('row', { name: new RegExp(name) });
    await row2.getByRole('button', { name: /actions/i }).click();
    await page.getByRole('menuitem', { name: /delete/i }).click();
    await page.getByRole('button', { name: /^delete$/i }).click();
    await expect(page.getByText(/deleted .*template/i)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(name)).toHaveCount(0);
  });

  test('builder validates a sample mismatch before submit (BR-11/GP-1)', async ({ page }) => {
    await openDemoTemplatesTab(page);
    await page.getByRole('button', { name: /submit template/i }).click();
    await page.waitForURL(/\/templates\/new$/, { timeout: 45_000 });
    await page.getByPlaceholder('order_update').fill(`loop_bad_${Date.now()}`);
    await page.getByPlaceholder(/your order/i).fill('Need two {{1}} and {{2}} here');
    await page.getByPlaceholder('Sample for {{1}}').fill('only one');
    // Leave {{2}} sample blank → save blocked with an inline body error.
    await page.getByRole('button', { name: /save draft/i }).click();
    await expect(page.getByText(/provide exactly 2 sample/i)).toBeVisible({ timeout: 10_000 });
  });

  test('responsive at 375px — builder stacks, no overflow', async ({ page }) => {
    await openDemoTemplatesTab(page);
    await page.getByRole('button', { name: /submit template/i }).click();
    await page.waitForURL(/\/templates\/new$/, { timeout: 45_000 });
    await page.setViewportSize({ width: 375, height: 800 });
    await expect(page.getByPlaceholder('order_update')).toBeVisible();
    await page.waitForTimeout(300);
    // Use innerWidth (includes the scrollbar) — a tall page's vertical scrollbar
    // otherwise trips the check on the global fixed header, not our content.
    const info = await page.evaluate(() => {
      const vw = window.innerWidth;
      const offenders: string[] = [];
      document.querySelectorAll('*').forEach((el) => {
        const r = el.getBoundingClientRect();
        if (r.right > vw + 1 && r.width > 1)
          offenders.push(`${el.tagName}.${(el.className || '').toString().slice(0, 40)} right=${Math.round(r.right)}`);
      });
      return { scrollW: document.documentElement.scrollWidth, innerW: vw, offenders: offenders.slice(0, 6) };
    });
    expect(info.scrollW, JSON.stringify(info)).toBeLessThanOrEqual(info.innerW + 1);
  });
});
