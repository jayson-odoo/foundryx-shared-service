import { expect, test, type Page } from '@playwright/test';

/**
 * Plan sprint-3/01 Phase C — Form engine slice 1, full stack (real clicks).
 *
 * Journeys (plan §TDD E2E):
 *   ① build a multi-page form via click-to-add → conditional field → computed
 *     field → publish.
 *   ② fill internally: condition shows/hides live, computed updates, per-page
 *     validation blocks, submit → row lands in the Submissions tab.
 *   ③ Flow tab: add "Under Review" / "Accepted" statuses + edges on the
 *     form's OWN scoped graph → transition the submission via graph-driven
 *     buttons → StatusBadge updates.
 *   ④ Versions: publish v1 → edit draft ("Unpublished changes") → republish
 *     v2 → version list paginates; the old submission still renders v1.
 *
 * Isolation (methodology §7): scoped statuses + submissions mutate tenant
 * state → DEDICATED tenant via the operator API (setup only). Names
 * timestamped.
 */
const API = process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8001';

const STAMP = Date.now();
const SLUG = `e2e-forms-${STAMP}`;
const ADMIN_EMAIL = `admin-${STAMP}@example.com`;
const ADMIN_PASSWORD = 'E2eStart1!';
const FORM_NAME = `Speaker CFP ${STAMP}`;

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

/** Click-to-add from the palette (search → entry; dnd-kit drags are covered
 * in Vitest — Playwright can't drive its pointer sensors). */
async function addField(page: Page, term: string, type: string) {
  await page.getByLabel('Search fields').fill(term);
  await page.getByTestId(`palette-${type}`).click();
  await page.getByLabel('Search fields').fill('');
}

/** The settings panel edits the SELECTED field — select by row, then write. */
async function lastFieldRow(page: Page) {
  return page.locator('[data-testid^="field-row-"]').last();
}

test.describe.configure({ mode: 'serial', timeout: 180_000 });

test.describe('Form engine — live stack (plan sprint-3/01 Phase C)', () => {
  test.beforeAll(async ({ request }) => {
    const platformLogin = await request.post(`${API}/auth/login`, {
      data: { email: 'platform@example.com', password: 'platform1234', tenantSlug: 'platform' },
    });
    expect(platformLogin.ok()).toBeTruthy();
    const platformToken = (await platformLogin.json()).access_token;

    const provision = await request.post(`${API}/platform/tenants`, {
      headers: { Authorization: `Bearer ${platformToken}` },
      data: {
        name: `E2E Forms ${STAMP}`,
        slug: SLUG,
        adminName: 'E2E Forms Admin',
        adminEmail: ADMIN_EMAIL,
        adminPassword: ADMIN_PASSWORD,
      },
    });
    expect(provision.status()).toBe(201);
  });

  test('① build a multi-page form (conditional + computed) and publish', async ({ page }) => {
    await login(page);

    await page.goto(tenantUrl('/forms'));
    await page.getByRole('button', { name: 'New form' }).click();
    await expect(page.getByTestId('form-builder')).toBeVisible();

    // Page 1 — a required text field.
    await addField(page, 'text', 'text');
    await (await lastFieldRow(page)).click();
    await page.getByLabel('Field label').fill('Full name');
    await page.getByLabel('Answer key').fill('fullName');
    await page.getByRole('switch', { name: 'Required' }).click();

    // A yes/no that will drive the conditional.
    await addField(page, 'yes', 'yesno');
    await (await lastFieldRow(page)).click();
    await page.getByLabel('Field label').fill('Workshop?');
    await page.getByLabel('Answer key').fill('isWorkshop');

    // Two numbers feeding a computed field.
    await addField(page, 'number', 'number');
    await (await lastFieldRow(page)).click();
    await page.getByLabel('Field label').fill('Seats');
    await page.getByLabel('Answer key').fill('seats');

    await addField(page, 'number', 'number');
    await (await lastFieldRow(page)).click();
    await page.getByLabel('Field label').fill('Fee');
    await page.getByLabel('Answer key').fill('fee');

    // Computed: seats * fee.
    await addField(page, 'calculated', 'computed');
    await (await lastFieldRow(page)).click();
    await page.getByLabel('Field label').fill('Revenue');
    await page.getByLabel('Answer key').fill('revenue');
    await page.getByTestId('computed-expression').fill('seats * fee');
    await expect(page.getByTestId('computed-error')).toHaveCount(0);

    // Conditional: Seats visible only when Workshop? is true (RuleBuilder).
    // Picking a boolean fact auto-sets the operator to "is yes" (is_true), so
    // no operator step is needed.
    const seatsRow = page.locator('[data-testid^="field-row-"]', { hasText: 'Seats' }).first();
    await seatsRow.click();
    await page.getByRole('button', { name: /add condition/i }).click();
    await page.getByRole('combobox', { name: 'Fact' }).first().click();
    await page.getByRole('option', { name: 'Workshop?' }).click();
    await expect(page.getByRole('combobox', { name: 'Operator' }).first()).toContainText(/is yes/i);

    // Second page with a textarea.
    await page.getByTestId('form-add-page').click();
    const page2 = page.locator('[data-testid^="page-card-"]').last();
    await page2.locator('[data-testid^="section-card-"]').first().click();
    await addField(page, 'long', 'textarea');
    await (await lastFieldRow(page)).click();
    await page.getByLabel('Field label').fill('Abstract');
    await page.getByLabel('Answer key').fill('abstract');
    await page.getByRole('switch', { name: 'Required' }).click();

    // Name it in Settings, save, publish.
    await page.getByRole('tab', { name: 'Settings' }).click();
    await page.getByLabel('Form name').fill(FORM_NAME);
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page).toHaveURL(/\/forms\/(?!new)[a-z0-9-]+/i);

    await page.getByRole('tab', { name: 'Builder' }).click();
    await page.getByTestId('publish-form').click();
    await expect(page.getByText(/Published — the form can now be filled/i)).toBeVisible();
    await expect(page.getByText('Published · v1')).toBeVisible();
  });

  test('② fill internally — conditions live, computed updates, validation blocks, submit', async ({
    page,
  }) => {
    await login(page);

    // Real users click through: list → form → Fill link target.
    await page.goto(tenantUrl('/forms'));
    await page.getByText(FORM_NAME, { exact: true }).click();
    await page.getByTestId('copy-fill-link').waitFor();
    const formUrl = page.url();
    const formId = formUrl.match(/\/forms\/([a-z0-9-]+)/i)?.[1] as string;
    await page.goto(tenantUrl(`/forms/${formId}/fill`));

    // Page 1: Seats hidden until Workshop? = Yes.
    await expect(page.getByText('Seats')).toHaveCount(0);
    await page.getByRole('button', { name: 'Yes', exact: true }).click();
    await expect(page.getByText('Seats')).toBeVisible();

    // Computed updates live.
    await page.locator('#ff-seats').fill('10');
    await page.locator('#ff-fee').fill('25');
    await expect(page.getByText('250')).toBeVisible();

    // Required gate: Next without Full name blocks with an inline error.
    await page.getByRole('button', { name: 'Next' }).click();
    await expect(page.getByText(/required/i).first()).toBeVisible();
    await page.locator('#ff-fullName').fill('E2E Speaker');
    await page.getByRole('button', { name: 'Next' }).click();

    // Page 2: submit (Abstract required → fill it).
    await page.locator('#ff-abstract').fill('A talk about building form engines end-to-end.');
    await page.getByRole('button', { name: 'Submit', exact: true }).click();
    await expect(page.getByTestId('fill-success')).toBeVisible();

    // The submission lands in the form's Submissions tab.
    await page.goto(tenantUrl(`/forms/${formId}`));
    await page.getByRole('tab', { name: 'Submissions' }).click();
    await expect(page.getByText('E2E Forms Admin').first()).toBeVisible();
    await expect(page.getByText('Submitted').first()).toBeVisible();
  });

  test('③ Flow tab — custom scoped statuses + graph-driven transition', async ({ page }) => {
    await login(page);

    await page.goto(tenantUrl('/forms'));
    await page.getByText(FORM_NAME, { exact: true }).click();

    // The form's OWN pipeline (scoped machine) — seeded Draft + Submitted.
    await page.getByRole('tab', { name: 'Flow' }).click();
    await expect(page.getByTestId('status-node-draft')).toBeVisible();
    await expect(page.getByTestId('status-node-submitted')).toBeVisible();

    // Edit → add "Under Review" + an edge Submitted → Under Review.
    await page.getByRole('button', { name: 'Edit', exact: true }).click();
    await page.getByRole('button', { name: /add status/i }).click();
    await page.getByLabel(/Label/).fill('Under Review');
    await page.getByRole('button', { name: 'Create', exact: true }).click();
    const reviewNode = page.getByTestId('status-node-under_review');
    await expect(reviewNode).toBeVisible();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await page.waitForTimeout(400);

    const sourceHandle = page.getByTestId('status-node-submitted').getByTestId('source-handle');
    const targetHandle = reviewNode.getByTestId('target-handle');
    const s = (await sourceHandle.boundingBox())!;
    const t = (await targetHandle.boundingBox())!;
    await page.mouse.move(s.x + s.width / 2, s.y + s.height / 2);
    await page.mouse.down();
    await page.mouse.move(t.x + t.width / 2, t.y + t.height / 2, { steps: 12 });
    await page.mouse.up();
    await expect(page.getByText(/Submitted → Under Review/)).toBeVisible();
    await page.getByLabel(/Action label/).fill('Start review');
    await page.getByRole('button', { name: 'Create transition' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);

    // Transition the existing submission via the graph-driven button.
    await page.getByRole('tab', { name: 'Submissions' }).click();
    await page.getByText('E2E Forms Admin').first().click();
    await expect(page.getByTestId('submission-transitions')).toBeVisible();
    await page.getByTestId('transition-start-review').click();
    await expect(page.getByText('Under Review').first()).toBeVisible();
  });

  test('④ versions — republish creates v2; the old submission still renders v1', async ({
    page,
  }) => {
    await login(page);

    await page.goto(tenantUrl('/forms'));
    await page.getByText(FORM_NAME, { exact: true }).click();

    // Edit the draft: relabel Full name → "Unpublished changes" appears.
    await page.getByRole('button', { name: 'Edit', exact: true }).click();
    await page.locator('[data-testid^="field-row-"]', { hasText: 'Full name' }).first().click();
    await page.getByLabel('Field label').fill('Speaker name');
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByTestId('unpublished-changes')).toBeVisible();

    // Republish → v2; Versions tab lists both, v2 current.
    await page.getByTestId('publish-form').click();
    await expect(page.getByText('Published · v2')).toBeVisible();
    await page.getByRole('tab', { name: 'Versions' }).click();
    const versions = page.getByTestId('form-versions');
    await expect(versions).toBeVisible();
    await expect(versions.getByText('v2', { exact: false })).toBeVisible();
    await expect(versions.getByText('v1', { exact: false })).toBeVisible();

    // The pre-existing submission re-renders against its PINNED v1: the field
    // still reads "Full name" even though the draft (v2) renamed it to
    // "Speaker name" (D9). (The value also appears in the raw-answers panel,
    // hence .first() on the rendered field.)
    await page.getByRole('tab', { name: 'Submissions' }).click();
    await page.getByText('E2E Forms Admin').first().click();
    await expect(page.getByText('Full name', { exact: true })).toBeVisible();
    await expect(page.getByText('Speaker name', { exact: true })).toHaveCount(0);
    await expect(page.getByText('E2E Speaker').first()).toBeVisible();
  });
});
