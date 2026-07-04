import { expect, test, type Page } from '@playwright/test';
import { expectMailTo } from './helpers/mailbox';

/**
 * Plan sprint-2/04 Phase C — change-email ceremony, full stack.
 *
 * Preconditions (the plan-10 Phase C rig):
 *   - backend :8001 on the plan-04 branch, migrated + seeded
 *   - debug SMTP with a maildir so the spec can READ both ceremony emails:
 *       python -m aiosmtpd -n -l localhost:1025 \
 *         -c aiosmtpd.handlers.Mailbox /tmp/dreamz-e2e-mailbox
 *     (pre-create tmp/new/cur subdirs — the handler doesn't)
 *
 * Spec isolation (methodology §7): the ceremony MUTATES the account email, so
 * everything runs on a DEDICATED tenant provisioned via the operator API
 * (setup only — the flows under test stay real clicks). Timestamped names.
 */
const API = process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8001';

const STAMP = Date.now();
const SLUG = `e2e-acct-${STAMP}`;
// example.com — .test/.invalid TLDs fail the backend EmailStr validation.
const ADMIN_EMAIL = `admin-${STAMP}@example.com`;
const NEW_EMAIL = `renamed-${STAMP}@example.com`;
const CANCEL_EMAIL = `cancelled-${STAMP}@example.com`;
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

/** Real-user navigation: avatar (top-right) → "My Account". */
async function gotoMyAccount(page: Page) {
  await page.getByRole('button', { name: 'User menu' }).click();
  await page.getByRole('menuitem', { name: 'My Account' }).click();
  await expect(page).toHaveURL(/\/account$/);
  // Since plan 06 the page sits on the Resource form shell — the h1 is the
  // USER'S NAME, not "My Account"; the breadcrumb carries the page name.
  await expect(page.locator('h1')).toBeVisible();
}

/** Opens the change-email dialog and submits a request for `newEmail`.
 * Since plan 06 the trigger lives in the form's "…" Actions menu. */
async function requestChange(page: Page, newEmail: string, password: string) {
  await page.getByRole('button', { name: 'Actions' }).click();
  await page.getByRole('menuitem', { name: 'Change email' }).click();
  await page.getByPlaceholder('you@example.com').fill(newEmail);
  await page.getByPlaceholder('Your current password').fill(password);
  await page.getByRole('button', { name: /send approval link/i }).click();
}

// Serial: the ceremony mutates the account email across tests. The timeout
// covers the outbox dispatcher's worst observed delivery lag (~35s) twice —
// the default 30s test timeout loses races against a busy parallel suite.
test.describe.configure({ mode: 'serial', timeout: 120_000 });

test.describe('Change-email ceremony — live stack (plan sprint-2/04 Phase C)', () => {
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
        name: `E2E Account ${STAMP}`,
        slug: SLUG,
        adminName: 'E2E Account Admin',
        adminEmail: ADMIN_EMAIL,
        adminPassword: ADMIN_PASSWORD,
      },
    });
    expect(provision.status()).toBe(201);

    // Tenant SMTP connection → the debug mailbox (so ceremony mail is readable).
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
          fromName: 'Dreamz E2E',
        },
        credentials: {},
      },
    });
    expect(connection.status()).toBe(201);
  });

  test('request shows the pending banner; cancel withdraws it and kills the link', async ({
    page,
  }) => {
    await login(page, ADMIN_EMAIL, ADMIN_PASSWORD);
    await gotoMyAccount(page);

    // Wrong password first — rejected inside the dialog, nothing pending.
    await requestChange(page, CANCEL_EMAIL, 'not-the-password-1!');
    await expect(page.getByText('Incorrect password.')).toBeVisible();

    // Correct password → "check your current inbox" → pending banner.
    await page.getByPlaceholder('Your current password').fill(ADMIN_PASSWORD);
    await page.getByRole('button', { name: /send approval link/i }).click();
    await expect(page.getByText(/check your current inbox/i)).toBeVisible();
    await page.getByRole('button', { name: /got it/i }).click();
    await expect(
      page.getByText(new RegExp(`change to ${CANCEL_EMAIL} awaits approval`, 'i')),
    ).toBeVisible();

    // The approve mail reached the CURRENT mailbox (masked target identifies it).
    const mail = await expectMailTo(ADMIN_EMAIL, 'c***@example.com');
    const match = mail.match(/\/approve-email-change\?token=([A-Za-z0-9_-]+)/);
    expect(match, 'approve email must carry an /approve-email-change link').toBeTruthy();

    // Cancel from the banner — the request is withdrawn…
    await page.getByRole('button', { name: /cancel request/i }).click();
    await expect(page.getByText(/awaits approval/i)).toHaveCount(0);

    // …and the cancelled approve link is dead.
    await page.goto(tenantUrl(`/approve-email-change?token=${match![1]}`));
    await page.getByRole('button', { name: /approve change/i }).click();
    await expect(page.getByRole('heading', { name: /link expired/i })).toBeVisible();
  });

  test('full ceremony: approve from old inbox, verify from new, re-login with new email', async ({
    page,
  }) => {
    await login(page, ADMIN_EMAIL, ADMIN_PASSWORD);
    await gotoMyAccount(page);

    await requestChange(page, NEW_EMAIL, ADMIN_PASSWORD);
    await expect(page.getByText(/check your current inbox/i)).toBeVisible();
    await page.getByRole('button', { name: /got it/i }).click();

    // OLD-side approve — the email link IS the real entry path. The masked
    // target distinguishes this mail from test 1's cancelled request.
    const approveMail = await expectMailTo(ADMIN_EMAIL, 'r***@example.com');
    const approveToken = approveMail.match(
      /\/approve-email-change\?token=([A-Za-z0-9_-]+)/,
    )![1];
    await page.goto(tenantUrl(`/approve-email-change?token=${approveToken}`));
    await expect(
      page.getByRole('heading', { name: /approve email change/i }),
    ).toBeVisible();
    await page.getByRole('button', { name: /approve change/i }).click();
    await expect(page.getByRole('heading', { name: /change approved/i })).toBeVisible();

    // NEW-side verify — this is the step that flips the email.
    const verifyMail = await expectMailTo(NEW_EMAIL);
    const verifyToken = verifyMail.match(
      /\/verify-email-change\?token=([A-Za-z0-9_-]+)/,
    )![1];
    await page.goto(tenantUrl(`/verify-email-change?token=${verifyToken}`));
    await expect(
      page.getByRole('heading', { name: /confirm your new email/i }),
    ).toBeVisible();
    await page.getByRole('button', { name: /confirm new email/i }).click();
    await expect(page.getByRole('heading', { name: /email updated/i })).toBeVisible();

    // Final notice goes to the PREVIOUS address (carries the full new email).
    const notice = await expectMailTo(ADMIN_EMAIL, NEW_EMAIL);
    expect(notice).toContain(NEW_EMAIL);

    // Old email is dead at the door (uniform 401)…
    await page.getByRole('link', { name: /go to sign in/i }).click();
    await page.getByPlaceholder('Your email').fill(ADMIN_EMAIL);
    await page.getByPlaceholder('Your password').fill(ADMIN_PASSWORD);
    await page.getByRole('button', { name: /sign in/i }).click();
    await expect(page.getByText('Invalid email or password.')).toBeVisible();

    // …the NEW email signs in (same password — only the email changed).
    await page.getByPlaceholder('Your email').fill(NEW_EMAIL);
    await page.getByPlaceholder('Your password').fill(ADMIN_PASSWORD);
    await page.getByRole('button', { name: /sign in/i }).click();
    await expect(page).not.toHaveURL(/\/signin/, { timeout: 15_000 });
  });

  test('redeemed ceremony links are single-use', async ({ page }) => {
    // The verify link from the completed ceremony cannot be redeemed twice.
    const verifyMail = await expectMailTo(NEW_EMAIL);
    const verifyToken = verifyMail.match(
      /\/verify-email-change\?token=([A-Za-z0-9_-]+)/,
    )![1];
    await page.goto(tenantUrl(`/verify-email-change?token=${verifyToken}`));
    await page.getByRole('button', { name: /confirm new email/i }).click();
    await expect(page.getByRole('heading', { name: /link expired/i })).toBeVisible();
    await expect(page.getByRole('link', { name: /go to my account/i })).toBeVisible();
  });
});
