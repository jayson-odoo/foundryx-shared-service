/**
 * Switch-off parity for the shells slice F5 branches that F1's harness did not
 * already pin (see parity-utils.ts): the four activity drawers (Uploads,
 * Imports, Jobs, My downloads) opened with fixture rows, and the impersonation
 * banner expanded and collapsed. Recorded on the code before any F5 change.
 */
import { act, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Job } from '@/types/jobs';
import type { ImportJob } from '@/types/import';
import type { DownloadJob, UploadFileItem } from '@/types/documents';
import { JobsDrawer } from '@/components/platform/jobs-drawer';
import { ImportsDrawer } from '@/components/platform/import-wizard/imports-drawer';
import { UploadActivityDrawer } from '@/components/platform/document-drive/upload-activity-drawer';
import { MyDownloadsDrawer } from '@/components/platform/document-drive/my-downloads-drawer';
import { ImpersonationBanner } from '@/components/impersonation/impersonation-banner';
import { parityHtml as baseParityHtml } from './parity-utils';

/**
 * React 19's `_r_N_` ids are renamed too, so test order cannot shift them, and
 * the sheet's spring frame (the opacity and transform it had reached when the
 * markup was read) is masked: it is timing, not markup.
 */
function parityHtml(root: Element): string {
  const seen = new Map<string, string>();
  return baseParityHtml(root)
    .replace(/_r_[0-9a-z]+_/g, (id) => {
      if (!seen.has(id)) seen.set(id, `_rid${seen.size}_`);
      return seen.get(id) as string;
    })
    .replace(/opacity: [0-9.]+;/g, 'opacity: <t>;')
    .replace(/transform: [^;"]+;/g, 'transform: <t>;');
}

vi.mock('next/navigation', () => ({
  usePathname: () => '/documents',
  useRouter: () => ({ push: vi.fn(), prefetch: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { timezone: 'UTC', permissions: [] } },
    status: 'authenticated',
  }),
}));

const T0 = '2026-11-18T06:30:00Z';

const JOBS: Job[] = [
  {
    id: 'job-1',
    tenantId: 't1',
    type: 'storage_migration',
    status: 'running',
    actorUserId: 'u1',
    payload: null,
    result: null,
    logs: null,
    progressTotal: 1240,
    progressDone: 820,
    progressFailed: 3,
    error: null,
    createdAt: T0,
    startedAt: T0,
    finishedAt: null,
  },
  {
    id: 'job-2',
    tenantId: 't1',
    type: 'storage_migration',
    status: 'failed',
    actorUserId: 'u1',
    payload: null,
    result: null,
    logs: null,
    progressTotal: 0,
    progressDone: 0,
    progressFailed: 0,
    error: 'Bucket not reachable',
    createdAt: T0,
    startedAt: T0,
    finishedAt: T0,
  },
  {
    id: 'job-3',
    tenantId: 't1',
    type: 'reindex',
    status: 'needs_review',
    actorUserId: null,
    payload: null,
    result: null,
    logs: null,
    progressTotal: 0,
    progressDone: 0,
    progressFailed: 0,
    error: null,
    createdAt: T0,
    startedAt: null,
    finishedAt: null,
  },
];

function importJob(over: Partial<ImportJob>): ImportJob {
  return {
    id: 'imp-1',
    entityType: 'contacts',
    mode: 'upsert',
    status: 'done',
    abortOnInvalid: false,
    triggerAutomations: false,
    sheetName: null,
    mapping: null,
    context: null,
    totalRows: 120,
    validRows: 118,
    invalidRows: 2,
    errors: null,
    hasErrorFile: false,
    createdIds: ['a', 'b'],
    updatedIds: ['c'],
    filesPurged: false,
    createdAt: T0,
    finishedAt: T0,
    ...over,
  };
}

const IMPORTS: ImportJob[] = [
  importJob({}),
  importJob({ id: 'imp-2', status: 'importing', entityType: 'products' }),
  importJob({ id: 'imp-3', status: 'failed' }),
  importJob({ id: 'imp-4', status: 'validated' }),
];

const UPLOADS: UploadFileItem[] = [
  { id: 'u1', name: 'invoice.pdf', sizeBytes: 20480, status: 'uploading', progress: 40, folderId: null },
  { id: 'u2', name: 'logo.png', sizeBytes: 1024, status: 'done', progress: 100, folderId: null },
  { id: 'u3', name: 'big.zip', sizeBytes: 5242880, status: 'failed', progress: 0, error: 'Too large', folderId: null },
  {
    id: 'u4',
    name: 'report.csv',
    sizeBytes: 2048,
    status: 'conflict',
    progress: 0,
    conflict: { fileName: 'report.csv' } as UploadFileItem['conflict'],
    folderId: null,
  },
];

const DOWNLOADS: DownloadJob[] = [
  { id: 'd1', filename: 'files.zip', status: 'ready', fileCount: 3, error: null, createdAt: T0, readyAt: T0 },
  { id: 'd2', filename: 'more.zip', status: 'processing', fileCount: 1, error: null, createdAt: T0, readyAt: null },
  { id: 'd3', filename: 'bad.zip', status: 'failed', fileCount: 2, error: 'Expired', createdAt: T0, readyAt: null },
];

let importsState = { jobs: IMPORTS, drawerOpen: true };
let uploadsState = { items: UPLOADS, open: true };
let downloadsState = { jobs: DOWNLOADS, open: true };

vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => ({
    jobs: importsState.jobs,
    drawerOpen: importsState.drawerOpen,
    setDrawerOpen: vi.fn(),
    openImport: vi.fn(),
    activeCount: 1,
    refresh: vi.fn(),
  }),
}));

vi.mock('@/components/platform/document-drive/upload-manager', () => ({
  useUploadManager: () => ({
    items: uploadsState.items,
    open: uploadsState.open,
    setOpen: vi.fn(),
    resolveConflict: vi.fn(),
    retry: vi.fn(),
    remove: vi.fn(),
    clearFinished: vi.fn(),
    activeCount: 1,
  }),
}));

vi.mock('@/components/platform/document-drive/downloads-manager', () => ({
  useDownloads: () => ({
    jobs: downloadsState.jobs,
    open: downloadsState.open,
    setOpen: vi.fn(),
    download: vi.fn(),
    activeCount: 1,
  }),
}));

const IMPERSONATION = {
  session: {
    targetUser: { id: 'u-9', name: 'Tan Mei Ling', email: 'tan@example.com' },
  },
};

vi.mock('@/hooks/use-impersonation', () => ({
  useImpersonation: () => ({
    session: IMPERSONATION.session,
    stop: vi.fn(),
    hydrate: vi.fn(async () => {}),
    pending: false,
  }),
}));

beforeEach(() => {
  importsState = { jobs: IMPORTS, drawerOpen: true };
  uploadsState = { items: UPLOADS, open: true };
  downloadsState = { jobs: DOWNLOADS, open: true };
  window.localStorage.clear();
});

afterEach(() => {
  window.localStorage.clear();
});

async function renderBody(ui: React.ReactElement): Promise<string> {
  await act(async () => {
    render(ui);
  });
  return parityHtml(document.body);
}

describe('parity (switch off): activity drawers', () => {
  it('Jobs drawer with rows renders as before', async () => {
    expect(
      await renderBody(<JobsDrawer open onOpenChange={() => {}} jobs={JOBS} />),
    ).toMatchSnapshot();
  });

  it('Jobs drawer empty renders as before', async () => {
    expect(
      await renderBody(<JobsDrawer open onOpenChange={() => {}} jobs={[]} />),
    ).toMatchSnapshot();
  });

  it('Imports drawer with rows renders as before', async () => {
    expect(await renderBody(<ImportsDrawer />)).toMatchSnapshot();
  });

  it('Imports drawer empty renders as before', async () => {
    importsState = { jobs: [], drawerOpen: true };
    expect(await renderBody(<ImportsDrawer />)).toMatchSnapshot();
  });

  it('Uploads drawer with rows renders as before', async () => {
    expect(await renderBody(<UploadActivityDrawer />)).toMatchSnapshot();
  });

  it('Uploads drawer empty renders as before', async () => {
    uploadsState = { items: [], open: true };
    expect(await renderBody(<UploadActivityDrawer />)).toMatchSnapshot();
  });

  it('My downloads drawer with rows renders as before', async () => {
    expect(await renderBody(<MyDownloadsDrawer />)).toMatchSnapshot();
  });

  it('My downloads drawer empty renders as before', async () => {
    downloadsState = { jobs: [], open: true };
    expect(await renderBody(<MyDownloadsDrawer />)).toMatchSnapshot();
  });

  it('closed drawers render nothing, as before', async () => {
    importsState = { jobs: IMPORTS, drawerOpen: false };
    uploadsState = { items: UPLOADS, open: false };
    downloadsState = { jobs: DOWNLOADS, open: false };
    expect(
      await renderBody(
        <>
          <JobsDrawer open={false} onOpenChange={() => {}} jobs={JOBS} />
          <ImportsDrawer />
          <UploadActivityDrawer />
          <MyDownloadsDrawer />
        </>,
      ),
    ).toMatchSnapshot();
  });
});

describe('parity (switch off): impersonation banner', () => {
  it('expanded renders as before and publishes the shell offset', async () => {
    expect(await renderBody(<ImpersonationBanner />)).toMatchSnapshot();
    expect(
      document.documentElement.style.getPropertyValue('--shell-top-offset'),
    ).toBe('0px');
  });

  it('collapsed renders as before', async () => {
    window.localStorage.setItem('foundryx.impersonation.collapsed', '1');
    expect(await renderBody(<ImpersonationBanner />)).toMatchSnapshot();
    expect(
      document.documentElement.style.getPropertyValue('--shell-top-offset'),
    ).toBe('0px');
  });
});
