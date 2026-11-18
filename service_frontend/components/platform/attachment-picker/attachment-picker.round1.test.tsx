import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AttachmentPicker, useAttachmentDraft } from './attachment-picker';

const png = (name: string) => new File(['x'], name, { type: 'image/png' });

beforeEach(() => {
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:x'), revokeObjectURL: vi.fn() }));
});

function Harness() {
  const draft = useAttachmentDraft();
  return (
    <div data-testid="wrap" {...draft.wrapperProps}>
      <AttachmentPicker draft={draft} />
    </div>
  );
}

describe('AttachmentPicker round 1', () => {
  it('the file input offers gallery, camera and files', () => {
    const { container } = render(<Harness />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input.accept).toBe('image/*,video/*,audio/*,application/pdf,*/*');
  });

  it('a files-only paste is taken over', () => {
    render(<Harness />);
    const notPrevented = fireEvent.paste(screen.getByTestId('wrap'), {
      clipboardData: { files: [png('p.png')], items: [], getData: () => '' },
    });
    expect(notPrevented).toBe(false);
    expect(screen.getByText('p.png')).toBeInTheDocument();
  });

  it('a paste with text and an image keeps the text but still adds the image', () => {
    render(<Harness />);
    const notPrevented = fireEvent.paste(screen.getByTestId('wrap'), {
      clipboardData: { files: [png('w.png')], items: [], getData: () => 'some words' },
    });
    expect(notPrevented).toBe(true);
    expect(screen.getByText('w.png')).toBeInTheDocument();
  });
});
