/**
 * sprint-5/14 S0 - red test for the Backfill dialog (AC-14-93).
 * `doc-feed-backfill-dialog.tsx` does not exist yet - the dynamic import
 * fails at runtime, the expected S0 red.
 *
 * N5 (review round 1) - the date range now renders through the shared
 * `DateRangePicker` (plan 30 roster), not two bare `<Input type="date">`;
 * the default "to" is MYT "today" (fixed UTC+8, D6), never the browser's
 * local/UTC date - these tests freeze system time near MYT midnight to pin
 * that distinction.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    formatDate: (v: string) => v,
    formatDateTime: (v: string) => v,
    formatTime: (v: string) => v,
  }),
}));

afterEach(() => {
  vi.useRealTimers();
});

describe('DocFeedBackfillDialog (AC-14-93)', () => {
  it('defaults the date range to 2023-01-01 through MYT today, not the browser/UTC date', async () => {
    // 2026-03-10T20:00:00Z is 2026-03-11 04:00 in MYT (UTC+8) - a moment
    // where the browser/UTC calendar date and the MYT one already differ.
    // No `userEvent` interaction here (Radix's real pointer sequence does
    // not mix reliably with `vi.useFakeTimers()`, house precedent) - the
    // default range is asserted straight off the picker's own rendered
    // label, no click required.
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-03-10T20:00:00Z'));
    const { DocFeedBackfillDialog } = await import('./doc-feed-backfill-dialog');
    render(<DocFeedBackfillDialog feed="delivery_orders" mode="push" fullBackfillDoneAt={null} backfill={null} onClose={vi.fn()} onStart={vi.fn()} onStop={vi.fn()} />);

    expect(screen.getByText('1 Jan - 11 Mar')).toBeInTheDocument();
  });

  it('has a Dry run switch, on by default', async () => {
    const { DocFeedBackfillDialog } = await import('./doc-feed-backfill-dialog');
    render(<DocFeedBackfillDialog feed="delivery_orders" mode="push" fullBackfillDoneAt={null} backfill={null} onClose={vi.fn()} onStart={vi.fn()} onStop={vi.fn()} />);
    expect(screen.getByTestId('backfill-dry-run-switch')).toBeChecked();
  });

  it('starts a backfill with the chosen range and dry-run flag', async () => {
    const onStart = vi.fn().mockResolvedValue(undefined);
    const { DocFeedBackfillDialog } = await import('./doc-feed-backfill-dialog');
    render(<DocFeedBackfillDialog feed="delivery_orders" mode="push" fullBackfillDoneAt={null} backfill={null} onClose={vi.fn()} onStart={onStart} onStop={vi.fn()} />);
    await userEvent.click(screen.getByTestId('backfill-start'));
    expect(onStart).toHaveBeenCalledWith(expect.objectContaining({ dryRun: true }));
  });

  it('shows JobProgress in days with a Stop control while a backfill is running', async () => {
    const { DocFeedBackfillDialog } = await import('./doc-feed-backfill-dialog');
    render(
      <DocFeedBackfillDialog
        feed="delivery_orders"
        mode="push"
        fullBackfillDoneAt={null}
        backfill={{ status: 'running', daysDone: 4, daysTotal: 1368, dryRun: true }}
        onClose={vi.fn()}
        onStart={vi.fn()}
        onStop={vi.fn()}
      />,
    );
    expect(screen.getByTestId('job-progress-label')).toHaveTextContent('day 4 of 1368');
    expect(screen.getByRole('button', { name: /stop/i })).toBeInTheDocument();
  });

  // RS2 (review round 2) - only offer what will work.
  it('locks Dry run on (disabled, checked) when the feed is not in Push mode, and starts a dry run', async () => {
    const onStart = vi.fn().mockResolvedValue(undefined);
    const { DocFeedBackfillDialog } = await import('./doc-feed-backfill-dialog');
    render(
      <DocFeedBackfillDialog
        feed="delivery_orders"
        mode="dry_run"
        fullBackfillDoneAt={null}
        backfill={null}
        onClose={vi.fn()}
        onStart={onStart}
        onStop={vi.fn()}
      />,
    );
    const toggle = screen.getByTestId('backfill-dry-run-switch');
    expect(toggle).toBeChecked();
    expect(toggle).toBeDisabled();
    await userEvent.click(screen.getByTestId('backfill-start'));
    expect(onStart).toHaveBeenCalledWith(expect.objectContaining({ dryRun: true }));
  });

  it('lets a Push-mode feed switch Dry run off', async () => {
    const { DocFeedBackfillDialog } = await import('./doc-feed-backfill-dialog');
    render(
      <DocFeedBackfillDialog
        feed="delivery_orders"
        mode="push"
        fullBackfillDoneAt={null}
        backfill={null}
        onClose={vi.fn()}
        onStart={vi.fn()}
        onStop={vi.fn()}
      />,
    );
    expect(screen.getByTestId('backfill-dry-run-switch')).toBeEnabled();
  });

  it('a live backfill after the full history completed starts the day after the floor, never at it', async () => {
    const onStart = vi.fn().mockResolvedValue(undefined);
    const { DocFeedBackfillDialog } = await import('./doc-feed-backfill-dialog');
    render(
      <DocFeedBackfillDialog
        feed="delivery_orders"
        mode="push"
        fullBackfillDoneAt="2026-09-01T00:00:00Z"
        backfill={null}
        onClose={vi.fn()}
        onStart={onStart}
        onStop={vi.fn()}
      />,
    );
    // Dry run (default) may still cover the full history.
    await userEvent.click(screen.getByTestId('backfill-start'));
    expect(onStart).toHaveBeenLastCalledWith(expect.objectContaining({ dryRun: true, fromDay: '2023-01-01' }));

    await userEvent.click(screen.getByTestId('backfill-dry-run-switch'));
    await userEvent.click(screen.getByTestId('backfill-start'));
    expect(onStart).toHaveBeenLastCalledWith(expect.objectContaining({ dryRun: false, fromDay: '2023-01-02' }));
  });
});
