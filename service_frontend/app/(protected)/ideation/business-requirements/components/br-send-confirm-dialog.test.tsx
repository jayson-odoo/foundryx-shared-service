import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { BrSendConfirmDialog } from './br-send-confirm-dialog';

const props = (over: Partial<React.ComponentProps<typeof BrSendConfirmDialog>> = {}) => ({
  open: true,
  repo: 'jayson-odoo/sorento-crm',
  ideaCount: 3,
  fieldsComplete: { done: 6, total: 6 },
  pending: false,
  onCancel: vi.fn(),
  onConfirm: vi.fn(),
  ...over,
});

describe('BrSendConfirmDialog (AC-STB-08)', () => {
  it('AC-STB-08 shows the title, repository, idea count and fields complete', () => {
    render(<BrSendConfirmDialog {...props()} />);
    expect(screen.getByText('Send to build?')).toBeInTheDocument();
    expect(screen.getByText(/jayson-odoo\/sorento-crm/)).toBeInTheDocument();
    expect(screen.getByText(/3/)).toBeInTheDocument();
    expect(screen.getByText(/6 of 6 complete/)).toBeInTheDocument();
  });

  it('AC-STB-08 Cancel fires onCancel; Send to build fires onConfirm once', () => {
    const p = props();
    render(<BrSendConfirmDialog {...p} />);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(p.onCancel).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Send to build' }));
    expect(p.onConfirm).toHaveBeenCalledTimes(1);
  });

  it('AC-STB-08 Confirm is disabled while pending', () => {
    render(<BrSendConfirmDialog {...props({ pending: true })} />);
    expect(screen.getByRole('button', { name: /Send to build/ })).toBeDisabled();
  });

  it('AC-STB-08 renders nothing when closed', () => {
    render(<BrSendConfirmDialog {...props({ open: false })} />);
    expect(screen.queryByText('Send to build?')).not.toBeInTheDocument();
  });
});
