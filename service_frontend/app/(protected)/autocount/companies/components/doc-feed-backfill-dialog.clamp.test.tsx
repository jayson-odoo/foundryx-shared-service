/**
 * sprint-5/14 round 2 (N-3) - a live range of exactly the floor day, after
 * the full history is done, is clamped to a valid range (to never before
 * from). The picker is stubbed so the test can hand the dialog that exact
 * range without driving the calendar popover.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/components/platform/date-range-picker', () => ({
  DateRangePicker: ({ onChange }: { onChange: (v: { preset: 'custom'; from: string; to: string }) => void }) => (
    <button
      type="button"
      data-testid="pick-floor-day"
      onClick={() => onChange({ preset: 'custom', from: '2023-01-01', to: '2023-01-01' })}
    >
      pick
    </button>
  ),
}));

describe('DocFeedBackfillDialog range clamp (N-3)', () => {
  it('a one-day floor range on a live backfill after full done never ends before it starts', async () => {
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
    await userEvent.click(screen.getByTestId('pick-floor-day'));
    await userEvent.click(screen.getByTestId('backfill-dry-run-switch'));
    await userEvent.click(screen.getByTestId('backfill-start'));
    expect(onStart).toHaveBeenCalledWith({ dryRun: false, fromDay: '2023-01-02', toDay: '2023-01-02' });
  });
});
