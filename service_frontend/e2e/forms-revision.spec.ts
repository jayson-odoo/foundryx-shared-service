import { expect, test, type Page } from '@playwright/test';

/**
 * Plan sprint-4/04 Phase C - Form submission revisions, full stack (real clicks).
 *
 * Journey (plan §Slices 2 / AC-04-RV-25):
 *   ① A revisions-enabled published form + one submitted entry (API setup).
 *   ② Open the submission → it's frozen (Submitted) → click **Revise** → a new
 *     Draft rev 2 opens, "Current · rev 2" badge, revision history lists 2.
 *   ③ **Edit & resubmit**: the fill page is pre-filled with the cloned answers
 *     (pinned to the revision's version) → edit → **Submit revision** → back on
 *     the detail, rev 2 is Submitted with the edited answer.
 *   ④ The default Submissions list shows ONE row per group (current rev 2, a
 *     "rev 2" badge); the prior rev 1 is frozen + unchanged (immutability).
 *
 * Isolation (methodology §7): submissions + scoped statuses mutate tenant state
 * → DEDICATED tenant via the operator API (setup only). Names timestamped.
 * Ports come from env so it runs against either the standard (3001/8001) or an
 * isolated (e.g. 3002/8012) stack.
 */
const API = process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8001';
const PORT = process.env.E2E_PORT ?? '3001';

const STAMP = Date.now();
const SLUG = `e2e-rev-${STAMP}`;
const ADMIN_EMAIL = `admin-${STAMP}@example.com`;
const ADMIN_PASSWORD = 'E2eStart1!';

let formId = '';
let firstSubmissionId = '';

function tenantUrl(pathname: string): string {
  return `http://${SLUG}.localhost:${PORT}${pathname}`;
}

async function login(page: Page) {
  await page.goto(tenantUrl('/signin'));
  await page.getByPlaceholder('Your email').fill(ADMIN_EMAIL);
  await page.getByPlaceholder('Your password').fill(ADMIN_PASSWORD);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));
}

test.describe.configure({ mode: 'serial', timeout: 180_000 });

test.describe('Form revisions - live stack (plan sprint-4/04)', () => {
  test.beforeAll(async ({ request }) => {
    const plat = await request.post(`${API}/auth/login`, {
      data: { email: 'platform@example.com', password: 'platform1234', tenantSlug: 'platform' },
    });
    expect(plat.ok()).toBeTruthy();
    const platToken = (await plat.json()).access_token;

    const prov = await request.post(`${API}/platform/tenants`, {
      headers: { Authorization: `Bearer ${platToken}` },
      data: {
        name: `E2E Rev ${STAMP}`,
        slug: SLUG,
        adminName: 'E2E Rev Admin',
        adminEmail: ADMIN_EMAIL,
        adminPassword: ADMIN_PASSWORD,
      },
    });
    expect(prov.status()).toBe(201);

    const loginRes = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD, tenantSlug: SLUG },
    });
    const auth = { Authorization: `Bearer ${(await loginRes.json()).access_token}` };

    // A revisions-enabled published form with one required text field.
    const form = await (
      await request.post(`${API}/forms`, {
        headers: auth,
        data: { name: `Proposal ${STAMP}`, access: 'internal' },
      })
    ).json();
    formId = form.id;
    const doc = {
      schemaVersion: 1,
      pages: [
        {
          id: 'p1',
          title: 'Page 1',
          sections: [
            {
              id: 's1',
              title: 'Details',
              fields: [{ id: 'f1', type: 'text', key: 'title', label: 'Proposal title', required: true }],
            },
          ],
        },
      ],
    };
    await request.patch(`${API}/forms/${formId}`, { headers: auth, data: { draftDefinition: doc } });
    await request.patch(`${API}/forms/${formId}`, { headers: auth, data: { allowRevisions: true } });
    expect((await request.post(`${API}/forms/${formId}/publish`, { headers: auth })).status()).toBe(200);

    const sub = await (
      await request.post(`${API}/forms/${formId}/submissions`, {
        headers: auth,
        data: { answers: { title: 'Original proposal' } },
      })
    ).json();
    firstSubmissionId = sub.id;
    expect(sub.statusKey).toBe('submitted');
    expect(sub.revisionNumber).toBe(1);
    expect(sub.submissionGroupId).toBe(sub.id);
  });

  test('① revise a frozen submission → Draft rev 2 with history', async ({ page }) => {
    await login(page);
    await page.goto(tenantUrl(`/forms/${formId}/submissions/${firstSubmissionId}`));

    await expect(page.getByTestId('revise-submission')).toBeVisible();
    await page.getByTestId('revise-submission').click();

    // Landed on the new Draft revision.
    await page.waitForURL((url) => !url.pathname.endsWith(firstSubmissionId));
    await expect(page.getByTestId('revision-badge')).toContainText(/Current · rev 2/);
    await expect(page.getByTestId('edit-revision')).toBeVisible();
    // History lists both revisions.
    const history = page.getByTestId('revision-history');
    await expect(history.getByText('rev 2')).toBeVisible();
    await expect(history.getByText('rev 1')).toBeVisible();
  });

  test('② edit & resubmit the revision', async ({ page }) => {
    await login(page);
    // Re-enter via the stale original's detail, then open the current revision
    // (rev 2) from its history panel and edit it.
    await page.goto(tenantUrl(`/forms/${formId}/submissions/${firstSubmissionId}`));
    await page.getByTestId('revision-history').getByText('rev 2').click();
    await expect(page.getByTestId('edit-revision')).toBeVisible();
    await page.getByTestId('edit-revision').click();
    await page.waitForURL((url) => url.pathname.endsWith('/fill'));

    const field = page.getByRole('textbox', { name: 'Proposal title' });
    await expect(field).toHaveValue('Original proposal'); // pre-filled clone
    await field.fill('Revised proposal v2');
    await page.getByRole('button', { name: /submit revision/i }).click();

    // Redirected back to the detail - rev 2 is now Submitted with the edit.
    await page.waitForURL((url) => url.pathname.includes('/submissions/'));
    await expect(page.getByTestId('revision-badge')).toContainText(/Current · rev 2/);
    // The edited answer renders (the field cell, not the raw-JSON sidebar).
    await expect(page.getByText('Revised proposal v2').first()).toBeVisible();
  });

  test('③ list shows one current row; rev 1 stays immutable', async ({ page, request }) => {
    const loginRes = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD, tenantSlug: SLUG },
    });
    const auth = { Authorization: `Bearer ${(await loginRes.json()).access_token}` };

    // Default list = one row per group (the current rev 2).
    const list = await (
      await request.get(`${API}/forms/${formId}/submissions`, { headers: auth })
    ).json();
    expect(list.total).toBe(1);
    expect(list.data[0].revisionNumber).toBe(2);
    expect(list.data[0].answers.title).toBe('Revised proposal v2');

    // The original revision is frozen + byte-for-byte unchanged.
    const original = await (
      await request.get(`${API}/submissions/${firstSubmissionId}`, { headers: auth })
    ).json();
    expect(original.isCurrent).toBe(false);
    expect(original.answers.title).toBe('Original proposal');

    // And the UI list reflects the current row with a rev badge.
    await login(page);
    await page.goto(tenantUrl(`/forms/${formId}`));
    await page.getByRole('tab', { name: 'Submissions' }).click();
    await expect(page.getByText('rev 2').first()).toBeVisible();
  });
});
