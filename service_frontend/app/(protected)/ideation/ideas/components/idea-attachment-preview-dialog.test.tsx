import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import type { IdeaAttachment } from '@/types/ideation';
import { IdeaAttachmentPreviewDialog } from './idea-attachment-preview-dialog';

function served(type: string): Blob {
  const b = new Blob(['x']);
  Object.defineProperty(b, 'type', { value: type });
  return b;
}

let created: Blob[];
beforeEach(() => {
  created = [];
  URL.createObjectURL = vi.fn((b: Blob) => {
    created.push(b);
    return 'blob:test';
  });
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => vi.clearAllMocks());

const upload = (name: string): IdeaAttachment => ({
  id: 'a1',
  kind: 'file' as IdeaAttachment['kind'],
  name,
  url: '',
  contentPath: '/ideas/i1/attachments/a1/content',
});

async function open(att: IdeaAttachment, blob: Blob) {
  render(<IdeaAttachmentPreviewDialog attachment={att} onClose={() => {}} fetchContent={async () => blob} />);
  await waitFor(() => expect(created).toHaveLength(1));
}

const UNLISTED = ['text/html', 'image/svg+xml', 'application/xhtml+xml', 'TEXT/HTML', 'text/html;x=1', ''];

describe('idea attachment preview blob type (AC-52-01)', () => {
  it.each(UNLISTED)('never renders a blob typed %j', async (type) => {
    await open(upload('notes.bin'), served(type));
    expect(created[0].type).toBe('application/octet-stream');
  });

  it('an empty type on a .html name is not rendered as html', async () => {
    await open(upload('page.html'), served(''));
    expect(created[0].type).toBe('application/octet-stream');
  });

  it.each([
    ['image/png', 'image/png'],
    ['image/jpeg', 'image/jpeg'],
    ['application/pdf', 'application/pdf'],
  ])('control: %s still previews', async (type, expected) => {
    await open(upload('f.bin'), served(type));
    expect(created[0].type).toBe(expected);
  });

  it('control: an untyped .pdf still gets the pdf type', async () => {
    await open(upload('scan.pdf'), served(''));
    expect(created[0].type).toBe('application/pdf');
  });
});

describe('idea attachment PDF frame (AC-52-02)', () => {
  it('a pdf is framed from a blob created as application/pdf', async () => {
    await open(upload('scan.pdf'), served('application/pdf'));
    const frame = await screen.findByTitle('scan.pdf');
    expect(frame.tagName).toBe('IFRAME');
    expect(created[0].type).toBe('application/pdf');
    expect(frame.getAttribute('src')).toBe('blob:test');
  });

  it.each(['text/html', 'image/svg+xml', 'application/xhtml+xml', 'TEXT/HTML', 'text/html;x=1'])(
    'a stored %j type never reaches a frame, it is offered as a download',
    async (type) => {
      await open(upload('scan.pdf'), served(type));
      expect(created[0].type).toBe('application/octet-stream');
      expect(screen.queryByTitle('scan.pdf')).toBeNull();
      expect(screen.getAllByText('Download').length).toBeGreaterThan(0);
    },
  );
});
