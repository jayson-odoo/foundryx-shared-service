import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { IdeaCommentsView } from './idea-comments-view';

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDate: (v: string) => v, formatDateTime: (v: string) => v, formatTime: (v: string) => v }),
}));

beforeEach(() => {
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:x'), revokeObjectURL: vi.fn() }));
});

const view = (onAdd: () => Promise<unknown>) => (
  <IdeaCommentsView threads={[]} count={0} loading={false} error={null} canComment onAdd={onAdd} allowAttachments />
);

describe('staff comment box', () => {
  it('names why a file failed; its X drops it and the box returns to normal', async () => {
    const bad = new File(['x'], 'a.png', { type: 'image/png' });
    const onAdd = vi.fn().mockResolvedValue({ commentId: 'c1', failed: [{ file: bad, reason: 'a.png is too large (max 25 MB)' }] });
    const { container } = render(view(onAdd));
    await userEvent.upload(container.querySelector('input[type="file"]') as HTMLInputElement, bad);
    await userEvent.click(screen.getByRole('button', { name: 'Comment' }));
    expect(await screen.findByText('a.png is too large (max 25 MB)')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Remove a.png' }));
    expect(await screen.findByRole('button', { name: 'Comment' })).toBeInTheDocument();
  });

  it('a failed post (null) keeps the text and the files', async () => {
    const onAdd = vi.fn().mockResolvedValue(null);
    const { container } = render(view(onAdd));
    await userEvent.type(screen.getByRole('textbox'), 'hello');
    await userEvent.upload(container.querySelector('input[type="file"]') as HTMLInputElement, new File(['x'], 'k.png', { type: 'image/png' }));
    await userEvent.click(screen.getByRole('button', { name: 'Comment' }));
    expect(screen.getByRole('textbox')).toHaveValue('hello');
    expect(screen.getByText('k.png')).toBeInTheDocument();
  });
});
