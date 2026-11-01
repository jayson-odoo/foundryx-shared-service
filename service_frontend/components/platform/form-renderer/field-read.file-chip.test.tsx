/**
 * The uploaded-file chip opens the fetched blob with a content type that is
 * never taken from the answer: markup types and an empty type open as an opaque
 * download; plain types are kept.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const toastError = vi.fn();
vi.mock('@/lib/toast', () => ({ toast: { error: (...a: unknown[]) => toastError(...a) } }));

import { FieldRead } from './field-read';
import { SubmissionContext } from './submission-context';
import type { FormField } from '@/types/forms';

const field: FormField = { id: 'f1', key: 'resume', type: 'file', label: 'Resume' };
const value = [{ key: 'forms/f/s/resume/0-x', name: 'cv.bin', size: 1, mime: 'text/plain' }];

function renderChip(fetchFile: (path: string) => Promise<Blob>) {
  render(
    <SubmissionContext.Provider value={{ submissionId: 'sub-1', fetchFile }}>
      <FieldRead field={field} value={value} />
    </SubmissionContext.Provider>,
  );
  fireEvent.click(screen.getByRole('button', { name: /cv\.bin/ }));
}

describe('FileChip content type', () => {
  let createObjectURL: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    toastError.mockClear();
    createObjectURL = vi.fn(() => 'blob:test');
    Object.defineProperty(URL, 'createObjectURL', { value: createObjectURL, configurable: true, writable: true });
    Object.defineProperty(URL, 'revokeObjectURL', { value: vi.fn(), configurable: true, writable: true });
    vi.spyOn(window, 'open').mockReturnValue(null);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it.each(['text/html', 'image/svg+xml', ''])('opens a fetched %j blob as an opaque download', async (type) => {
    renderChip(async () => new Blob(['x'], { type }));
    await waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1));
    expect((createObjectURL.mock.calls[0][0] as Blob).type).toBe('application/octet-stream');
  });

  it.each(['image/png', 'application/pdf', 'text/plain'])('keeps the %s type of a fetched blob', async (type) => {
    renderChip(async () => new Blob(['x'], { type }));
    await waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1));
    expect((createObjectURL.mock.calls[0][0] as Blob).type).toBe(type);
  });

  it('a failed fetch still shows the existing toast', async () => {
    renderChip(async () => {
      throw new Error('boom');
    });
    await waitFor(() => expect(toastError).toHaveBeenCalledWith('Could not open the file.'));
    expect(createObjectURL).not.toHaveBeenCalled();
  });
});
