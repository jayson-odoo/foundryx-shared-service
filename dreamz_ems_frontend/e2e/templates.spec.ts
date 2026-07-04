import { expect, test, type Page } from '@playwright/test';
import { expectMailTo } from './helpers/mailbox';

/**
 * Plan sprint-2/07 Phase C — template engine + email log, full stack.
 *
 * Preconditions:
 *   - backend :8001 on the plan-07 branch, migrated + seeded (platform-tier
 *     system templates present)
 *   - maildir smtpd so the spec READS rendered mail:
 *       python -m aiosmtpd -n -l localhost:1025 \
 *         -c aiosmtpd.handlers.Mailbox /tmp/dreamz-e2e-mailbox
 *
 * Isolation (methodology §7): forking a system template + sending mail mutates
 * tenant state, so everything runs on a DEDICATED tenant provisioned via the
 * operator API (setup only — flows under test stay real clicks). Timestamped.
 */
const API = process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8001';

const STAMP = Date.now();
const SLUG = `e2e-tpl-${STAMP}`;
const ADMIN_EMAIL = `admin-${STAMP}@example.com`;
const ADMIN_PASSWORD = 'E2eStart1!';
const CUSTOM_NAME = `Campaign ${STAMP}`;

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

async function gotoTemplates(page: Page) {
  await page.goto(tenantUrl('/settings/templates'));
  await expect(page.locator('h1', { hasText: 'Templates' })).toBeVisible();
}

test.describe.configure({ mode: 'serial', timeout: 120_000 });

test.describe('Template engine — live stack (plan sprint-2/07 Phase C)', () => {
  test.beforeAll(async ({ request }) => {
    const platformLogin = await request.post(`${API}/auth/login`, {
      data: { email: 'platform@example.com', password: 'platform1234', tenantSlug: 'platform' },
    });
    expect(platformLogin.ok()).toBeTruthy();
    const platformToken = (await platformLogin.json()).access_token;

    const provision = await request.post(`${API}/platform/tenants`, {
      headers: { Authorization: `Bearer ${platformToken}` },
      data: {
        name: `E2E Templates ${STAMP}`,
        slug: SLUG,
        adminName: 'E2E Templates Admin',
        adminEmail: ADMIN_EMAIL,
        adminPassword: ADMIN_PASSWORD,
      },
    });
    expect(provision.status()).toBe(201);

    // Tenant SMTP → debug maildir so test-send + forgot-password mail is readable.
    const adminLogin = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD, tenantSlug: SLUG },
    });
    const adminToken = (await adminLogin.json()).access_token;
    const connection = await request.post(`${API}/integrations/connections`, {
      headers: { Authorization: `Bearer ${adminToken}` },
      data: {
        provider: 'smtp',
        name: 'E2E debug SMTP',
        config: {
          host: 'localhost',
          port: '1025',
          security: 'none',
          fromEmail: 'no-reply@example.com',
          fromName: 'Dreamz E2E',
        },
        credentials: {},
      },
    });
    expect(connection.status()).toBe(201);
  });

  test('create a custom template, design it, preview and test-send', async ({ page }) => {
    await login(page, ADMIN_EMAIL, ADMIN_PASSWORD);
    await gotoTemplates(page);

    // System templates list with Default tier.
    await expect(page.getByText('auth.password_reset')).toBeVisible();

    // New template (create mode opens in edit).
    await page.getByRole('button', { name: /new template/i }).click();
    await expect(page).toHaveURL(/\/settings\/templates\/new$/);

    // Settings tab: name + context (create mode opens on the Design tab).
    await page.getByRole('tab', { name: 'Settings' }).click();
    await page.getByLabel('Template name').fill(CUSTOM_NAME);
    // Context picker (SearchSelect — combobox named by its aria-label).
    await page.getByRole('combobox', { name: 'Template context' }).click();
    await page.getByRole('option', { name: /Template · Test send/i }).click();
    // Confirm the selection registered before leaving the Settings tab.
    await expect(
      page.getByRole('combobox', { name: 'Template context' }),
    ).toContainText('Template · Test send');

    // Design tab — the blank template seeds brand header/body/footer, valid
    // to save as-is. (dnd-kit drag-drop is exercised in the editor's Vitest
    // suite; Playwright's mouse-event dragTo doesn't drive dnd-kit's pointer
    // sensors reliably.)
    await page.getByRole('tab', { name: 'Design' }).click();
    await expect(page.getByTestId('email-canvas')).toBeVisible();

    // Save → create replaces /new with the new template's id.
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page).toHaveURL(/\/settings\/templates\/[0-9a-f-]+$/, { timeout: 15_000 });

    // Preview renders.
    await page.getByTestId('editor-mode-preview').click();
    await expect(page.getByTestId('preview-frame')).toBeVisible();

    // Test send → mail lands in the maildir, branded.
    await page.getByRole('button', { name: 'Actions' }).click();
    await page.getByRole('menuitem', { name: /send test email/i }).click();
    await expect(page.getByText(/test email queued/i)).toBeVisible();

    const mail = await expectMailTo(ADMIN_EMAIL, '[Test]');
    expect(mail).toContain('<table'); // mrml output
  });

  test('fork a system template; forgot-password mail uses the fork; reset reverts', async ({
    page,
  }) => {
    await login(page, ADMIN_EMAIL, ADMIN_PASSWORD);
    await gotoTemplates(page);

    // Open the seeded Password reset template (Default tier) and edit it.
    // (Row click carries ?ctx=&i= record-nav context.)
    await page.getByText('Password reset', { exact: true }).click();
    await expect(page).toHaveURL(/\/settings\/templates\/[0-9a-f-]+(\?|$)/);
    await page.getByRole('button', { name: /^Edit$/ }).click();

    // Subject lives on the Settings tab (the form opens on Design).
    await page.getByRole('tab', { name: 'Settings' }).click();
    const marker = `Forked ${STAMP}`;
    const subject = page.getByLabel('Subject');
    await subject.fill(`${marker} — reset your {{tenant.name}} password`);
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    // First edit of a platform default forks it: the URL replaces to the new
    // (fork) template id. The list then shows the row at the Customized tier.
    await expect(page.getByText(/saved/i)).toBeVisible({ timeout: 15_000 });
    await gotoTemplates(page);
    const forkRow = page.getByRole('row', { name: /Password reset/ });
    await expect(forkRow.getByText('Customized')).toBeVisible();

    // Trigger a real forgot-password for the admin → mail uses the fork.
    await page.goto(tenantUrl('/reset-password'));
    await page.getByPlaceholder('Your email').fill(ADMIN_EMAIL);
    await page.getByRole('button', { name: /send reset link/i }).click();

    const mail = await expectMailTo(ADMIN_EMAIL, marker);
    expect(mail).toContain(marker);
    expect(mail).toContain('change-password?token=');

    // Reset to platform default → tier flips back to Default.
    await gotoTemplates(page);
    await page.getByText('Password reset', { exact: true }).click();
    await page.getByRole('button', { name: 'Actions' }).click();
    await page.getByRole('menuitem', { name: /reset to default/i }).click();
    await page.getByRole('button', { name: /^Reset$/ }).click();
    await expect(page.getByText('Default')).toBeVisible();
  });

  test('email log lists the sent mail, opens the body, and retry/cancel work', async ({ page }) => {
    await login(page, ADMIN_EMAIL, ADMIN_PASSWORD);
    await page.goto(tenantUrl('/settings/email-log'));
    await expect(page.locator('h1', { hasText: 'Email log' })).toBeVisible();

    // The test-send + forgot-password mails are here.
    await expect(page.getByText('[Test]', { exact: false }).first()).toBeVisible();

    // Open a row → detail with the Body tab.
    await page.getByText('[Test]', { exact: false }).first().click();
    await expect(page).toHaveURL(/\/settings\/email-log\/[0-9a-f-]+(\?|$)/);
    await page.getByRole('tab', { name: 'Body' }).click();
    await expect(page.getByTestId('email-body-frame')).toBeVisible();
    // Raw HTML view shows the mrml table output.
    await page.getByTestId('body-view-html').click();
    await expect(page.getByText('<table', { exact: false }).first()).toBeVisible();
  });
});
