import { expect, test, type Page } from '@playwright/test';

/**
 * Plan sprint-2/08 Phase C — Workflow engine, full stack (real clicks).
 *
 * Preconditions:
 *   - frontend :3001 + backend :8001 on the plan-08 branch, migrated + seeded;
 *     workflows.read/manage/run granted to tenant Admin (core CSV).
 *
 * Isolation (methodology §7): building + running workflows mutates tenant
 * state, so everything runs on a DEDICATED tenant provisioned via the operator
 * API (setup only — the flow under test stays real clicks). Names timestamped.
 */
const API = process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8001';

const STAMP = Date.now();
const SLUG = `e2e-wf-${STAMP}`;
const ADMIN_EMAIL = `admin-${STAMP}@example.com`;
const ADMIN_PASSWORD = 'E2eStart1!';
const WF_NAME = `Welcome ${STAMP}`;

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

test.describe('Workflow engine — live stack (plan sprint-2/08 Phase C)', () => {
  test.beforeAll(async ({ request }) => {
    const platformLogin = await request.post(`${API}/auth/login`, {
      data: { email: 'platform@example.com', password: 'platform1234', tenantSlug: 'platform' },
    });
    expect(platformLogin.ok()).toBeTruthy();
    const platformToken = (await platformLogin.json()).access_token;

    const provision = await request.post(`${API}/platform/tenants`, {
      headers: { Authorization: `Bearer ${platformToken}` },
      data: {
        name: `E2E Workflows ${STAMP}`,
        slug: SLUG,
        adminName: 'E2E Workflows Admin',
        adminEmail: ADMIN_EMAIL,
        adminPassword: ADMIN_PASSWORD,
      },
    });
    expect(provision.status()).toBe(201);
  });

  test('build a manual → custom-email workflow, publish, run, see the log', async ({ page }) => {
    await login(page, ADMIN_EMAIL, ADMIN_PASSWORD);

    // List → New workflow (opens the editor in edit mode).
    await page.goto(tenantUrl('/workflows'));
    await page.getByRole('button', { name: 'New workflow' }).click();
    await expect(page.getByTestId('workflow-canvas')).toBeVisible();

    // Add a Manual trigger from the palette (search → click-to-add).
    await addNode(page, 'manual', 'manual');
    await expect(page.locator('[data-node-type="manual"]')).toBeVisible();

    // Declare a run input on the trigger.
    await page.locator('[data-node-type="manual"]').click();
    await page.getByTestId('add-manual-input').click();
    await page.getByLabel('Input 1 key').fill('email');
    await page.getByLabel('Input 1 label').fill('Email');

    // Add a Send email action (drops unwired) and connect the trigger to it.
    await addNode(page, 'send email', 'email.send');
    await expect(page.locator('[data-node-type="email.send"]')).toBeVisible();
    await connect(page, 'manual', 'email.send');
    await expect(page.locator('.react-flow__edge')).toHaveCount(1);

    // Configure it as a custom (bare) email (Email type is a SearchSelect).
    await page.locator('[data-node-type="email.send"]').click();
    await page.locator('button[aria-label="Email type"]').click();
    await page.getByRole('option', { name: 'Write a custom email' }).click();
    await page.getByLabel('Subject').fill('Welcome {{ trigger.input.email }}');
    await page.getByLabel('Body').fill('Hello from the workflow engine.');
    await page.getByLabel('To', { exact: true }).fill('{{ trigger.input.email }}');

    // Name it (Settings) and Save (creates the workflow).
    await page.getByRole('tab', { name: 'Settings' }).click();
    await page.getByLabel('Workflow name').fill(WF_NAME);
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await page.waitForURL(/\/workflows\/[^/]+(\?|$)/);

    // Publish (arms the trigger) — proves the validate gate passed.
    await page.getByRole('tab', { name: 'Editor' }).click();
    await page.getByTestId('workflow-publish').click();
    await expect(page.getByTestId('unpublished-badge')).toHaveCount(0);

    // Run — the manual input dialog collects the value, run executes inline.
    await page.getByTestId('workflow-run').click();
    await page.getByTestId('run-input-email').fill('e2e@example.com');
    await page.getByTestId('run-dialog-submit').click();

    // Logs → the run shows Success.
    await page.getByRole('tab', { name: 'Logs' }).click();
    await expect(page.getByTestId('workflow-runs')).toContainText('Success', { timeout: 30_000 });
  });

  test('the workflow appears in the list and can be archived', async ({ page }) => {
    await login(page, ADMIN_EMAIL, ADMIN_PASSWORD);
    await page.goto(tenantUrl('/workflows'));

    const row = page.getByRole('row', { name: new RegExp(WF_NAME) });
    await expect(row).toBeVisible();

    // Select it → bulk Archive (single "Actions" dropdown).
    await row.getByRole('checkbox').click();
    await page.getByRole('button', { name: 'Bulk actions' }).click();
    await page.getByRole('menuitem', { name: 'Archive' }).click();

    // Gone from Active; present in Archived.
    await expect(page.getByRole('row', { name: new RegExp(WF_NAME) })).toHaveCount(0);
    await page.getByRole('radio', { name: 'Archived' }).click();
    await expect(page.getByRole('row', { name: new RegExp(WF_NAME) })).toBeVisible();
  });
});
