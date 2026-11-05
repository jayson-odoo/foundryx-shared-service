import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { FileRow } from '@/types/documents';

const previewUrl = vi.fn();
vi.mock('@/services/document-service', () => ({
  documentService: { previewUrl: (...a: unknown[]) => previewUrl(...a) },
}));

import { PreviewDialog } from './preview-dialog';

beforeEach(() => {
  URL.revokeObjectURL = vi.fn();
  previewUrl.mockResolvedValue('blob:test');
});
afterEach(() => vi.clearAllMocks());

const file = (name: string) =>
  ({ id: 'f1', name, currentVersion: { sizeBytes: 10 }, versionCount: 1 }) as unknown as FileRow;

// The blob's type is decided in documentService.previewUrl (see
// services/document-service.real.test.ts); this pins that the frame is fed
// only that service-built url.
describe('drive preview PDF frame (AC-52-02)', () => {
  it('a pdf is framed from the url the service built', async () => {
    render(<PreviewDialog file={file('scan.pdf')} onClose={() => {}} onDownload={() => {}} />);
    const frame = await screen.findByTitle('scan.pdf');
    expect(frame.tagName).toBe('IFRAME');
    expect(frame.getAttribute('src')).toBe('blob:test');
    expect(previewUrl).toHaveBeenCalledWith('f1');
  });

  it('a file type outside the previewable set is not framed', async () => {
    render(<PreviewDialog file={file('page.html')} onClose={() => {}} onDownload={() => {}} />);
    await vi.waitFor(() => expect(previewUrl).toHaveBeenCalled());
    expect(screen.queryByTitle('page.html')).toBeNull();
    expect(document.querySelector('iframe')).toBeNull();
  });
});
