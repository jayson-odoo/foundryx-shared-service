/** AC-IVE-30/48 - Close disabled until a reason is chosen, note optional, 422 mapping. */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api-client';
import type { CloseReason } from '@/types/omnichannel';
import { CloseThreadDialog } from './close-thread-dialog';

const REASONS: CloseReason[] = [
  { id: 'cr-1', workspaceId: 'wsp-001', name: 'General Inquiry', sortOrder: 0, isActive: true, usesCount: 1, createdAt: '2026-01-01T00:00:00Z' },
  { id: 'cr-2', workspaceId: 'wsp-001', name: 'Inactive one', sortOrder: 1, isActive: false, usesCount: 0, createdAt: '2026-01-01T00:00:00Z' },
];

describe('CloseThreadDialog', () => {
  it('Close is disabled until a reason is chosen', () => {
    render(<CloseThreadDialog open onOpenChange={vi.fn()} reasons={REASONS} onClose={vi.fn()} />);
    expect(screen.getByTestId('close-thread-submit')).toBeDisabled();
  });

  it('only ACTIVE reasons are offered', async () => {
    const user = userEvent.setup();
    render(<CloseThreadDialog open onOpenChange={vi.fn()} reasons={REASONS} onClose={vi.fn()} />);
    await user.click(screen.getByRole('combobox', { name: 'Close reason' }));
    expect(screen.getByText('General Inquiry')).toBeInTheDocument();
    expect(screen.queryByText('Inactive one')).not.toBeInTheDocument();
  });

  it('picking a reason enables Close; note is optional', async () => {
    const onClose = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<CloseThreadDialog open onOpenChange={vi.fn()} reasons={REASONS} onClose={onClose} />);
    await user.click(screen.getByRole('combobox', { name: 'Close reason' }));
    await user.click(screen.getByText('General Inquiry'));
    expect(screen.getByTestId('close-thread-submit')).toBeEnabled();
    await user.click(screen.getByTestId('close-thread-submit'));
    expect(onClose).toHaveBeenCalledWith('cr-1', '');
  });

  it('passes the typed note through', async () => {
    const onClose = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<CloseThreadDialog open onOpenChange={vi.fn()} reasons={REASONS} onClose={onClose} />);
    await user.click(screen.getByRole('combobox', { name: 'Close reason' }));
    await user.click(screen.getByText('General Inquiry'));
    await user.type(screen.getByTestId('close-note'), 'Refunded in full.');
    await user.click(screen.getByTestId('close-thread-submit'));
    expect(onClose).toHaveBeenCalledWith('cr-1', 'Refunded in full.');
  });

  it('maps a 422 fieldError onto the dialog error banner', async () => {
    const onClose = vi
      .fn()
      .mockRejectedValue(new ApiError('Unprocessable', 422, null, { fieldErrors: { closeReasonId: 'Choose an active close reason.' } }));
    const user = userEvent.setup();
    render(<CloseThreadDialog open onOpenChange={vi.fn()} reasons={REASONS} onClose={onClose} />);
    await user.click(screen.getByRole('combobox', { name: 'Close reason' }));
    await user.click(screen.getByText('General Inquiry'));
    await user.click(screen.getByTestId('close-thread-submit'));
    expect(await screen.findByText('Choose an active close reason.')).toBeInTheDocument();
  });
});
