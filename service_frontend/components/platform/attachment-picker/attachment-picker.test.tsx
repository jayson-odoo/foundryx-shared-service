import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * FEEDBACK-ATTACH-IMAGE AC-A-20/21. Chosen contract (the coder matches it):
 *  - `useAttachmentDraft()` -> `{ files: File[], error: string | null, add(files), remove(index),
 *    clear(), wrapperProps }`; spread `wrapperProps` on the wrapped form/area (onPaste/onDrop/...).
 *  - `<AttachmentPicker draft={draft} />` renders the paperclip button (accessible name /attach/i),
 *    a hidden `input[type=file]` (multiple), the pending list (name + a "Remove <name>" button),
 *    and `draft.error` text.
 */
const MB = 1024 * 1024;
const png = (name: string) => new File(['x'], name, { type: 'image/png' });

beforeEach(() => {
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:x'), revokeObjectURL: vi.fn() }));
});

const SPEC = '@/components/platform/attachment-picker/attachment-picker';

async function harness() {
  const { AttachmentPicker, useAttachmentDraft } = await import(/* @vite-ignore */ SPEC);
  let latest: ReturnType<typeof useAttachmentDraft> | null = null;
  function Harness() {
    const draft = useAttachmentDraft();
    latest = draft;
    return (
      <div data-testid="wrap" {...draft.wrapperProps}>
        <AttachmentPicker draft={draft} />
      </div>
    );
  }
  const utils = render(<Harness />);
  return { ...utils, draft: () => latest! };
}

describe('AttachmentPicker (AC-A-20)', () => {
  it('the paperclip opens the file input, which accepts any file', async () => {
    const { container } = await harness();
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input).not.toBeNull();
    expect(input.multiple).toBe(true);
    const click = vi.spyOn(input, 'click');
    await userEvent.click(screen.getByRole('button', { name: /attach/i }));
    expect(click).toHaveBeenCalled();
  });

  it('picked files show by name with a Remove button', async () => {
    const { container } = await harness();
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, [png('a.png'), png('b.png')]);
    expect(screen.getByText('a.png')).toBeInTheDocument();
    expect(screen.getByText('b.png')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Remove a.png' }));
    expect(screen.queryByText('a.png')).toBeNull();
    expect(screen.getByText('b.png')).toBeInTheDocument();
  });

  it('a pasted file from the clipboard is added', async () => {
    const { draft } = await harness();
    fireEvent.paste(screen.getByTestId('wrap'), { clipboardData: { files: [png('pasted.png')], items: [] } });
    expect(screen.getByText('pasted.png')).toBeInTheDocument();
    expect(draft().files).toHaveLength(1);
  });

  it('a dropped file is added', async () => {
    await harness();
    fireEvent.drop(screen.getByTestId('wrap'), { dataTransfer: { files: [png('dropped.png')], types: ['Files'] } });
    expect(screen.getByText('dropped.png')).toBeInTheDocument();
  });
});

describe('AttachmentPicker limits (AC-A-21)', () => {
  it('refuses the 11th file with "Up to 10 files" and keeps the first 10', async () => {
    const { container, draft } = await harness();
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, Array.from({ length: 10 }, (_, i) => png(`f${i}.png`)));
    expect(draft().files).toHaveLength(10);
    await userEvent.upload(input, png('eleventh.png'));
    expect(screen.getByText(/Up to 10 files/)).toBeInTheDocument();
    expect(screen.queryByText('eleventh.png')).toBeNull();
    expect(draft().files).toHaveLength(10);
  });

  it('refuses a 26 MB file by name and keeps other files', async () => {
    const { container, draft } = await harness();
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const big = png('huge.png');
    Object.defineProperty(big, 'size', { value: 26 * MB });
    await userEvent.upload(input, [png('ok.png'), big]);
    expect(screen.getByText('huge.png is too large (max 25 MB)')).toBeInTheDocument();
    expect(screen.getByText('ok.png')).toBeInTheDocument();
    expect(draft().files.map((f) => f.name)).toEqual(['ok.png']);
  });
});
