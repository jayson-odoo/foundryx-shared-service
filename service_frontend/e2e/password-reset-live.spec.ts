import { expect, test } from '@playwright/test';
import { expectMailTo } from './helpers/mailbox';

/**
 * Plan 10 Phase C - full-stack forgot-password + throttle E2E.
 *
 * Preconditions (matches the plan-09 Phase C rig):
 *   - backend :8001 on the plan-10 branch, seeded (platform@example.com)
 *   - debug SMTP with a maildir so the spec can READ the reset email:
 *       python -m aiosmtpd -n -l localhost:1025 \
 *         -c aiosmtpd.handlers.Mailbox /tmp/foundryx-e2e-mailbox
 *
 * Spec isolation (methodology §7): login throttling + password changes MUTATE
 * state, so everything runs on a DEDICATED tenant provisioned via the operator
 * API (setup only - the flows under test stay real clicks). Names are
 * timestamped; e2e-* tenants are residue until BL-035.
 */
const API = process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8001';

const STAMP = Date.now();
const SLUG = `e2e-reset-${STAMP}`;
// example.com - .test/.invalid TLDs fail the backend EmailStr validation.
const ADMIN_EMAIL = `admin-${STAMP}@example.com`;
const ADMIN_PASSWORD = 'E2eStart1!';
const NEW_PASSWORD = 'E2eFresh2@';

const UNIFORM_MESSAGE =
  'If an account exists for this email, a reset link has been sent.';

function tenantUrl(pathname: string): string {
  return `http://${SLUG}.localhost:3001${pathname}`;
}


// Timeout covers the shared expectMailTo's worst-case dispatcher lag (~35s
// observed) - the default 30s test timeout loses races under a parallel suite.
test.describe.configure({ mode: 'serial', timeout: 120_000 });

test.describe('Forgot password - live stack (plan 10 Phase C)', () => {
  test.beforeAll(async ({ request }) => {
    // Operator provisions the dedicated tenant (plan 07 §7).
    const platformLogin = await request.post(`${API}/auth/login`, {
      data: {
        email: 'platform@example.com',
        password: 'platform1234',
        tenantSlug: 'platform',
      },
    });
    expect(platformLogin.ok()).toBeTruthy();
    const platformToken = (await platformLogin.json()).access_token;

    const provision = await request.post(`${API}/platform/tenants`, {
      headers: { Authorization: `Bearer ${platformToken}` },
      data: {
        name: `E2E Reset ${STAMP}`,
        slug: SLUG,
        adminName: 'E2E Admin',
        adminEmail: ADMIN_EMAIL,
        adminPassword: ADMIN_PASSWORD,
      },
    });
    expect(provision.status()).toBe(201);

    // Tenant SMTP connection → the debug mailbox (so reset mail is readable).
    const adminLogin = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD, tenantSlug: SLUG },
    });
    expect(adminLogin.ok()).toBeTruthy();
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
          fromName: 'Foundryx E2E',
        },
        credentials: {},
      },
    });
    expect(connection.status()).toBe(201);
  });

  test('forgot → email arrives → redeem → old password dead, new works', async ({
    page,
  }) => {
    // Real clicks: signin → "Forgot Password?" → request a link.
    await page.goto(tenantUrl('/signin'));
    await page.getByRole('link', { name: /forgot password/i }).click();
    // Both pages have a "Your email" field - anchor on the reset heading so
    // the fill can't race the navigation and land on the signin form.
    await expect(
      page.getByRole('heading', { name: /forgot your password/i }),
    ).toBeVisible();
    await page.getByPlaceholder('Your email').fill(ADMIN_EMAIL);
    await page.getByRole('button', { name: /send reset link/i }).click();
    await expect(page.getByText(UNIFORM_MESSAGE)).toBeVisible();

    // Mailbox assertion: the outbox dispatcher delivers via the debug SMTP.
    const mail = await expectMailTo(ADMIN_EMAIL);
    const match = mail.match(/\/change-password\?token=([A-Za-z0-9_-]+)/);
    expect(match, 'reset email must carry a /change-password link').toBeTruthy();

    // The email link IS the real entry path to the redeem page.
    await page.goto(tenantUrl(`/change-password?token=${match![1]}`));
    await page
      .getByPlaceholder('Your new password', { exact: true })
      .fill(NEW_PASSWORD);
    await page.getByPlaceholder('Confirm your new password').fill(NEW_PASSWORD);
    await page.getByRole('button', { name: /reset password/i }).click();
    await expect(
      page.getByRole('heading', { name: /password updated/i }),
    ).toBeVisible();
    await page.getByRole('link', { name: /go to sign in/i }).click();

    // Old password rejected…
    await page.getByPlaceholder('Your email').fill(ADMIN_EMAIL);
    await page.getByPlaceholder('Your password').fill(ADMIN_PASSWORD);
    await page.getByRole('button', { name: /sign in/i }).click();
    await expect(page.getByText('Invalid email or password.')).toBeVisible();

    // …new password lands on the dashboard.
    await page.getByPlaceholder('Your password').fill(NEW_PASSWORD);
    await page.getByRole('button', { name: /sign in/i }).click();
    await expect(page).not.toHaveURL(/\/signin/, { timeout: 15_000 });
  });

  test('used reset link cannot be redeemed twice (single-use)', async ({ page }) => {
    const mail = await expectMailTo(ADMIN_EMAIL);
    const token = mail.match(/\/change-password\?token=([A-Za-z0-9_-]+)/)![1];

    await page.goto(tenantUrl(`/change-password?token=${token}`));
    await page
      .getByPlaceholder('Your new password', { exact: true })
      .fill('E2eAgain3#');
    await page.getByPlaceholder('Confirm your new password').fill('E2eAgain3#');
    await page.getByRole('button', { name: /reset password/i }).click();

    await expect(
      page.getByRole('heading', { name: /link expired/i }),
    ).toBeVisible();
    await expect(
      page.getByRole('link', { name: /request a new link/i }),
    ).toBeVisible();
  });

  test('6 rapid bad logins lock the account with a distinct throttle message', async ({
    page,
  }) => {
    await page.goto(tenantUrl('/signin'));
    for (let i = 0; i < 5; i += 1) {
      await page.getByPlaceholder('Your email').fill(ADMIN_EMAIL);
      await page.getByPlaceholder('Your password').fill(`wrong-pass-${i}!`);
      await page.getByRole('button', { name: /sign in/i }).click();
      await expect(page.getByText('Invalid email or password.')).toBeVisible();
    }

    // 6th attempt - even with the CORRECT password - is throttled (429),
    // and the message is deliberately distinct from invalid-credentials.
    await page.getByPlaceholder('Your email').fill(ADMIN_EMAIL);
    await page.getByPlaceholder('Your password').fill(NEW_PASSWORD);
    await page.getByRole('button', { name: /sign in/i }).click();
    await expect(page.getByText(/too many attempts/i)).toBeVisible();
  });
});
