import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { AutocountEntityConfig } from '@/types/autocount';

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    formatDate: (v: string) => v,
    formatDateTime: (v: string) => v,
    formatTime: (v: string) => v,
  }),
}));

const { EntityLookbackDialog } = await import('./entity-lookback-dialog');

function entity(over: Partial<AutocountEntityConfig> = {}): AutocountEntityConfig {
  return {
    id: 'e1',
    entityType: 'goods_received_note',
    syncMode: 'SCHEDULED_REVIEW',
    sourceImpl: 'autocount_read',
    recordCap: 200,
    initialLookbackDays: 30,
    enabled: true,
    lastSuccessAt: null,
    lastAttemptAt: null,
    watermarkAt: null,
    consecutiveFailures: 0,
    lastError: null,
    etlStatus: 'draft',
    ...over,
  };
}

describe('first-run window dialog', () => {
  it('saves a valid whole number of days', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <EntityLookbackDialog entity={entity()} onClose={vi.fn()} onSave={onSave} />,
    );

    const input = screen.getByTestId('lookback-days');
    expect(input).toHaveValue(30);

    await userEvent.clear(input);
    await userEvent.type(input, '365');
    await userEvent.click(screen.getByTestId('save-lookback'));

    expect(onSave).toHaveBeenCalledWith('goods_received_note', 365);
  });

  it('refuses nonsense rather than coercing it', async () => {
    const onSave = vi.fn();
    render(
      <EntityLookbackDialog entity={entity()} onClose={vi.fn()} onSave={onSave} />,
    );

    const input = screen.getByTestId('lookback-days');
    await userEvent.clear(input);
    await userEvent.type(input, '0');

    expect(screen.getByTestId('lookback-error')).toBeInTheDocument();
    expect(screen.getByTestId('save-lookback')).toBeDisabled();
    await userEvent.click(screen.getByTestId('save-lookback'));
    expect(onSave).not.toHaveBeenCalled();
  });

  it('locks the field once a sync position exists', async () => {
    // Widening the window after a watermark exists would be a guaranteed no-op
    // (the backend's watermark wins), and an edit that provably does nothing is
    // the foolproof-UI violation. The established position is shown instead.
    render(
      <EntityLookbackDialog
        entity={entity({ watermarkAt: '2026-07-12T12:00:00Z' })}
        onClose={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    expect(screen.getByTestId('lookback-days')).toBeDisabled();
    expect(screen.getByTestId('save-lookback')).toBeDisabled();
    expect(screen.getByTestId('lookback-superseded')).toHaveTextContent(
      '2026-07-12T12:00:00Z',
    );
  });

  it('renders nothing when no entity is selected', () => {
    render(<EntityLookbackDialog entity={null} onClose={vi.fn()} onSave={vi.fn()} />);
    expect(screen.queryByTestId('lookback-days')).not.toBeInTheDocument();
  });
});
