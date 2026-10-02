/**
 * sprint-5/14 S0 - red test for the doc-feed Configure dialog (AC-14-91).
 * `doc-feed-config-dialog.tsx` does not exist yet - the dynamic import
 * below fails at runtime, the expected S0 red.
 */
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

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
    fireEvent.click(screen.getByRole('combobox'));
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

  it('renders the Entities cadence cards as Poll + Deletion sweep, prefilled with the defaults', async () => {
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
    expect(screen.getByText('Deletion sweep')).toBeInTheDocument();
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
    });
  });
});
