import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { FileRow } from '@/types/documents';

vi.mock('@/services/document-service', () => ({
  documentService: { previewUrl: vi.fn().mockResolvedValue('blob:test') },
}));

import { PreviewDialog } from './preview-dialog';

beforeEach(() => {
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => vi.clearAllMocks());

const file = (name: string) =>
  ({ id: 'f1', name, currentVersion: { sizeBytes: 10 }, versionCount: 1 }) as unknown as FileRow;

describe('drive preview PDF frame (AC-52-02)', () => {
  it('renders a pdf inside a sandboxed frame with no script or same-origin grant', async () => {
    render(<PreviewDialog file={file('scan.pdf')} onClose={() => {}} onDownload={() => {}} />);
    const frame = await screen.findByTitle('scan.pdf');
    expect(frame.tagName).toBe('IFRAME');
    expect(frame.hasAttribute('sandbox')).toBe(true);
    const tokens = (frame.getAttribute('sandbox') ?? '').split(/\s+/);
    expect(tokens).not.toContain('allow-scripts');
    expect(tokens).not.toContain('allow-same-origin');
  });
});
