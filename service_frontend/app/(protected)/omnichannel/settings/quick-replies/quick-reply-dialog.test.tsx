import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { QuickReplyDialog } from './quick-reply-dialog';

const onClose = vi.fn();
const onCreate = vi.fn();
const onUpdate = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  onCreate.mockResolvedValue(undefined);
  onUpdate.mockResolvedValue(undefined);
});

describe('QuickReplyDialog', () => {
  it('creates a quick reply, trimming shortcut to null when blank', async () => {
    render(
      <QuickReplyDialog item={null} onClose={onClose} onCreate={onCreate} onUpdate={onUpdate} />,
    );
    expect(screen.getByText('New quick reply')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Message/), { target: { value: '  Hello team  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(onCreate).toHaveBeenCalled());
    expect(onCreate).toHaveBeenCalledWith({ shortcut: null, body: 'Hello team' });
    expect(onUpdate).not.toHaveBeenCalled();
  });

  it('disables Save until the body is non-blank', () => {
    render(
      <QuickReplyDialog item={null} onClose={onClose} onCreate={onCreate} onUpdate={onUpdate} />,
    );
    const save = screen.getByRole('button', { name: 'Save' }) as HTMLButtonElement;
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Message/), { target: { value: 'x' } });
    expect(save).not.toBeDisabled();
  });

  it('prefills + updates an existing row (edit mode)', async () => {
    render(
      <QuickReplyDialog
        item={{ id: 'qr-1', workspaceId: 'wsp-1', shortcut: '/hi', body: 'Hi' }}
        onClose={onClose}
        onCreate={onCreate}
        onUpdate={onUpdate}
      />,
    );
    expect(screen.getByText('Edit quick reply')).toBeInTheDocument();
    const shortcut = screen.getByLabelText('Shortcut') as HTMLInputElement;
    expect(shortcut.value).toBe('/hi');
    fireEvent.change(screen.getByLabelText(/Message/), { target: { value: 'Hi there' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(onUpdate).toHaveBeenCalled());
    expect(onUpdate).toHaveBeenCalledWith('qr-1', { shortcut: '/hi', body: 'Hi there' });
  });

  it('shows the error and stays open when a save fails', async () => {
    onCreate.mockRejectedValueOnce(new Error('That shortcut is already in use.'));
    render(
      <QuickReplyDialog item={null} onClose={onClose} onCreate={onCreate} onUpdate={onUpdate} />,
    );
    fireEvent.change(screen.getByLabelText(/Message/), { target: { value: 'x' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(screen.getByText('That shortcut is already in use.')).toBeInTheDocument(),
    );
    expect(onClose).not.toHaveBeenCalled();
  });
});
