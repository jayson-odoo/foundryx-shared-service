import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import type { IdeaAttachment } from '@/types/ideation';
import { IdeaAttachmentPreviewDialog } from './idea-attachment-preview-dialog';

// F22 repro (flaky on CI as "Unable to find an element with the text: Download").
// The dialog calls URL.createObjectURL inside the fetch .then and commits
// setBlobUrl only AFTER it returns, so the Download link is not in the DOM at the
// moment createObjectURL is observed. The sibling test waits on createObjectURL
// and queries synchronously; whether the React commit has landed by then is a
// scheduling race. Here we sample the DOM in the microtask right after
// createObjectURL, the earliest moment a waitFor poll can see it: deterministic.
const att: IdeaAttachment = {
  id: 'a1',
  kind: 'file' as IdeaAttachment['kind'],
  name: 'scan.pdf',
  url: '',
  contentPath: '/ideas/i1/attachments/a1/content',
};

describe('F22 download link vs createObjectURL timing', () => {
  it('the Download link is already in the DOM when createObjectURL has been observed', async () => {
    let downloadAtObserve: boolean | null = null;
    URL.createObjectURL = vi.fn(() => {
      queueMicrotask(() => {
        downloadAtObserve = screen.queryAllByText('Download').length > 0;
      });
      return 'blob:test';
    });
    URL.revokeObjectURL = vi.fn();
    const blob = new Blob(['x']);
    Object.defineProperty(blob, 'type', { value: 'text/html' });
    render(<IdeaAttachmentPreviewDialog attachment={att} onClose={() => {}} fetchContent={async () => blob} />);
    await waitFor(() => expect(downloadAtObserve).not.toBeNull());
    expect(downloadAtObserve).toBe(true);
  });
});
