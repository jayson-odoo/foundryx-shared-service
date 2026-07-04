import { expect, test, type Page } from '@playwright/test';

/**
 * Plan sprint-2/10 Phase C — BL-064 undo/redo + non-destructive Tidy on the
 * workflow canvas (the shared `useHistory` hook end-to-end, real clicks).
 *
 * Preconditions: frontend :3001 + backend :8001 on the plan-10 branch, migrated
 * + seeded; workflows.read/manage granted to tenant Admin.
 *
 * Isolation (methodology §7): a DEDICATED tenant per run; names timestamped.
 */
const API = process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8001';

const STAMP = Date.now();
const SLUG = `e2e-wf10-${STAMP}`;
const ADMIN_EMAIL = `admin-${STAMP}@example.com`;
const ADMIN_PASSWORD = 'E2eStart1!';

function tenantUrl(pathname: string): string {
  return `http://${SLUG}.localhost:3001${pathname}`;
}

async function login(page: Page, email: string, password: string) {
  await page.goto(tenantUrl('/signin'));
  await page.getByPlaceholder('Your email').fill(email);
  await page.getByPlaceholder('Your password').fill(password);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));
}

/** Palette sections are collapsed by default — search surfaces the item. */
async function addNode(page: Page, term: string, type: string) {
  await page.getByTestId('palette-search').fill(term);
  await page.getByTestId(`palette-${type}`).click();
  await page.getByTestId('palette-search').fill('');
}

/** Wire one node's source handle to another's target handle (no auto-connect). */
async function connect(page: Page, fromType: string, toType: string) {
  const src = page.locator(`[data-node-type="${fromType}"] [data-testid="source-handle"]`);
  const tgt = page.locator(`[data-node-type="${toType}"] [data-testid="target-handle"]`);
  const s = (await src.boundingBox())!;
  const t = (await tgt.boundingBox())!;
  await page.mouse.move(s.x + s.width / 2, s.y + s.height / 2);
  await page.mouse.down();
  await page.mouse.move(t.x + t.width / 2, t.y + t.height / 2, { steps: 12 });
  await page.mouse.up();
}

test.describe.configure({ mode: 'serial', timeout: 120_000 });

test.describe('Workflow canvas polish — BL-064 (plan sprint-2/10 Phase C)', () => {
  test.beforeAll(async ({ request }) => {
    const platformLogin = await request.post(`${API}/auth/login`, {
      data: { email: 'platform@example.com', password: 'platform1234', tenantSlug: 'platform' },
    });
    expect(platformLogin.ok()).toBeTruthy();
    const platformToken = (await platformLogin.json()).access_token;

    const provision = await request.post(`${API}/platform/tenants`, {
      headers: { Authorization: `Bearer ${platformToken}` },
      data: {
        name: `E2E WF10 ${STAMP}`,
        slug: SLUG,
        adminName: 'E2E WF10 Admin',
        adminEmail: ADMIN_EMAIL,
        adminPassword: ADMIN_PASSWORD,
      },
    });
    expect(provision.status(), await provision.text()).toBe(201);
  });

  test('undo/redo + non-destructive Tidy round-trip', async ({ page }) => {
    await login(page, ADMIN_EMAIL, ADMIN_PASSWORD);

    await page.goto(tenantUrl('/workflows'));
    await page.getByRole('button', { name: 'New workflow' }).click();
    await expect(page.getByTestId('workflow-canvas')).toBeVisible();

    // Empty timeline — nothing to undo yet.
    await expect(page.getByTestId('canvas-undo')).toBeDisabled();

    // Build a trigger → action graph (each op is one history entry).
    await addNode(page, 'manual', 'manual');
    await expect(page.locator('[data-node-type="manual"]')).toBeVisible();
    await addNode(page, 'send email', 'email.send');
    await expect(page.locator('[data-node-type]')).toHaveCount(2);
    await connect(page, 'manual', 'email.send');
    await expect(page.locator('.react-flow__edge')).toHaveCount(1);
    await expect(page.getByTestId('canvas-undo')).toBeEnabled();

    // Tidy is NON-DESTRUCTIVE: structure intact, and it pushes an undoable entry.
    await page.getByTestId('canvas-tidy').click();
    await expect(page.locator('[data-node-type]')).toHaveCount(2);
    await expect(page.locator('.react-flow__edge')).toHaveCount(1);

    // Undo Tidy → structure still intact (only the layout reverted).
    await page.getByTestId('canvas-undo').click();
    await expect(page.locator('[data-node-type]')).toHaveCount(2);
    await expect(page.locator('.react-flow__edge')).toHaveCount(1);

    // Undo the connect → edge gone; undo the add-email → one node left.
    await page.getByTestId('canvas-undo').click();
    await expect(page.locator('.react-flow__edge')).toHaveCount(0);
    await page.getByTestId('canvas-undo').click();
    await expect(page.locator('[data-node-type]')).toHaveCount(1);

    // Redo restores the email node and then the edge.
    await page.getByTestId('canvas-redo').click();
    await expect(page.locator('[data-node-type]')).toHaveCount(2);
    await page.getByTestId('canvas-redo').click();
    await expect(page.locator('.react-flow__edge')).toHaveCount(1);
  });
});
