import { expect, test } from '@playwright/test';

/**
 * Sign-in E2E - real user clicks against the live stack
 * (NextAuth → FastAPI :8001). Requires the backend up + seeded
 * (`python -m scripts.init_db`). Drives the UI; never URL-jumps into
 * protected areas.
 */
test.describe('Sign-in', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/signin');
    await expect(
      page.getByRole('heading', { name: /welcome to foundryx ems/i }),
    ).toBeVisible();
  });

  test('shows the sign-in form', async ({ page }) => {
    // Form only - EVERY brand-panel element (slogan, logo, illustration) is
    // tenant-configurable since sprint-2/03 (a branded tenant may clear any
    // of them), so the spec must not assert specific branding content.
    await expect(page.getByPlaceholder('Your email')).toBeVisible();
    await expect(page.getByPlaceholder('Your password')).toBeVisible();
    await expect(page.getByRole('button', { name: /sign in/i })).toBeVisible();
  });

  test('blocks empty submit with a validation message', async ({ page }) => {
    await page.getByRole('button', { name: /sign in/i }).click();
    await expect(
      page.getByText(/please enter a valid email address/i),
    ).toBeVisible();
  });

  test('rejects wrong credentials with a generic error', async ({ page }) => {
    await page.getByPlaceholder('Your email').fill('demo@example.com');
    await page.getByPlaceholder('Your password').fill('definitely-wrong');
    await page.getByRole('button', { name: /sign in/i }).click();

    await expect(page.getByText('Invalid email or password.')).toBeVisible();
    await expect(page).toHaveURL(/\/signin$/); // no creds leaked to URL
  });

  test('logs in with seeded credentials and lands on the dashboard', async ({
    page,
  }) => {
    await page.getByPlaceholder('Your email').fill('demo@example.com');
    await page.getByPlaceholder('Your password').fill('demo1234');
    await page.getByRole('button', { name: /sign in/i }).click();

    await expect(page).toHaveURL(/localhost:\d+\/(?:$|\?)/, { timeout: 15_000 });
    await expect(page).not.toHaveURL(/\/signin/);
  });

  test('toggles password visibility', async ({ page }) => {
    const password = page.getByPlaceholder('Your password');
    await password.fill('secret123');
    await expect(password).toHaveAttribute('type', 'password');
    await page.getByRole('button', { name: /show password/i }).click();
    await expect(password).toHaveAttribute('type', 'text');
  });

  test('hides "Create an Account" while signup is disabled (plan 10 D3)', async ({
    page,
  }) => {
    await expect(
      page.getByRole('link', { name: /create an account/i }),
    ).toHaveCount(0);
  });

  test('shows the Remember me checkbox, unchecked by default', async ({
    page,
  }) => {
    const checkbox = page.getByRole('checkbox', { name: /remember me/i });
    await expect(checkbox).toBeVisible();
    await expect(checkbox).not.toBeChecked();
  });

  test('navigates to reset via "Forgot Password?"', async ({ page }) => {
    await page.getByRole('link', { name: /forgot password/i }).click();
    await expect(page).toHaveURL(/\/reset-password$/);
  });
});
