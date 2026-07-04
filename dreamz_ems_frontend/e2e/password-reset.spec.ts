import { expect, test } from '@playwright/test';

/**
 * Forgot/change-password E2E (plan 10 §3, Phase A) — real user clicks.
 * The request flow is reached by clicking "Forgot Password?" on signin (real
 * users don't know URLs); the redeem page is entered via a tokened URL because
 * that IS the real entry path (the link in the reset email).
 *
 * Phase A runs against the mock password service (knobs: email containing
 * `throttled` → 429; token containing `expired` → invalid-token). Phase B
 * swaps the service to the real backend; the click-flow assertions stay.
 */
const UNIFORM_MESSAGE =
  'If an account exists for this email, a reset link has been sent.';

test.describe('Forgot password (request)', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/signin');
    await page.getByRole('link', { name: /forgot password/i }).click();
    await expect(
      page.getByRole('heading', { name: /forgot your password/i }),
    ).toBeVisible();
  });

  test('blocks an invalid email client-side', async ({ page }) => {
    await page.getByPlaceholder('Your email').fill('not-an-email');
    await page.getByRole('button', { name: /send reset link/i }).click();
    await expect(
      page.getByText(/please enter a valid email address/i),
    ).toBeVisible();
  });

  test('shows the uniform confirmation for an existing account', async ({
    page,
  }) => {
    await page.getByPlaceholder('Your email').fill('demo@example.com');
    await page.getByRole('button', { name: /send reset link/i }).click();
    await expect(page.getByText(UNIFORM_MESSAGE)).toBeVisible();
  });

  test('shows the SAME confirmation for an unknown account (enumeration-safe)', async ({
    page,
  }) => {
    await page
      .getByPlaceholder('Your email')
      .fill(`nobody-${Date.now()}@example.com`);
    await page.getByRole('button', { name: /send reset link/i }).click();
    await expect(page.getByText(UNIFORM_MESSAGE)).toBeVisible();
  });

  test('returns to signin via "Back to Sign In"', async ({ page }) => {
    await page.getByRole('link', { name: /back to sign in/i }).click();
    await expect(page).toHaveURL(/\/signin$/);
  });
});

test.describe('Change password (redeem)', () => {
  test('shows the expired-link state without a token and offers a new link', async ({
    page,
  }) => {
    // No token = how a user lands if the URL got truncated; the page must not
    // render a dead form.
    await page.goto('/change-password');
    await expect(
      page.getByRole('heading', { name: /link expired/i }),
    ).toBeVisible();
    await page.getByRole('link', { name: /request a new link/i }).click();
    await expect(page).toHaveURL(/\/reset-password$/);
  });

  test('enforces the password policy client-side', async ({ page }) => {
    await page.goto('/change-password?token=e2e-valid-token');
    await page
      .getByPlaceholder('Your new password', { exact: true })
      .fill('weakpass');
    await page.getByPlaceholder('Confirm your new password').fill('weakpass');
    await page.getByRole('button', { name: /reset password/i }).click();
    await expect(
      page.getByText(/must contain at least one uppercase letter/i),
    ).toBeVisible();
  });

  test('blocks mismatched confirmation', async ({ page }) => {
    await page.goto('/change-password?token=e2e-valid-token');
    await page
      .getByPlaceholder('Your new password', { exact: true })
      .fill('NewPass1!');
    await page.getByPlaceholder('Confirm your new password').fill('Other1!aa');
    await page.getByRole('button', { name: /reset password/i }).click();
    await expect(page.getByText(/passwords do not match/i)).toBeVisible();
  });
});

test.describe('Parked signup (plan 10 D3)', () => {
  // notFound() from a client component renders the not-found boundary (the
  // HTTP status of the prerendered shell stays 200) — assert the UI.
  test('/signup renders not-found while signup is disabled', async ({
    page,
  }) => {
    await page.goto('/signup');
    await expect(page.getByText(/could not be found/i)).toBeVisible();
    await expect(page.getByPlaceholder('Your email')).toHaveCount(0);
  });

  test('/verify-email renders not-found while signup is disabled', async ({
    page,
  }) => {
    await page.goto('/verify-email');
    await expect(page.getByText(/could not be found/i)).toBeVisible();
  });
});
