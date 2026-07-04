import { expect, test, type Page } from '@playwright/test';

/**
 * Plan sprint-3/04 Phase C — Document management (the Drive), full stack (real
 * clicks). Mapped to the UAT (`04-document-mgmt-drive-uat.md`).
 *
 * Journeys:
 *   ① create nested folders, navigate via tree + breadcrumb (AC-NAV, AC-FOLDER).
 *   ② upload a file → it appears; same-name upload → conflict → Keep both →
 *      "name (1)" (AC-UPLOAD-01/06/08).
 *   ③ rename a file via the right-click menu (AC-FILE-01).
 *   ④ delete a folder → Trash → Restore (AC-TRASH-01/02).
 *   ⑤ bulk-select a folder → Download ZIP → My Downloads shows Ready
 *      (AC-DOWNLOAD-02).
 *
 * Isolation (methodology §7): the Drive mutates tenant state → DEDICATED tenant
 * via the operator API (setup only). Names timestamped.
 */
const API = process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8001';

const STAMP = Date.now();
const SLUG = `e2e-docs-${STAMP}`;
const ADMIN_EMAIL = `admin-${STAMP}@example.com`;
const ADMIN_PASSWORD = 'E2eStart1!';

function tenantUrl(pathname: string): string {
  return `http://${SLUG}.localhost:3001${pathname}`;
}

async function login(page: Page) {
  await page.goto(tenantUrl('/signin'));
  await page.getByPlaceholder('Your email').fill(ADMIN_EMAIL);
  await page.getByPlaceholder('Your password').fill(ADMIN_PASSWORD);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));
}

async function newFolder(page: Page, name: string) {
  await page.getByRole('button', { name: 'New folder' }).click();
  await page.getByLabel('Folder name').fill(name);
  await page.getByRole('button', { name: 'Create' }).click();
  await expect(page.locator('[data-entry="folder"]', { hasText: name }).first()).toBeVisible();
}

/** Open a folder via the tree sidebar — the reliable nav path (grid dblclick is
 * a real feature but, layered on dnd-kit + a Radix context-menu trigger, isn't
 * deterministically drivable by Playwright — same class as the canvas
 * click-to-add lesson). Asserts the breadcrumb (scoped) updated. */
async function openFolder(page: Page, name: string) {
  await page.locator(`[data-tree-folder="${name}"]`).first().click();
  await expect(page.getByTestId('drive-breadcrumb').getByRole('button', { name })).toBeVisible();
}

/** Open an entry's cursor-anchored context menu (sprint-3/04b). The cards are
 * dnd-kit draggables; a plain onContextMenu handler opens the custom menu, so
 * dispatching the `contextmenu` event directly is the reliable E2E path. */
async function rightClickEntry(page: Page, kind: 'file' | 'folder', name: string) {
  const card = page.locator(`[data-entry="${kind}"]`, { hasText: name }).first();
  await expect(card).toBeVisible();
  await card.dispatchEvent('contextmenu');
  await expect(page.getByRole('menuitem').first()).toBeVisible();
}

/** Upload via the Upload dialog (sprint-3/04b): the button opens a dialog with a
 * type picker + drop-zone; feed its hidden input (the E2E equivalent of
 * choosing a file). The dialog enqueues + closes on selection. */
async function uploadFile(page: Page, name: string, body: string) {
  await page.getByRole('button', { name: 'Upload', exact: true }).click();
  await page.locator('input[type="file"]').setInputFiles({
    name,
    mimeType: 'application/pdf',
    buffer: Buffer.from(`%PDF-1.4\n${body}`),
  });
}

test.describe.configure({ mode: 'serial', timeout: 180_000 });

test.describe('Document Drive — live stack (plan sprint-3/04 Phase C)', () => {
  test.beforeAll(async ({ request }) => {
    const platformLogin = await request.post(`${API}/auth/login`, {
      data: { email: 'platform@example.com', password: 'platform1234', tenantSlug: 'platform' },
    });
    expect(platformLogin.ok()).toBeTruthy();
    const platformToken = (await platformLogin.json()).access_token;

    const provision = await request.post(`${API}/platform/tenants`, {
      headers: { Authorization: `Bearer ${platformToken}` },
      data: {
        name: `E2E Docs ${STAMP}`,
        slug: SLUG,
        adminName: 'E2E Docs Admin',
        adminEmail: ADMIN_EMAIL,
        adminPassword: ADMIN_PASSWORD,
      },
    });
    expect(provision.status()).toBe(201);
  });

  test('① create + navigate nested folders', async ({ page }) => {
    await login(page);
    await page.goto(tenantUrl('/documents'));
    await expect(page.getByRole('button', { name: 'New folder' })).toBeVisible();

    await newFolder(page, 'Quotations');
    await openFolder(page, 'Quotations');
    await newFolder(page, '2026');

    // Navigate back to root via the Drive crumb.
    await page.getByRole('button', { name: 'Drive', exact: true }).first().click();
    await expect(page.locator('[data-entry="folder"]', { hasText: 'Quotations' }).first()).toBeVisible();
  });

  test('② upload + collision → keep both', async ({ page }) => {
    await login(page);
    await page.goto(tenantUrl('/documents'));

    await uploadFile(page, 'quote.pdf', 'one');
    await expect(page.locator('[data-entry="file"]', { hasText: 'quote.pdf' }).first()).toBeVisible();

    // Same name again → the Uploads drawer offers Replace / Keep both.
    await uploadFile(page, 'quote.pdf', 'two');
    await expect(page.getByText(/already exists here/i)).toBeVisible();
    await page.getByRole('button', { name: 'Keep both' }).click();
    await expect(page.locator('[data-entry="file"]', { hasText: 'quote (1).pdf' }).first()).toBeVisible();
  });

  test('③ rename a file via the context menu', async ({ page }) => {
    await login(page);
    await page.goto(tenantUrl('/documents'));
    await uploadFile(page, 'draft.pdf', 'x');
    await rightClickEntry(page, 'file', 'draft.pdf');
    await page.getByRole('menuitem', { name: 'Rename' }).click();
    await page.locator('#drive-name-input').fill('final.pdf');
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page.locator('[data-entry="file"]', { hasText: 'final.pdf' }).first()).toBeVisible();
  });

  test('④ delete a folder → Trash → Restore', async ({ page }) => {
    await login(page);
    await page.goto(tenantUrl('/documents'));
    await newFolder(page, 'Temp');
    const folder = page.locator('[data-entry="folder"]', { hasText: 'Temp' }).first();
    await rightClickEntry(page, 'folder', 'Temp');
    // Wait for the soft-delete request to commit before switching to Trash (the
    // Trash view fetches once on mount — racing it shows an empty trash).
    await Promise.all([
      page.waitForResponse((r) => r.url().includes('/documents/folders/delete') && r.ok()),
      page.getByRole('menuitem', { name: 'Delete' }).click(),
    ]);
    await expect(folder).toBeHidden();

    await page.getByRole('button', { name: 'Trash' }).click();
    const trashSelect = page.getByLabel('Select Temp');
    await expect(trashSelect).toBeVisible({ timeout: 15_000 });
    await trashSelect.click();
    await page.getByRole('button', { name: 'Restore' }).click();
    await page.getByRole('button', { name: 'Trash' }).click(); // back to Drive
    await expect(page.locator('[data-entry="folder"]', { hasText: 'Temp' }).first()).toBeVisible();
  });

  test('⑤ download a folder as ZIP via right-click → My Downloads ready', async ({ page }) => {
    await login(page);
    await page.goto(tenantUrl('/documents'));
    await newFolder(page, 'Bundle');
    await openFolder(page, 'Bundle');
    await uploadFile(page, 'a.pdf', 'a');
    await uploadFile(page, 'b.pdf', 'b');
    await expect(page.locator('[data-entry="file"]', { hasText: 'b.pdf' }).first()).toBeVisible();
    // Back to root (re-load is the reliable nav; the uploaded files persist).
    await page.goto(tenantUrl('/documents'));

    // Right-click the folder → Download ZIP (bulk actions live in the menu now).
    await rightClickEntry(page, 'folder', 'Bundle');
    await page.getByRole('menuitem', { name: 'Download ZIP' }).click();
    // My Downloads drawer (global) opens; the job becomes ready.
    await expect(page.getByText('My downloads')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Download' }).first()).toBeVisible({ timeout: 15_000 });
  });
});
