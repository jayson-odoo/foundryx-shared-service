/**
 * One Jobs place under the Foundryx UIUX switch (slice W3-JOBS): the Jobs
 * sheet lists uploads, imports, jobs and downloads as jobs; each next step
 * calls the provider function the old drawer row called; a job that ends
 * while the app is open says so in a toast.
 */
import { useSyncExternalStore, type ReactNode } from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { TooltipsProvider } from '@/providers/tooltips-provider';
import type { DownloadJob, UploadFileItem } from '@/types/documents';
import type { ImportJob } from '@/types/import';
import type { Job } from '@/types/jobs';
import {
  downloadItem,
  endToast,
  importItem,
  jobItem,
  toJobItems,
  uploadItem,
} from './fx-job-items';

const h = vi.hoisted(() => ({ calls: [] as unknown[] }));

vi.mock('@/lib/toast', () => ({
  toast: {
    fxDone: (...args: unknown[]) => h.calls.push(['toast.fxDone', ...args]),
    success: vi.fn(),
    error: vi.fn(),
  },
}));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: (...args: unknown[]) => h.calls.push(['router.push', ...args]) }),
  usePathname: () => '/',
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { timezone: 'Asia/Kuala_Lumpur' } }, status: 'authenticated' }),
}));

function job(over: Partial<Job> = {}): Job {
  return {
    id: 'job-1',
    tenantId: 't',
    type: 'storage_migration',
    status: 'running',
    actorUserId: null,
    payload: null,
    result: null,
    logs: null,
    progressTotal: 1240,
    progressDone: 820,
    progressFailed: 0,
    error: null,
    createdAt: '2026-11-18T02:00:00Z',
    startedAt: null,
    finishedAt: null,
    ...over,
  };
}
function imp(over: Partial<ImportJob> = {}): ImportJob {
  return {
    id: 'imp-1',
    entityType: 'project_participant',
    mode: 'create_only',
    status: 'importing',
    abortOnInvalid: false,
    triggerAutomations: false,
    sheetName: null,
    mapping: null,
    context: null,
    totalRows: 12,
    validRows: 10,
    invalidRows: 2,
    errors: null,
    hasErrorFile: false,
    createdIds: null,
    updatedIds: null,
    filesPurged: false,
    createdAt: '2026-11-18T03:00:00Z',
    finishedAt: null,
    ...over,
  };
}
function upload(over: Partial<UploadFileItem> = {}): UploadFileItem {
  return { id: 'up-1', name: 'invoice.pdf', sizeBytes: 2048, status: 'uploading', progress: 40, folderId: null, ...over };
}
function zip(over: Partial<DownloadJob> = {}): DownloadJob {
  return {
    id: 'dl-1',
    filename: 'files.zip',
    status: 'processing',
    fileCount: 3,
    error: null,
    createdAt: '2026-11-18T01:00:00Z',
    readyAt: null,
    ...over,
  };
}

describe('one list of jobs (pure)', () => {
  it('reads each kind as a job with a chip, real progress and its next step', () => {
    expect(jobItem(job())).toMatchObject({
      title: 'Storage migration',
      status: 'Running',
      progress: { text: '820 of 1,240', pct: 66 },
      href: '/jobs/job-1',
    });
    expect(jobItem(job({ status: 'done', progressFailed: 3 })).status).toBe('Done with errors');
    expect(jobItem(job({ status: 'aborted' })).status).toBe('Stopped');
    expect(jobItem(job({ status: 'needs_review' })).steps).toEqual([{ kind: 'open', label: 'Review' }]);

    expect(importItem(imp()).title).toBe('Import · Project participant');
    const done = importItem(imp({ status: 'done', createdIds: ['a', 'b'], updatedIds: ['c'] }));
    expect(done).toMatchObject({ status: 'Done with errors', detail: '2 added, 1 updated, 2 with problems' });
    expect(done.steps).toEqual([{ kind: 'open', label: 'View errors' }]);
    expect(importItem(imp({ status: 'validated' })).steps).toEqual([{ kind: 'open', label: 'Continue' }]);

    expect(uploadItem(upload(), 0, '2 KB').progress?.text).toBe('40%');
    expect(uploadItem(upload({ status: 'failed', error: 'Too big' }), 0, '2 KB').steps[0].label).toBe('Try again');
    expect(uploadItem(upload({ status: 'conflict' }), 0, '2 KB').steps.map((s) => s.label)).toEqual([
      'Keep both',
      'Replace',
    ]);
    expect(downloadItem(zip({ status: 'ready' })).steps).toEqual([{ kind: 'download', label: 'Download' }]);
  });

  it('puts this session’s uploads first, then the newest', () => {
    const items = toJobItems({
      uploads: [upload()],
      imports: [imp()],
      jobs: [job()],
      downloads: [zip()],
      sizeOf: () => '2 KB',
    });
    expect(items.map((i) => i.kind)).toEqual(['upload', 'import', 'job', 'download']);
  });

  it('says what finished and how it went', () => {
    expect(endToast(importItem(imp({ status: 'done', createdIds: ['a'] })))).toEqual({
      what: 'Import finished',
      forWhom: 'Project participant',
      howMany: '1 added, 2 with problems',
    });
    expect(endToast(downloadItem(zip({ status: 'ready' })))).toEqual({ what: 'files.zip is ready', howMany: '3 files' });
    expect(endToast(jobItem(job({ status: 'failed' })))?.what).toBe('Storage migration failed');
    expect(endToast(uploadItem(upload({ status: 'done' }), 0, '2 KB'))).toBeNull();
  });
});

// ── The sheet, with the four providers as one tiny store ─────────────────

type Kind = 'uploads' | 'imports' | 'jobs' | 'downloads';
let flags: Record<Kind, boolean>;
let data: { uploads: UploadFileItem[]; imports: ImportJob[]; jobs: Job[]; downloads: DownloadJob[] };
let snapshot = {};
const listeners = new Set<() => void>();
function publish() {
  snapshot = {};
  listeners.forEach((l) => l());
}
function setFlag(kind: Kind, open: boolean) {
  flags = { ...flags, [kind]: open };
  h.calls.push(['setOpen', kind, open]);
  publish();
}
function useStore() {
  useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => snapshot,
  );
}

vi.mock('@/components/platform/document-drive/upload-manager', () => ({
  useUploadManager: () => {
    useStore();
    return {
      open: flags.uploads,
      setOpen: (v: boolean) => setFlag('uploads', v),
      items: data.uploads,
      activeCount: 1,
      resolveConflict: (...a: unknown[]) => h.calls.push(['uploads.resolveConflict', ...a]),
      retry: (...a: unknown[]) => h.calls.push(['uploads.retry', ...a]),
      remove: (...a: unknown[]) => h.calls.push(['uploads.remove', ...a]),
      clearFinished: () => h.calls.push(['uploads.clearFinished']),
    };
  },
}));
vi.mock('@/components/platform/document-drive/downloads-manager', () => ({
  useDownloads: () => {
    useStore();
    return {
      open: flags.downloads,
      setOpen: (v: boolean) => setFlag('downloads', v),
      jobs: data.downloads,
      activeCount: 0,
      download: async (...a: unknown[]) => {
        h.calls.push(['downloads.download', ...a]);
      },
    };
  },
}));
vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => {
    useStore();
    return {
      drawerOpen: flags.imports,
      setDrawerOpen: (v: boolean) => setFlag('imports', v),
      jobs: data.imports,
      activeCount: 1,
    };
  },
}));
vi.mock('@/providers/jobs-activity-provider', () => ({
  useJobsActivity: () => {
    useStore();
    return {
      drawerOpen: flags.jobs,
      setDrawerOpen: (v: boolean) => setFlag('jobs', v),
      jobs: data.jobs,
      activeCount: 1,
    };
  },
}));

import { FxJobsSheet, jobJustEnded, resetJobsSheetForTests } from '@/components/fx/shell/jobs-sheet';

function On({ children }: { children: ReactNode }) {
  return (
    <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
      <TooltipsProvider>{children}</TooltipsProvider>
    </FxProvider>
  );
}

beforeEach(() => {
  h.calls.length = 0;
  resetJobsSheetForTests();
  flags = { uploads: false, imports: false, jobs: false, downloads: false };
  data = {
    uploads: [
      upload({ id: 'up-f', name: 'broken.pdf', status: 'failed', error: 'Network error' }),
      upload({ id: 'up-c', name: 'contract.pdf', status: 'conflict', conflict: { fileName: 'contract.pdf' } as UploadFileItem['conflict'] }),
    ],
    imports: [imp()],
    jobs: [job()],
    downloads: [zip({ status: 'ready' })],
  };
});

describe('the Jobs sheet', () => {
  it('opens on any flag as one list of every kind and loads the downloads', async () => {
    render(<On><FxJobsSheet /></On>);
    act(() => setFlag('imports', true));
    const sheet = await screen.findByRole('dialog', { name: 'Jobs' });
    expect(flags.downloads).toBe(true);
    const rows = within(sheet).getAllByRole('listitem');
    expect(rows.map((r) => r.getAttribute('data-fx-job'))).toEqual(['upload', 'upload', 'import', 'job', 'download']);
    expect(within(sheet).getByText('820 of 1,240')).toBeInTheDocument();
    expect(within(sheet).getByRole('progressbar', { name: 'Storage migration: 820 of 1,240' })).toBeInTheDocument();
    expect(within(sheet).queryByRole('tab')).toBeNull();
  });

  it('each next step calls what the old drawer row called', async () => {
    render(<On><FxJobsSheet /></On>);
    act(() => setFlag('uploads', true));
    const sheet = await screen.findByRole('dialog', { name: 'Jobs' });
    h.calls.length = 0;
    fireEvent.click(within(sheet).getByRole('button', { name: 'Try again' }));
    fireEvent.click(within(sheet).getByRole('button', { name: 'Dismiss' }));
    fireEvent.click(within(sheet).getByRole('button', { name: 'Keep both' }));
    fireEvent.click(within(sheet).getByRole('button', { name: 'Replace' }));
    fireEvent.click(within(sheet).getByRole('button', { name: 'Download' }));
    await act(async () => {});
    expect(h.calls).toEqual([
      ['uploads.retry', 'up-f'],
      ['uploads.remove', 'up-f'],
      ['uploads.resolveConflict', 'up-c', 'keep_both'],
      ['uploads.resolveConflict', 'up-c', 'replace'],
      ['downloads.download', 'dl-1'],
    ]);
  });

  it('a row with a page opens it and closes the sheet', async () => {
    render(<On><FxJobsSheet /></On>);
    act(() => setFlag('jobs', true));
    const sheet = await screen.findByRole('dialog', { name: 'Jobs' });
    expect(within(sheet).getByRole('link', { name: 'Storage migration' })).toHaveAttribute('href', '/jobs/job-1');
    fireEvent.click(within(sheet).getByText('820 of 1,240'));
    expect(h.calls).toContainEqual(['router.push', '/jobs/job-1']);
    expect(Object.values(flags).some(Boolean)).toBe(false);
  });

  it('toasts a job that ends while the app is open, not the ones already over', async () => {
    data.jobs = [job(), job({ id: 'job-old', status: 'done' })];
    render(<On><FxJobsSheet /></On>);
    expect(h.calls.filter((c) => (c as unknown[])[0] === 'toast.fxDone')).toEqual([]);
    act(() => {
      data = {
        ...data,
        jobs: [job({ status: 'done', progressDone: 1240 }), job({ id: 'job-old', status: 'done' })],
        imports: [imp({ status: 'done', createdIds: ['a'] })],
      };
      publish();
    });
    expect(h.calls.filter((c) => (c as unknown[])[0] === 'toast.fxDone')).toEqual([
      ['toast.fxDone', { what: 'Import finished', forWhom: 'Project participant', howMany: '1 added, 2 with problems' }],
      ['toast.fxDone', { what: 'Storage migration finished', howMany: '1,240 of 1,240' }],
    ]);
  });

  it('only a change into an end toasts', () => {
    const running = jobItem(job());
    const done = jobItem(job({ status: 'done' }));
    expect(jobJustEnded(undefined, done)).toBe(false);
    expect(jobJustEnded(running, done)).toBe(true);
    expect(jobJustEnded(done, done)).toBe(false);
    expect(jobJustEnded(running, jobItem(job({ status: 'needs_review' })))).toBe(true);
    expect(jobJustEnded(importItem(imp({ status: 'validating' })), importItem(imp({ status: 'validated' })))).toBe(false);
  });
});
