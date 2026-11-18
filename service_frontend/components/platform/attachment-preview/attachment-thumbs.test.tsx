import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { IdeaAttachment } from '@/types/ideation';
import { AttachmentThumbs } from './attachment-thumbs';

const att = (over: Partial<IdeaAttachment> = {}): IdeaAttachment => ({
  id: 'a1', kind: 'image', name: 'shot.png', url: '', contentPath: '/portal/ideas/i1/attachments/a1/content', ...over,
});

beforeEach(() => {
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:x'), revokeObjectURL: vi.fn() }));
});

describe('AttachmentThumbs', () => {
  it('a tile requests the thumb variant, never the original', async () => {
    const fetchContent = vi.fn().mockResolvedValue(new Blob(['x'], { type: 'image/jpeg' }));
    render(<AttachmentThumbs attachments={[att()]} fetchContent={fetchContent} />);
    await waitFor(() => expect(fetchContent).toHaveBeenCalled());
    expect(fetchContent.mock.calls.every((c) => String(c[0].contentPath).endsWith('?variant=thumb'))).toBe(true);
  });

  it('the preview popup fetches the original', async () => {
    const fetchContent = vi.fn().mockResolvedValue(new Blob(['x'], { type: 'image/png' }));
    render(<AttachmentThumbs attachments={[att()]} fetchContent={fetchContent} />);
    await waitFor(() => expect(fetchContent).toHaveBeenCalledTimes(1));
    await userEvent.click(screen.getByRole('button', { name: 'shot.png' }));
    await waitFor(() => expect(fetchContent).toHaveBeenCalledTimes(2));
    expect(String(fetchContent.mock.calls[1][0].contentPath).includes('variant')).toBe(false);
  });

  it('a failed thumbnail falls back to the file icon without throwing', async () => {
    const fetchContent = vi.fn().mockRejectedValue(new Error('404'));
    render(<AttachmentThumbs attachments={[att()]} fetchContent={fetchContent} />);
    expect(await screen.findByRole('button', { name: 'shot.png' })).toBeInTheDocument();
  });
});
