/**
 * Switch-off parity for the jobs list and the job page (Foundryx UIUX, slice
 * W3-JOBS). Recorded on the code BEFORE the slice changed anything, so a later
 * change that alters what a user sees, or what reaches the backend, with the
 * switch off fails here. A change that needs one of these snapshots updated is
 * wrong by definition: fix the code, never the snapshot.
 */
import { Suspense, type ReactElement } from 'react';
import { act, fireEvent, render as rtlRender, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import { parityHtml as baseParityHtml } from '@/components/fx/__parity__/parity-utils';
import type { Job } from '@/types/jobs';

/** React 19's `_r_N_` ids renamed in order, so test order cannot shift them. */
function parityHtml(root: Element): string {
  const seen = new Map<string, string>();
  return baseParityHtml(root)
    .replace(/_r_[0-9a-z]+_/g, (id) => {
      if (!seen.has(id)) seen.set(id, `_rid${seen.size}_`);
      return seen.get(id) as string;
    })
    .replace(/(animation|transition)-duration:\s*[0-9.]+m?s/g, '$1-duration: <t>');
}

const h = vi.hoisted(() => ({
  calls: [] as unknown[],
  job: null as unknown,
}));

vi.mock('@/lib/toast', () => {
  const t = (kind: string) => (...args: unknown[]) => {
    h.calls.push([`toast.${kind}`, ...args]);
    return 'toast-id';
  };
  return {
    toast: {
      success: t('success'),
      error: t('error'),
      info: t('info'),
      warning: t('warning'),
      message: t('message'),
      custom: t('custom'),
      dismiss: t('dismiss'),
      fxDone: t('fxDone'),
    },
  };
});

vi.mock('@/components/platform/resource-actions/deferred-toast', () => ({
  deferredToast: (input: Record<string, unknown>) => {
    h.calls.push(['deferredToast', { ...input, commitAt: '<t>', onCancel: typeof input.onCancel }]);
    return 'deferred-toast';
  },
  dismissDeferredToast: (...args: unknown[]) => h.calls.push(['dismissDeferredToast', ...args]),
}));

vi.mock('@/hooks/use-deferred-action', () => ({
  useDeferredAction: () => ({
    state: { status: 'idle' },
    dimEntityIds: [],
    start: async (...args: unknown[]) => {
      h.calls.push(['deferred.start', ...args]);
      return { commitAt: '2026-11-18T02:00:10Z', windowSeconds: 10, failedCount: 0, parkedEntityIds: ['job-run'] };
    },
    cancel: async () => h.calls.push(['deferred.cancel']),
    reset: vi.fn(),
  }),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: (...args: unknown[]) => h.calls.push(['router.push', ...args]),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
    refresh: vi.fn(),
  }),
  usePathname: () => '/jobs',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { name: 'Kay Tan', timezone: 'Asia/Kuala_Lumpur', permissions: [] } },
    status: 'authenticated',
  }),
}));

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));
vi.mock('@/hooks/use-terminology', () => ({
  useTerminology: () => ({
    ready: true,
    label: (k: string) => k,
    labelPlural: (k: string) => k,
    t: (k: string) => k,
    refetch: vi.fn(),
  }),
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/preferences-service', () => ({
  preferencesService: { get: vi.fn().mockResolvedValue(null), save: vi.fn().mockResolvedValue(undefined) },
}));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => ({ openImport: vi.fn(), refresh: vi.fn() }),
}));

export function job(over: Partial<Job> = {}): Job {
  return {
    id: 'job-run',
    tenantId: 't',
    type: 'storage_migration',
    status: 'running',
    actorUserId: 'u-1',
    payload: { fromConnectionId: 'conn-a', toConnectionId: 'conn-b' },
    result: null,
    logs: [
      { ts: '2026-11-18T02:00:00Z', level: 'info', message: 'Copy started' },
      { ts: '2026-11-18T02:01:00Z', level: 'warning', message: 'Slow bucket' },
      { ts: '2026-11-18T02:02:00Z', level: 'error', message: 'Key a/b.pdf failed' },
    ],
    progressTotal: 1240,
    progressDone: 820,
    progressFailed: 3,
    error: null,
    createdAt: '2026-11-18T02:00:00Z',
    startedAt: '2026-11-18T02:00:00Z',
    finishedAt: null,
    ...over,
  };
}

const ROWS: Job[] = [
  job(),
  job({
    id: 'job-review',
    status: 'needs_review',
    progressDone: 1237,
    result: {
      copied: 1237,
      failed: 3,
      orphaned: 0,
      failures: [{ key: 'a/b.pdf', reason: 'Access denied' }],
    },
    finishedAt: '2026-11-18T02:10:00Z',
  }),
  job({ id: 'job-failed', status: 'failed', progressTotal: 0, progressDone: 0, progressFailed: 0, error: 'Bucket not reachable' }),
  job({ id: 'job-done', status: 'done', progressDone: 1240, progressFailed: 0 }),
];

vi.mock('@/services/jobs-service', () => ({
  jobsService: {
    listJobs: (...args: unknown[]) => {
      h.calls.push(['jobs.list', ...args]);
      return Promise.resolve({ items: ROWS, total: ROWS.length });
    },
    getJob: (...args: unknown[]) => {
      h.calls.push(['jobs.get', ...args]);
      return Promise.resolve(h.job);
    },
    retryJob: (...args: unknown[]) => {
      h.calls.push(['jobs.retry', ...args]);
      return Promise.resolve(job({ status: 'pending' }));
    },
    abortJob: vi.fn(),
    completeJob: vi.fn(),
  },
}));

// Imported after the mocks.
import JobsPage from '../page';
import JobDetailPage from '../[id]/page';

function render(ui: ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

async function settle(ms = 50) {
  await act(async () => {
    await new Promise((r) => setTimeout(r, ms));
  });
}

function calls(): unknown[] {
  return JSON.parse(JSON.stringify(h.calls));
}

beforeEach(() => {
  h.calls.length = 0;
  h.job = job({ status: 'done', progressDone: 1240, progressFailed: 0 });
});

describe('switch-off parity: jobs list', () => {
  it('renders the list as today', async () => {
    const { container } = render(<JobsPage />);
    await screen.findByText('Bucket not reachable', {}, { timeout: 100 }).catch(() => null);
    await screen.findAllByText('Storage migration');
    await settle();
    expect(parityHtml(container)).toMatchSnapshot();
    expect(calls()).toMatchSnapshot();
  });
});

async function renderJob(j: Job) {
  h.job = j;
  const params = Promise.resolve({ id: j.id });
  let view!: ReturnType<typeof render>;
  await act(async () => {
    view = render(
      <Suspense fallback={null}>
        <JobDetailPage params={params} />
      </Suspense>,
    );
  });
  await screen.findByText('Progress');
  await settle();
  return view;
}

async function openMenuItem(label: string) {
  const trigger = screen.getByRole('button', { name: 'Actions' });
  fireEvent.pointerDown(trigger, { button: 0, clientX: 10, clientY: 10 });
  const item = await screen.findByRole('menuitem', { name: label });
  fireEvent.click(item);
  await settle();
}

describe('switch-off parity: job page', () => {
  it('renders a finished job as today', async () => {
    const { container } = await renderJob(job({ status: 'done', progressDone: 1240, progressFailed: 0, finishedAt: '2026-11-18T02:10:00Z' }));
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('renders a job needing review, with its failed files, as today', async () => {
    const { container } = await renderJob(ROWS[1]);
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('renders a failed job as today', async () => {
    const { container } = await renderJob(ROWS[2]);
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('Retry sends the same request as today', async () => {
    await renderJob(ROWS[2]);
    h.calls.length = 0;
    await openMenuItem('Retry');
    expect(calls()).toMatchSnapshot();
  });

  it('Abort parks the same deferred action as today', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      await renderJob(job());
      h.calls.length = 0;
      await openMenuItem('Abort');
      expect(calls()).toMatchSnapshot();
    } finally {
      vi.useRealTimers();
    }
  });

  it('Complete anyway parks the same deferred action as today', async () => {
    await renderJob(ROWS[1]);
    h.calls.length = 0;
    await openMenuItem('Complete anyway');
    expect(calls()).toMatchSnapshot();
  });
});
