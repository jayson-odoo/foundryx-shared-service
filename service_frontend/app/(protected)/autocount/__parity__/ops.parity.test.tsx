/**
 * Switch-off parity for the AutoCount review, pull and find pages (Foundryx
 * UIUX slice W5-AC-OPS, build plan 1.3 and 4): the Review list, a batch
 * review (awaiting approval before and after the dry run, and a finished
 * batch), the Pull list (Keys and Snapshots), the Issue key dialog (form and
 * the one-time key), a snapshot record (building and ready) and Find
 * document (form and a found document), rendered with the switch OFF.
 * Recorded on the code as it was before the slice; a change that needs one of
 * these snapshots updated is wrong by definition (fix the code, never the
 * snapshot). Generated ids are renamed in order of appearance.
 */
import type { ReactNode } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import { SettingsProvider } from '@/providers/settings-provider';
import { resetEtlMockState } from '@/services/autocount-service.mock';
import {
  MOCK_REDATED_DOC_NO,
  mockAutocountDocLookupService,
  resetMockDocLookup,
} from '@/services/autocount-doc-lookup-service.mock';
import type { UseAutocountReviewResult } from '@/hooks/use-autocount-review';
import type { UseAutocountPreviewResult } from '@/hooks/use-autocount-preview';
import type { AutocountPullSnapshot, AutocountCompany } from '@/types/autocount';
import AutocountReviewListPage from '../review/page';
import { ReviewView } from '../review/[jobId]/components/review-view';
import { PullView } from '../pull/components/pull-view';
import { IssueKeyDialog } from '../pull/components/issue-key-dialog';
import { SnapshotDetailView } from '../pull/snapshots/[id]/components/snapshot-detail-view';
import { FindDocumentView } from '../find/components/find-document-view';
import { DocResult } from '../find/components/doc-result';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/autocount/review'),
  useParams: vi.fn(() => ({})),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { name: 'Demo Admin', permissions: [] } },
    status: 'authenticated',
    update: vi.fn(),
  }),
}));
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));
vi.mock('@/components/common/require-permission', () => ({
  RequirePermission: ({ children }: { children: ReactNode }) => children,
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/preferences-service', () => ({
  preferencesService: { get: vi.fn().mockResolvedValue(null), save: vi.fn().mockResolvedValue(undefined) },
}));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/services/pending-actions-service', () => ({
  pendingActionsService: { park: vi.fn(), cancel: vi.fn(), current: vi.fn().mockResolvedValue({ pending: null }) },
}));
vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => ({ openImport: vi.fn() }),
}));
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    timeZone: 'UTC',
    formatDate: (v: string) => v ?? '',
    formatDateTime: (v: string) => v ?? '',
    formatTime: (v: string) => v ?? '',
    formatRelative: (v: string) => v ?? '',
  }),
}));

const COMPANY: AutocountCompany = {
  id: 'c1',
  connectionId: 'conn-1',
  databaseName: 'AED_VSOFT',
  companyName: 'V Soft Trading',
  name: 'V Soft',
  isActive: true,
  sinkImpl: 'logging',
  sinkConnectionId: null,
  sorentoCompanyCode: 'VSOFT',
  createdAt: '2026-11-02T03:00:00Z',
  sourceKind: 'db',
  documentPrerequisites: [],
};

const JOBS = vi.hoisted(() => [
  {
    jobId: 'job-1',
    companyName: 'V Soft',
    databaseName: 'AED_VSOFT',
    entityType: 'customer',
    status: 'needs_review',
    progressTotal: 12,
    progressFailed: 2,
    createdAt: '2026-11-10T04:00:00Z',
    updatedAt: '2026-11-10T04:05:00Z',
  },
  {
    jobId: 'job-2',
    companyName: '',
    databaseName: 'AED_OLD',
    entityType: 'product',
    status: 'done',
    progressTotal: 340,
    progressFailed: 0,
    createdAt: '2026-11-09T04:00:00Z',
    updatedAt: null,
  },
]);

vi.mock('@/services/autocount-service', async () => {
  const mock = (await import('@/services/autocount-service.mock')).mockAutocountService;
  return {
    autocountService: {
      ...mock,
      listJobs: vi.fn(async () => ({ data: JOBS, total: 2, page: 0 })),
      listCompanies: vi.fn(async () => ({ data: [COMPANY], total: 1, page: 0 })),
      listStaged: vi.fn(async () => ({
        data: [],
        total: 0,
        page: 0,
        noChangeCount: 0,
        job: { id: 'job-1', status: 'needs_review' },
      })),
    },
  };
});

const reviewState = vi.hoisted(() => ({ current: null as unknown }));
const previewState = vi.hoisted(() => ({ current: null as unknown }));
vi.mock('@/hooks/use-autocount-review', () => ({
  useAutocountReview: () => reviewState.current,
}));
vi.mock('@/hooks/use-autocount-preview', () => ({
  useAutocountPreview: () => previewState.current,
}));
vi.mock('../review/[jobId]/components/staged-records-list', () => ({
  StagedRecordsList: ({ jobId }: { jobId: string }) => <div data-testid="staged-records-list">{jobId}</div>,
}));

const detailState = vi.hoisted(() => ({ current: null as unknown }));
vi.mock('@/hooks/use-autocount-pull', async (orig) => {
  const real = (await orig()) as Record<string, unknown>;
  return {
    ...real,
    usePullSnapshotDetail: () => ({ state: detailState.current, reload: vi.fn() }),
    usePullSnapshotRows: () => ({ state: { status: 'idle' }, run: vi.fn() }),
  };
});

function review(over: Partial<UseAutocountReviewResult> = {}): UseAutocountReviewResult {
  return {
    job: {
      id: 'job-1',
      status: 'needs_review',
      progressTotal: 12,
      progressDone: 12,
      progressFailed: 2,
      result: null,
      error: null,
      createdAt: '2026-11-10T04:00:00Z',
    },
    total: 12,
    noChangeCount: 4,
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
function preview(over: Partial<UseAutocountPreviewResult> = {}): UseAutocountPreviewResult {
  return { preview: null, isLoading: false, error: null, hasRun: false, failed: false, run: vi.fn(), ...over };
}

function snapshot(over: Partial<AutocountPullSnapshot> = {}): AutocountPullSnapshot {
  return {
    id: 'snap-1',
    entityType: 'product',
    companyId: 'c1',
    companyCode: 'VSOFT',
    status: 'ready',
    requestedVia: 'operator',
    createdAt: '2026-11-10T00:00:00Z',
    extractedAt: '2026-11-10T00:05:00Z',
    expiresAt: '2026-11-17T00:05:00Z',
    recordCount: 1234,
    complete: true,
    contentHash: 'sha256:9f2a77c4',
    sourcePageSize: 500,
    progress: null,
    error: null,
    excludedCount: 1,
    excludedRows: [{ reason: 'no_price', item_code: 'A-1' }],
    zeroListPriceCount: 3,
    negativeListPriceCount: 1,
    enrichMissCount: 0,
    ...over,
  };
}

function stable(root: Element): string {
  const seen = new Map<string, string>();
  return parityHtml(root)
    .replace(/ style="(animation-duration: 0s;)?"/g, '')
    .replace(/_r_[0-9a-z]+_/g, (id) => {
      let name = seen.get(id);
      if (!name) {
        name = `_rid${seen.size}_`;
        seen.set(id, name);
      }
      return name;
    });
}

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  resetEtlMockState();
  resetMockDocLookup();
  reviewState.current = review();
  previewState.current = preview();
  detailState.current = { status: 'ready', snapshot: snapshot() };
});

describe('parity (switch off): review', () => {
  it('Review list with rows', async () => {
    const { container } = render(
      <SettingsProvider>
        <AutocountReviewListPage />
      </SettingsProvider>,
    );
    await screen.findAllByText('AED_OLD');
    expect(stable(container)).toMatchSnapshot();
  });

  it('batch awaiting approval, before the dry run', () => {
    const { container } = render(<ReviewView jobId="job-1" />, { wrapper: SettingsProvider });
    expect(stable(container)).toMatchSnapshot();
  });

  it('batch awaiting approval, after the dry run', () => {
    previewState.current = preview({
      hasRun: true,
      preview: {
        previewable: true,
        sink: 'sorento',
        summary: { total: 12, created: 8, updated: 2, failed: 2, retryable: 1 },
        predictions: [],
      },
    });
    const { container } = render(<ReviewView jobId="job-1" />, { wrapper: SettingsProvider });
    expect(stable(container)).toMatchSnapshot();
  });

  it('batch already reviewed', () => {
    reviewState.current = review({
      job: {
        id: 'job-1',
        status: 'done',
        progressTotal: 12,
        progressDone: 12,
        progressFailed: 0,
        result: null,
        error: null,
        createdAt: '2026-11-10T04:00:00Z',
      },
      canDecide: false,
      blockedReason: 'This batch has already been reviewed.',
    });
    const { container } = render(<ReviewView jobId="job-1" />, { wrapper: SettingsProvider });
    expect(stable(container)).toMatchSnapshot();
  });

  it('Discard asks first', () => {
    render(<ReviewView jobId="job-1" />, { wrapper: SettingsProvider });
    fireEvent.click(screen.getByTestId('discard-batch'));
    expect(stable(document.body)).toMatchSnapshot();
  });
});

describe('parity (switch off): pull', () => {
  it('Keys', async () => {
    const { container } = render(<PullView />, { wrapper: SettingsProvider });
    await screen.findByText('Sorento production');
    expect(stable(container)).toMatchSnapshot();
  });

  it('Snapshots', async () => {
    const { container } = render(<PullView />, { wrapper: SettingsProvider });
    await screen.findByText('Sorento production');
    fireEvent.click(screen.getAllByRole('combobox')[0]);
    fireEvent.click(await screen.findByRole('option', { name: 'Snapshots' }));
    await waitFor(() => expect(screen.getAllByText(/Operator|Consumer/).length).toBeGreaterThan(0));
    expect(stable(container)).toMatchSnapshot();
  });

  it('Issue key form', () => {
    render(<IssueKeyDialog open onOpenChange={vi.fn()} companies={[COMPANY]} onIssued={vi.fn()} />, {
      wrapper: SettingsProvider,
    });
    expect(stable(document.body)).toMatchSnapshot();
  });
});

describe('parity (switch off): snapshot', () => {
  it('ready snapshot', () => {
    const { container } = render(<SnapshotDetailView id="snap-1" />, { wrapper: SettingsProvider });
    expect(stable(container)).toMatchSnapshot();
  });

  it('building snapshot', () => {
    detailState.current = {
      status: 'ready',
      snapshot: snapshot({
        status: 'building',
        recordCount: 0,
        progress: { stage: 'lookup:uom', pagesDone: 2, pagesTotal: 4 },
      }),
    };
    const { container } = render(<SnapshotDetailView id="snap-1" />, { wrapper: SettingsProvider });
    expect(stable(container)).toMatchSnapshot();
  });
});

describe('parity (switch off): find document', () => {
  it('empty form', async () => {
    const { container } = render(
      <FindDocumentView lookupOptions={{ service: mockAutocountDocLookupService }} />,
      { wrapper: SettingsProvider },
    );
    await waitFor(() => expect(screen.getByLabelText('Document number *')).toBeTruthy());
    expect(stable(container)).toMatchSnapshot();
  });

  it('found document', async () => {
    const job = await mockAutocountDocLookupService.start({ companyId: 'c1', docNo: MOCK_REDATED_DOC_NO });
    const stored = await mockAutocountDocLookupService.stored('c1', MOCK_REDATED_DOC_NO);
    const { container } = render(
      <DocResult result={job.result!} stored={stored} typeLabel="Delivery order" />,
      { wrapper: SettingsProvider },
    );
    expect(stable(container)).toMatchSnapshot();
  });
});
