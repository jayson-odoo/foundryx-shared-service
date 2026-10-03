/**
 * sprint-5/14 S0 - red test for the doc-feed Configure dialog (AC-14-91).
 * `doc-feed-config-dialog.tsx` does not exist yet - the dynamic import
 * below fails at runtime, the expected S0 red.
 */
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

// sprint-5/19 - the shared cadence cards format "Next ..." badges through the
// session-bound datetime hook (house mock, same as `schedule-tab.test.tsx`).
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDateTime: (iso: string) => iso }),
}));

function eligibleConnection(over: Record<string, unknown> = {}) {
  return { id: 'conn-1', name: 'db1 open API', book: 'db1', ...over };
}

describe('DocFeedConfigDialog (AC-14-91)', () => {
  it('offers only eligibleConnections in the connection picker', async () => {
    const { DocFeedConfigDialog } = await import('./doc-feed-config-dialog');
    render(
      <DocFeedConfigDialog
        feed="delivery_orders"
        current={{ connectionId: null, mode: 'off', contractGate: null }}
        eligibleConnections={[eligibleConnection()]}
        onClose={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    // The connection picker is a SearchSelect (house convention, see
    // `search-select.test.tsx`) - its options render once opened, same as
    // every other SearchSelect in the codebase.
    fireEvent.click(screen.getByRole('combobox', { name: 'Connection' }));
    expect(screen.getByText(/db1 open api/i)).toBeInTheDocument();
  });

  it('offers Off only until a connection is chosen', async () => {
    const { DocFeedConfigDialog } = await import('./doc-feed-config-dialog');
    render(
      <DocFeedConfigDialog
        feed="delivery_orders"
        current={{ connectionId: null, mode: 'off', contractGate: null }}
        eligibleConnections={[eligibleConnection()]}
        onClose={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    expect(screen.queryByText(/dry run/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^push$/i)).not.toBeInTheDocument();
  });

  it('shows a warning Alert naming the version gap when the contract gate is shut', async () => {
    const { DocFeedConfigDialog } = await import('./doc-feed-config-dialog');
    render(
      <DocFeedConfigDialog
        feed="delivery_orders"
        current={{
          connectionId: 'conn-1', mode: 'off',
          contractGate: { version: 2.6, requiredVersion: 2.7 },
        }}
        eligibleConnections={[eligibleConnection()]}
        onClose={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('2.7');
  });

  it('saves the chosen connection and mode', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const { DocFeedConfigDialog } = await import('./doc-feed-config-dialog');
    render(
      <DocFeedConfigDialog
        feed="delivery_orders"
        current={{ connectionId: 'conn-1', mode: 'off', contractGate: null }}
        eligibleConnections={[eligibleConnection()]}
        onClose={vi.fn()}
        onSave={onSave}
      />,
    );
    await userEvent.click(screen.getByText(/dry run/i));
    await userEvent.click(screen.getByTestId('doc-feed-config-save'));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ connectionId: 'conn-1', mode: 'dry_run' }));
  });

  // ── sprint-5/19 - per-feed schedule (AC-19-11) ──────────────────────────────

  it('renders the Entities cadence cards as Poll + Re-check, prefilled with the defaults', async () => {
    const { DocFeedConfigDialog } = await import('./doc-feed-config-dialog');
    render(
      <DocFeedConfigDialog
        feed="delivery_orders"
        current={{ connectionId: 'conn-1', mode: 'push', contractGate: null }}
        eligibleConnections={[eligibleConnection()]}
        onClose={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    expect(screen.getByText('Poll')).toBeInTheDocument();
    expect(screen.getByText('Re-check')).toBeInTheDocument();
    expect(screen.getByTestId('doc-feed-schedule-incremental-minutes')).toHaveValue(60);
    expect(screen.getByTestId('doc-feed-schedule-reconcile-hours')).toHaveValue(24);
  });

  it('blocks Save below the 1-minute poll floor (the Entities floor, owner Q1)', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const { DocFeedConfigDialog } = await import('./doc-feed-config-dialog');
    render(
      <DocFeedConfigDialog
        feed="delivery_orders"
        current={{ connectionId: 'conn-1', mode: 'push', contractGate: null }}
        eligibleConnections={[eligibleConnection()]}
        onClose={vi.fn()}
        onSave={onSave}
      />,
    );
    const minutes = screen.getByTestId('doc-feed-schedule-incremental-minutes');
    fireEvent.change(minutes, { target: { value: '0' } });
    expect(screen.getByTestId('doc-feed-schedule-incremental-error')).toHaveTextContent('At least 1 minute.');
    expect(screen.getByTestId('doc-feed-config-save')).toBeDisabled();
    expect(onSave).not.toHaveBeenCalled();
  });

  it('saves the edited schedule with the connection and mode', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const { DocFeedConfigDialog } = await import('./doc-feed-config-dialog');
    render(
      <DocFeedConfigDialog
        feed="goods_receive_notes"
        current={{
          connectionId: 'conn-1', mode: 'push', contractGate: null,
          schedule: { incrementalMinutes: 30, reconcileMode: 'interval', reconcileHours: 6, reconcileAt: null },
        }}
        eligibleConnections={[eligibleConnection()]}
        onClose={vi.fn()}
        onSave={onSave}
      />,
    );
    expect(screen.getByTestId('doc-feed-schedule-incremental-minutes')).toHaveValue(30);
    fireEvent.change(screen.getByTestId('doc-feed-schedule-incremental-minutes'), { target: { value: '15' } });
    await userEvent.click(screen.getByTestId('doc-feed-config-save'));
    expect(onSave).toHaveBeenCalledWith({
      connectionId: 'conn-1',
      mode: 'push',
      schedule: { incrementalMinutes: 15, reconcileMode: 'interval', reconcileHours: 6, reconcileAt: null },
      window: { pollBasis: 'last_modified', pollLookbackDays: 1, recheckDays: 45 },
    });
  });

  it('shows a server 422 fieldError on the cadence card and keeps the dialog open', async () => {
    const { ApiError } = await import('@/lib/api-client');
    const onSave = vi.fn().mockRejectedValue(
      new ApiError('Enter the daily reconcile time as HH:MM.', 422, null, {
        fieldErrors: { reconcileHours: 'Server says no.' },
      }),
    );
    const { DocFeedConfigDialog } = await import('./doc-feed-config-dialog');
    render(
      <DocFeedConfigDialog
        feed="delivery_orders"
        current={{ connectionId: 'conn-1', mode: 'push', contractGate: null }}
        eligibleConnections={[eligibleConnection()]}
        onClose={vi.fn()}
        onSave={onSave}
      />,
    );
    await userEvent.click(screen.getByTestId('doc-feed-config-save'));
    expect(await screen.findByTestId('doc-feed-schedule-reconcile-hours-error')).toHaveTextContent('Server says no.');
  });

  // ── DOC-FEED-WINDOW - read window (poll basis / lookback / re-check days) ──

  it('prefills the window with the defaults: LastModified, 1 day back, 45-day re-check', async () => {
    const { DocFeedConfigDialog } = await import('./doc-feed-config-dialog');
    render(
      <DocFeedConfigDialog
        feed="delivery_orders"
        current={{ connectionId: 'conn-1', mode: 'push', contractGate: null }}
        eligibleConnections={[eligibleConnection()]}
        onClose={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    expect(screen.getByTestId('doc-feed-window-basis-last_modified')).toHaveAttribute('data-state', 'on');
    expect(screen.getByTestId('doc-feed-window-lookback-days')).toHaveValue(1);
    expect(screen.getByTestId('doc-feed-window-recheck-days')).toHaveValue(45);
  });

  it('saves an edited window with the rest of the feed', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const { DocFeedConfigDialog } = await import('./doc-feed-config-dialog');
    render(
      <DocFeedConfigDialog
        feed="delivery_orders"
        current={{
          connectionId: 'conn-1', mode: 'push', contractGate: null,
          window: { pollBasis: 'last_modified', pollLookbackDays: 1, recheckDays: 45 },
        }}
        eligibleConnections={[eligibleConnection()]}
        onClose={vi.fn()}
        onSave={onSave}
      />,
    );
    await userEvent.click(screen.getByTestId('doc-feed-window-basis-doc_date'));
    fireEvent.change(screen.getByTestId('doc-feed-window-lookback-days'), { target: { value: '3' } });
    fireEvent.change(screen.getByTestId('doc-feed-window-recheck-days'), { target: { value: '150' } });
    await userEvent.click(screen.getByTestId('doc-feed-config-save'));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        window: { pollBasis: 'doc_date', pollLookbackDays: 3, recheckDays: 150 },
      }),
    );
  });

  it.each([
    ['doc-feed-window-lookback-days', '31', 'Between 0 and 30 days.'],
    ['doc-feed-window-lookback-days', '', 'Between 0 and 30 days.'],
    ['doc-feed-window-recheck-days', '0', 'Between 1 and 180 days.'],
    ['doc-feed-window-recheck-days', '181', 'Between 1 and 180 days.'],
  ])('blocks Save when %s is %s', async (testId, value, message) => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const { DocFeedConfigDialog } = await import('./doc-feed-config-dialog');
    render(
      <DocFeedConfigDialog
        feed="delivery_orders"
        current={{ connectionId: 'conn-1', mode: 'push', contractGate: null }}
        eligibleConnections={[eligibleConnection()]}
        onClose={vi.fn()}
        onSave={onSave}
      />,
    );
    fireEvent.change(screen.getByTestId(testId), { target: { value } });
    expect(screen.getByText(message)).toBeInTheDocument();
    expect(screen.getByTestId('doc-feed-config-save')).toBeDisabled();
  });

  it('shows a server 422 on the window field', async () => {
    const { ApiError } = await import('@/lib/api-client');
    const onSave = vi.fn().mockRejectedValue(
      new ApiError('bad', 422, null, { fieldErrors: { recheckDays: 'Server says no.' } }),
    );
    const { DocFeedConfigDialog } = await import('./doc-feed-config-dialog');
    render(
      <DocFeedConfigDialog
        feed="delivery_orders"
        current={{ connectionId: 'conn-1', mode: 'push', contractGate: null }}
        eligibleConnections={[eligibleConnection()]}
        onClose={vi.fn()}
        onSave={onSave}
      />,
    );
    await userEvent.click(screen.getByTestId('doc-feed-config-save'));
    expect(await screen.findByText('Server says no.')).toBeInTheDocument();
  });
});
