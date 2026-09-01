import { expect, test, type Page } from '@playwright/test';

/**
 * Omnichannel Inbox (plan 05) E2E - real user clicks through the menu against
 * the LIVE backend (Phase B: real conversation API + WS). The dev seed
 * (`seed_demo_conversations`) provides deterministic threads cnt-001..cnt-005
 * on a sandbox channel whose dev credentials stub the Graph send.
 * Backend must be bootstrapped (`python -m scripts.bootstrap_db`); demo user
 * is Admin. Tests are self-healing where earlier runs mutate thread state.
 */

async function login(page: Page) {
  await page.goto('/signin');
  await page.getByPlaceholder('Your email').fill('demo@example.com');
  await page.getByPlaceholder('Your password').fill('demo1234');
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));
}

async function openInbox(page: Page) {
  const link = page.getByRole('link', { name: 'Inbox', exact: true });
  if (!(await link.isVisible().catch(() => false))) {
    await page.getByRole('button', { name: 'Omnichannel', exact: true }).click();
    await expect(link).toBeVisible();
  }
  await link.click();
  await page.waitForURL(/\/omnichannel\/inbox$/);
}

test.describe('Omnichannel - Inbox', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await openInbox(page);
  });

  test('thread list loads; opening a thread shows the conversation', async ({ page }) => {
    await expect(page.getByTestId('inbox-shell')).toBeVisible();
    await expect(page.getByTestId('drawer-empty')).toBeVisible();

    await page.getByTestId('thread-row-cnt-001').click();
    await expect(page.getByTestId('drawer-contact-name')).toHaveText('Sarah Chen');
    await expect(page.getByTestId('thread-window')).toContainText('Can I change my booking to Saturday?');
    // Internal note renders as a centered SYSTEM bubble (.first(): the seeded
    // VIP note is oldest; note-test runs add more SYSTEM bubbles over time).
    await expect(page.getByTestId('bubble-system').first()).toContainText('VIP client');
  });

  test('sends a free-form message inside the 24h window and sees the sent tick', async ({ page }) => {
    await page.getByTestId('thread-row-cnt-001').click();
    await expect(page.getByTestId('message-input')).toBeEnabled();

    const text = `Saturday is confirmed - see you! (${Date.now()})`;
    await page.getByTestId('message-input').fill(text);
    await page.getByTestId('message-send').click();

    const bubble = page.getByTestId('bubble-agent').last();
    await expect(bubble).toContainText(text);
    // Real pipeline: SENT immediately; DELIVERED/READ arrive via Meta status
    // webhooks (exercised in pytest), so only the sent tick is deterministic.
    await expect(bubble.getByTestId('tick-sent')).toBeVisible({ timeout: 10_000 });
  });

  test('expired window locks the composer; template re-engages', async ({ page }) => {
    await page.getByTestId('thread-row-cnt-002').click();
    await expect(page.getByTestId('csw-banner')).toBeVisible();
    await expect(page.getByTestId('message-input')).toBeDisabled();

    await page.getByTestId('csw-pick-template').click();
    await page.getByTestId('template-select').click();
    await page.getByRole('option', { name: /booking_update/ }).click();
    await page.getByTestId('template-var-1').fill('Marcus');
    await page.getByTestId('template-var-2').fill('your slot moved to 4pm');
    await expect(page.getByTestId('template-preview')).toContainText('Hi Marcus');
    await page.getByTestId('template-send').click();

    const bubble = page.getByTestId('bubble-agent').last();
    await expect(bubble).toContainText('Hi Marcus');
    await expect(bubble).toContainText('Template');
  });

  test('quick reply inserts into the composer', async ({ page }) => {
    await page.getByTestId('thread-row-cnt-001').click();
    await page.getByTestId('quick-replies').click();
    await page.getByText('Our office hours are Mon-Fri 9am-6pm (MYT).').click();
    await expect(page.getByTestId('message-input')).toHaveValue(
      'Our office hours are Mon-Fri 9am-6pm (MYT).',
    );
  });

  test('adds an internal note from the Activities tab', async ({ page }) => {
    await page.getByTestId('thread-row-cnt-001').click();
    await page.getByTestId('tab-activities').click();

    // Notes bypass the CSW - input enabled even though it is note mode.
    await page.getByTestId('note-input').fill('Customer prefers afternoon calls');
    await page.getByTestId('note-send').click();

    await expect(page.getByTestId('bubble-system').last()).toContainText(
      'Customer prefers afternoon calls',
    );
    // Back on Messages, the note shows inline in the thread.
    await page.getByTestId('tab-messages').click();
    await expect(page.getByTestId('thread-window')).toContainText('Customer prefers afternoon calls');
  });

  test('self-claims an unassigned thread from the Unassigned bucket', async ({ page }) => {
    // Self-heal: a prior run may have claimed cnt-003 - unassign it first.
    await page.getByTestId('thread-row-cnt-003').click();
    await page.getByTestId('assign-trigger').click();
    await expect(page.getByTestId('assign-clear')).toBeVisible();
    await page.getByTestId('assign-clear').click();
    // Let the menu's exit animation finish before re-opening - re-opening over
    // a still-mounted exiting Radix portal detaches the new content mid-click.
    await expect(page.getByTestId('assign-clear')).not.toBeVisible();
    await expect(page.getByTestId('assign-trigger')).toContainText('Unassigned');

    await page.getByTestId('bucket-unassigned').click();
    await expect(page.getByTestId('thread-row-cnt-003')).toBeVisible();

    await page.getByTestId('thread-row-cnt-003').click();
    await page.getByTestId('assign-trigger').click();
    await expect(page.getByTestId('assign-me')).toBeVisible();
    await page.getByTestId('assign-me').click();
    await expect(page.getByTestId('assign-trigger')).toContainText('Demo User');

    // Claimed - it leaves the Unassigned bucket.
    await expect(page.getByTestId('thread-row-cnt-003')).not.toBeVisible();
  });

  test('snoozes and closes a thread; CSW lock note still applies on reopen', async ({ page }) => {
    await page.getByTestId('thread-row-cnt-001').click();
    // Wait for the drawer header to render before probing lifecycle buttons.
    await expect(page.getByTestId('assign-trigger')).toBeVisible();

    // Self-heal: a prior run leaves cnt-001 snoozed/closed - reopen first.
    if (await page.getByTestId('thread-reopen').isVisible().catch(() => false)) {
      await page.getByTestId('thread-reopen').click();
      await expect(page.getByTestId('thread-snooze')).toBeVisible();
    }

    await page.getByTestId('thread-snooze').click();
    await expect(page.getByTestId('thread-reopen')).toBeVisible();

    await page.getByTestId('thread-reopen').click();
    await expect(page.getByTestId('thread-close')).toBeVisible();

    await page.getByTestId('thread-close').click();
    await expect(page.getByTestId('thread-reopen')).toBeVisible();
  });

  test('filters by status and priority', async ({ page }) => {
    await page.getByTestId('filter-status').click();
    await page.getByRole('option', { name: 'Snoozed' }).click();
    await expect(page.getByTestId('thread-row-cnt-004')).toBeVisible();
    await expect(page.getByTestId('thread-row-cnt-001')).not.toBeVisible();

    await page.getByTestId('filter-status').click();
    await page.getByRole('option', { name: 'All statuses' }).click();
    await page.getByTestId('filter-priority').click();
    await page.getByRole('option', { name: 'Urgent' }).click();
    await expect(page.getByTestId('thread-row-cnt-003')).toBeVisible();
    await expect(page.getByTestId('thread-row-cnt-001')).not.toBeVisible();
  });

  test('day separator pills segment the thread by date', async ({ page }) => {
    // cnt-002's history spans ~28h - at least two day groups.
    await page.getByTestId('thread-row-cnt-002').click();
    const pills = page.getByTestId('day-pill');
    await expect(pills.first()).toBeVisible();
    expect(await pills.count()).toBeGreaterThanOrEqual(2);
    await expect(pills.last()).toHaveText(/Today|Yesterday/);
  });

  test('right-click reply quotes the message; send renders the quoted block', async ({ page }) => {
    await page.getByTestId('thread-row-cnt-001').click();

    const target = page.getByTestId('bubble-contact').last(); // "Can I change my booking to Saturday?"
    await target.click({ button: 'right' });
    await page.getByTestId('menu-reply').click();

    await expect(page.getByTestId('reply-strip')).toContainText('Can I change my booking to Saturday?');

    await page.getByTestId('message-input').fill('Yes - moving it now.');
    await page.getByTestId('message-send').click();

    const sent = page.getByTestId('bubble-agent').last();
    await expect(sent).toContainText('Yes - moving it now.');
    await expect(sent.getByTestId('quoted-block')).toContainText('Can I change my booking to Saturday?');
    // Strip cleared after the send.
    await expect(page.getByTestId('reply-strip')).not.toBeVisible();
  });

  test('searches inside a conversation with match navigation', async ({ page }) => {
    await page.getByTestId('thread-row-cnt-002').click();
    await expect(page.getByTestId('thread-window')).toContainText('Confirming Friday 3pm site visit.');

    await page.getByTestId('thread-search-toggle').click();
    await page.getByTestId('thread-search-input').fill('confirm');

    // cnt-002 seed has ≥2 "confirm" hits (Confirming… / Confirmed!).
    await expect(page.getByTestId('thread-search-count')).toContainText('1 /');
    const markCount = await page.locator('[data-testid="thread-window"] mark').count();
    expect(markCount).toBeGreaterThanOrEqual(2);

    // Step older, then close clears highlights.
    await page.getByTestId('thread-search-prev').click();
    await expect(page.getByTestId('thread-search-count')).toContainText('2 /');
    await page.getByTestId('thread-search-close').click();
    await expect(page.getByTestId('thread-search-bar')).not.toBeVisible();
    expect(await page.locator('[data-testid="thread-window"] mark').count()).toBe(0);
  });

  test('right-click copy puts the message text on the clipboard', async ({ page, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    await page.getByTestId('thread-row-cnt-001').click();

    await page.getByTestId('bubble-contact').first().click({ button: 'right' });
    await page.getByTestId('menu-copy').click();

    const copied = await page.evaluate(() => navigator.clipboard.readText());
    expect(copied).toBe('Hi! I booked the Grand Ballroom for Friday.');
  });
});
