import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { UseAutocountReviewResult } from '@/hooks/use-autocount-review';
import type { UseAutocountPreviewResult } from '@/hooks/use-autocount-preview';
import { ReviewView } from './review-view';

const reviewState = vi.fn<() => UseAutocountReviewResult>();
const previewState = vi.fn<() => UseAutocountPreviewResult>();

vi.mock('@/hooks/use-autocount-review', () => ({
  useAutocountReview: () => reviewState(),
}));
vi.mock('@/hooks/use-autocount-preview', () => ({
  useAutocountPreview: () => previewState(),
}));
// The staged records render through their own server-paginated Resource list;
// stub it so this suite stays focused on the approve gate + toolbar.
vi.mock('./staged-records-list', () => ({
  StagedRecordsList: ({ jobId }: { jobId: string }) => (
    <div data-testid="staged-records-list">{jobId}</div>
  ),
}));
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    timeZone: 'UTC',
    formatDate: () => '',
    formatDateTime: () => '2026-07-21 09:00',
    formatTime: () => '',
  }),
}));
// Layout chrome pulls in the settings/session providers — passthroughs keep the
// test focused on the approve gate.
vi.mock('@/components/common/container', () => ({
  Container: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock('@/partials/common/toolbar', () => ({
  Toolbar: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  ToolbarActions: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  ToolbarHeading: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  ToolbarPageTitle: ({ text }: { text: string }) => <h1>{text}</h1>,
}));

function baseReview(over: Partial<UseAutocountReviewResult> = {}): UseAutocountReviewResult {
  return {
    job: {
      id: 'job-1',
      status: 'needs_review',
      progressTotal: 1,
      progressDone: 1,
      progressFailed: 0,
      result: null,
      error: null,
      createdAt: '2026-07-21T09:00:00Z',
    },
    total: 1,
    noChangeCount: 0,
    isLoading: false,
    notFound: false,
    isSubmitting: false,
    canDecide: true,
    blockedReason: null,
    approve: vi.fn(),
    discard: vi.fn(),
    reload: vi.fn(),
    ...over,
  };
}

function basePreview(over: Partial<UseAutocountPreviewResult> = {}): UseAutocountPreviewResult {
  return {
    preview: null,
    isLoading: false,
    error: null,
    hasRun: false,
    failed: false,
    run: vi.fn(),
    ...over,
  };
}

beforeEach(() => {
  reviewState.mockReset();
  previewState.mockReset();
});

describe('ReviewView preview gate (AC-14-20)', () => {
  it('DISABLES Approve until a dry run has been previewed (never approve blind)', () => {
    // AC-14-20 / grill G4: the whole point is the operator SEES the prediction
    // before committing. A decidable batch that has not been previewed must not
    // be approvable.
    reviewState.mockReturnValue(baseReview());
    previewState.mockReturnValue(basePreview()); // hasRun: false
    render(<ReviewView jobId="job-1" />);
    expect(screen.getByTestId('approve-batch')).toBeDisabled();
    expect(screen.getByTestId('approve-blocked')).toHaveTextContent('Preview before approving');
  });

  it('enables Approve once a dry run has run successfully', () => {
    reviewState.mockReturnValue(baseReview());
    previewState.mockReturnValue(
      basePreview({
        hasRun: true,
        preview: { previewable: true, sink: 'sorento', summary: { total: 1, created: 1, updated: 0, failed: 0, retryable: 0 }, predictions: [] },
      }),
    );
    render(<ReviewView jobId="job-1" />);
    expect(screen.getByTestId('approve-batch')).not.toBeDisabled();
  });

  it('enables Approve after a not-previewable dry run (logging sink — nothing to overwrite)', () => {
    reviewState.mockReturnValue(baseReview());
    previewState.mockReturnValue(
      basePreview({
        hasRun: true,
        preview: { previewable: false, sink: 'logging', reason: 'No consumer is configured.' },
      }),
    );
    render(<ReviewView jobId="job-1" />);
    expect(screen.getByTestId('approve-batch')).not.toBeDisabled();
  });

  it('DISABLES Approve while the dry run is failing (never approve blind)', () => {
    reviewState.mockReturnValue(baseReview());
    previewState.mockReturnValue(
      basePreview({ hasRun: true, failed: true, error: 'Consumer unreachable.' }),
    );
    render(<ReviewView jobId="job-1" />);
    expect(screen.getByTestId('approve-batch')).toBeDisabled();
    expect(screen.getByTestId('approve-blocked')).toBeInTheDocument();
  });

  it('offers a Preview push action', () => {
    reviewState.mockReturnValue(baseReview());
    previewState.mockReturnValue(basePreview());
    render(<ReviewView jobId="job-1" />);
    expect(screen.getByTestId('preview-push')).toBeInTheDocument();
  });
});
