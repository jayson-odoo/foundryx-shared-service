import { expect, test, type Browser, type Page } from '@playwright/test';

/**
 * Plan sprint-3/05 Phase C — Document sharing (Google-Drive model), full stack
 * (real clicks). Mapped to `05-document-mgmt-sharing-uat.md`.
 *
 * Journeys:
 *   ① Workspace link (one stable URL) → opened logged-out shows "Sign in to
 *      access"; opened by the signed-in member routes into the in-app SCOPED
 *      view (only the shared item, not the whole Drive).
 *   ② Public + Viewer file link → anonymous branded mini-Drive (preview + Download),
 *      verified at 375px.
 *   ③ Public + Editor folder link → an anonymous visitor uploads → appears live.
 *   ④ Oversight lists links; revoke (kill-switch) → the public URL 404s.
 *
 * Isolation: a dedicated tenant per run (operator API); the ceiling is set via
 * the admin API (a slice-04 enum). Names timestamped.
 */
const API = process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8001';
const STAMP = Date.now();
const SLUG = `e2e-share-${STAMP}`;
const ADMIN_EMAIL = `admin-${STAMP}@example.com`;
const ADMIN_PASSWORD = 'E2eStart1!';

const ACCESS_LABEL = {
  restricted: 'Restricted — only people added below',
  workspace: 'Anyone in the workspace',
  public: 'Anyone with the link',
} as const;

function tenantUrl(pathname: string): string {
  return `http://${SLUG}.localhost:3001${pathname}`;
}

async function login(page: Page) {
  // Retry the whole flow — the dev server can serve the signin page before React
  // hydrates, so an early click native-submits the form (GET ?email=…) and never
  // authenticates. Reload + retry until we leave /signin.
  for (let attempt = 0; attempt < 3; attempt++) {
    await page.goto(tenantUrl('/signin'));
    await page.waitForLoadState('networkidle').catch(() => {});
    const btn = page.getByRole('button', { name: /sign in/i });
    await btn.waitFor({ state: 'visible' });
    await page.getByPlaceholder('Your email').fill(ADMIN_EMAIL);
    await page.getByPlaceholder('Your password').fill(ADMIN_PASSWORD);
    await page.waitForTimeout(400); // let hydration attach the onSubmit handler
    await btn.click();
    try {
      await page.waitForURL((url) => !url.pathname.startsWith('/signin'), { timeout: 30_000 });
      return;
    } catch {
      /* native-submit / cold compile — retry */
    }
  }
  throw new Error('login did not complete');
}

async function newFolder(page: Page, name: string) {
  await page.getByRole('button', { name: 'New folder' }).click();
  await page.getByLabel('Folder name').fill(name);
  await page.getByRole('button', { name: 'Create' }).click();
  await expect(page.locator('[data-entry="folder"]', { hasText: name }).first()).toBeVisible();
}

async function uploadFile(page: Page, name: string, body: string) {
  await page.getByRole('button', { name: 'Upload', exact: true }).click();
  await page.locator('input[type="file"]').setInputFiles({
    name,
    mimeType: 'application/pdf',
    buffer: Buffer.from(`%PDF-1.4\n${body}`),
  });
}

/** The upload drawer (Sheet) auto-opens and its overlay intercepts clicks. */
async function closeDrawers(page: Page) {
  const overlay = page.locator('[data-slot="sheet-overlay"]');
  for (let i = 0; i < 4 && (await overlay.count()) > 0; i++) {
    await page.keyboard.press('Escape');
    await page.waitForTimeout(150);
  }
}

async function rightClickEntry(page: Page, kind: 'file' | 'folder', name: string) {
  await closeDrawers(page);
  const card = page.locator(`[data-entry="${kind}"]`, { hasText: name }).first();
  await expect(card).toBeVisible();
  await card.dispatchEvent('contextmenu');
  await expect(page.getByRole('menuitem', { name: 'Share' })).toBeVisible();
}

async function pickSelect(page: Page, ariaLabel: string, optionText: string) {
  await page.getByRole('combobox', { name: ariaLabel }).click();
  await page.getByRole('option', { name: optionText }).click();
}

/** Open the Share dialog (ensures the stable link), set general access (+role),
 * and return the copyable frontend URL. */
async function shareLink(
  page: Page,
  kind: 'file' | 'folder',
  name: string,
  access: 'restricted' | 'workspace' | 'public',
  role: 'view' | 'edit' = 'view',
): Promise<string> {
  await rightClickEntry(page, kind, name);
  await page.getByRole('menuitem', { name: 'Share' }).click();
  await expect(page.getByRole('heading', { name: 'Share' })).toBeVisible();
  await expect(page.getByTestId('share-url')).toBeVisible(); // ensure() resolved
  if (access !== 'restricted') {
    await pickSelect(page, 'General access', ACCESS_LABEL[access]);
  }
  if (role === 'edit') {
    await pickSelect(page, 'General role', 'Editor');
  }
  const url = await page.getByTestId('share-url').inputValue();
  expect(url).toContain('/public/documents/');
  await page.keyboard.press('Escape');
  return url;
}

async function anonPage(browser: Browser, mobile = false): Promise<Page> {
  const ctx = await browser.newContext(mobile ? { viewport: { width: 375, height: 812 } } : {});
  return ctx.newPage();
}

test.describe.configure({ mode: 'serial', timeout: 180_000 });

test.describe('Document sharing — live stack (plan sprint-3/05 Phase C)', () => {
  test.beforeAll(async ({ request }) => {
    const platformLogin = await request.post(`${API}/auth/login`, {
      data: { email: 'platform@example.com', password: 'platform1234', tenantSlug: 'platform' },
    });
    expect(platformLogin.ok()).toBeTruthy();
    const platformToken = (await platformLogin.json()).access_token;

    const provision = await request.post(`${API}/platform/tenants`, {
      headers: { Authorization: `Bearer ${platformToken}` },
      data: {
        name: `E2E Share ${STAMP}`,
        slug: SLUG,
        adminName: 'E2E Share Admin',
        adminEmail: ADMIN_EMAIL,
        adminPassword: ADMIN_PASSWORD,
      },
    });
    expect(provision.status()).toBe(201);

    const adminLogin = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD, tenantSlug: SLUG },
    });
    const adminToken = (await adminLogin.json()).access_token;
    const put = await request.put(`${API}/documents/settings`, {
      headers: { Authorization: `Bearer ${adminToken}` },
      data: { publicSharing: 'edit' },
    });
    expect(put.ok()).toBeTruthy();
  });

  test('① workspace link — logged-out signs in, member sees it under Shared with me', async ({ page, browser }) => {
    await login(page);
    await page.goto(tenantUrl('/documents'));
    await uploadFile(page, 'internal-doc.pdf', 'i');
    await expect(page.locator('[data-entry="file"]', { hasText: 'internal-doc.pdf' }).first()).toBeVisible();

    const url = await shareLink(page, 'file', 'internal-doc.pdf', 'workspace');

    // Logged-out → "Sign in to access" (not a blank not-available).
    const anon = await anonPage(browser);
    await anon.goto(url);
    await expect(anon.getByTestId('share-signin')).toBeVisible();
    await anon.context().close();

    // The signed-in member is routed to All-documents → Shared with me, with the
    // item already browsing in place (the standalone scoped page is gone).
    await page.goto(url);
    await page.waitForURL(/\/documents\?shared=/);
    await expect(page.getByText('Shared with me').first()).toBeVisible();
    await expect(page.getByTestId('share-download')).toBeVisible();
  });

  test('② public+view file → branded anonymous mini-Drive (mobile)', async ({ page, browser }) => {
    await login(page);
    await page.goto(tenantUrl('/documents'));
    await uploadFile(page, 'public-doc.pdf', 'p');
    await expect(page.locator('[data-entry="file"]', { hasText: 'public-doc.pdf' }).first()).toBeVisible();

    const url = await shareLink(page, 'file', 'public-doc.pdf', 'public', 'view');

    const anon = await anonPage(browser, true);
    await anon.goto(url);
    await expect(anon.getByTestId('share-download')).toBeVisible();
    await expect(anon.getByText('public-doc.pdf').first()).toBeVisible();
    const overflow = await anon.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(2);
    await anon.context().close();
  });

  test('③ public+edit folder → anonymous upload appears live', async ({ page, browser }) => {
    await login(page);
    await page.goto(tenantUrl('/documents'));
    const folder = `Inbox ${STAMP}`;
    await newFolder(page, folder);

    const url = await shareLink(page, 'folder', folder, 'public', 'edit');

    const anon = await anonPage(browser);
    await anon.goto(url);
    await expect(anon.getByTestId('share-upload')).toBeVisible();
    await anon.locator('[data-testid="share-upload-input"]').setInputFiles({
      name: 'from-guest.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.4\nguest'),
    });
    await expect(anon.getByTestId('share-file').filter({ hasText: 'from-guest.pdf' })).toBeVisible({
      timeout: 30_000,
    });
    await anon.context().close();

    await page.goto(tenantUrl('/documents'));
    await page.locator(`[data-tree-folder="${folder}"]`).first().click();
    await expect(page.locator('[data-entry="file"]', { hasText: 'from-guest.pdf' }).first()).toBeVisible();
  });

  test('④ oversight lists links; revoke → public URL 404s', async ({ page, browser }) => {
    await login(page);
    await page.goto(tenantUrl('/documents'));
    await uploadFile(page, 'revoke-doc.pdf', 'r');
    await expect(page.locator('[data-entry="file"]', { hasText: 'revoke-doc.pdf' }).first()).toBeVisible();
    const url = await shareLink(page, 'file', 'revoke-doc.pdf', 'public', 'view');

    const anon = await anonPage(browser);
    await anon.goto(url);
    await expect(anon.getByTestId('share-download')).toBeVisible();

    // Oversight lists the link, then revoke it from its row (kill-switch).
    await page.goto(tenantUrl('/documents/shares'));
    const row = page.getByRole('row', { name: /revoke-doc\.pdf/ });
    await expect(row).toBeVisible({ timeout: 15_000 });
    await row.getByRole('button', { name: 'Actions' }).click();
    await page.getByRole('menuitem', { name: 'Revoke' }).click();
    await page.getByRole('button', { name: 'Revoke', exact: true }).click();

    // The previously-open anonymous page now 404s on reload.
    await anon.reload();
    await expect(anon.getByTestId('share-notfound')).toBeVisible();
    await anon.context().close();
  });
});
