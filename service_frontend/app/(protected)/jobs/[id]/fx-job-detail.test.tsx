/**
 * The jobs list and a job's page under the Foundryx UIUX switch (slice
 * W3-JOBS): the red action follows the job's state (Stop while it runs, Try
 * again when it failed), and every action sends what the "…" menu sends with
 * the switch off. The list hides its search box, which searches nothing.
 */
import { Suspense, type ReactNode } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { TooltipsProvider } from '@/providers/tooltips-provider';
import { SettingsProvider } from '@/providers/settings-provider';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import type { Job } from '@/types/jobs';

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

function job(over: Partial<Job> = {}): Job {
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

import JobsPage from '../page';
import JobDetailPage from './page';
import { jobMainActionId } from './fx-job-detail';

function Wrap({ fx, children }: { fx: boolean; children: ReactNode }) {
  return (
    <FxProvider initial={fx} initialTheme={FX_DEFAULT_THEME}>
      <TooltipsProvider>
        <SettingsProvider>{children}</SettingsProvider>
      </TooltipsProvider>
    </FxProvider>
  );
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
  resetPageActionsForTests();
});

async function renderJob(fx: boolean, j: Job) {
  h.job = j;
  const params = Promise.resolve({ id: j.id });
  let view!: ReturnType<typeof render>;
  await act(async () => {
    view = render(
      <Wrap fx={fx}>
        <Suspense fallback={null}>
          <JobDetailPage params={params} />
        </Suspense>
      </Wrap>,
    );
  });
  await screen.findByRole('heading', { name: 'Progress' }).catch(() => screen.findByText('Progress'));
  await settle();
  return view;
}

/** Runs one action with the switch off (from the "…" menu) and on (the red
 *  action or an icon action), and returns both request logs. */
async function both(j: Job, menuLabel: string, fxName: RegExp) {
  const off = await renderJob(false, j);
  h.calls.length = 0;
  fireEvent.pointerDown(screen.getByRole('button', { name: 'Actions' }), { button: 0, clientX: 10, clientY: 10 });
  fireEvent.click(await screen.findByRole('menuitem', { name: menuLabel }));
  await settle();
  const offCalls = calls();
  off.unmount();

  resetPageActionsForTests();
  const on = await renderJob(true, j);
  h.calls.length = 0;
  fireEvent.click(screen.getByRole('button', { name: fxName }));
  await settle();
  const onCalls = calls();
  on.unmount();
  return { offCalls, onCalls };
}

describe('job page: the red action follows the state', () => {
  it('Stop while it runs, Try again when it failed or needs review, none when done', () => {
    expect(jobMainActionId(job({ status: 'running' }))).toBe('abort');
    expect(jobMainActionId(job({ status: 'pending' }))).toBe('abort');
    expect(jobMainActionId(job({ status: 'failed' }))).toBe('retry');
    expect(jobMainActionId(job({ status: 'needs_review' }))).toBe('retry');
    expect(jobMainActionId(job({ status: 'done' }))).toBeNull();
    expect(jobMainActionId(job({ status: 'aborted' }))).toBeNull();
  });

  it('shows the progress as "820 of 1,240" with the job running', async () => {
    await renderJob(true, job());
    expect(screen.getByText('820 of 1,240')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Stop storage migration$/ })).toBeInTheDocument();
    expect(screen.getByText('Key a/b.pdf failed')).toBeInTheDocument();
  });
});

describe('job page: same requests in both looks', () => {
  it('Stop parks the same deferred action as Abort', async () => {
    const { offCalls, onCalls } = await both(job(), 'Abort', /^Stop storage migration$/);
    expect(onCalls).toEqual(offCalls);
    expect((offCalls[0] as unknown[])[0]).toBe('deferred.start');
  });

  it('Try again sends the same request as Retry', async () => {
    const failed = ROWS[2];
    const { offCalls, onCalls } = await both(failed, 'Retry', /^Try again storage migration$/);
    expect(onCalls).toEqual(offCalls);
    expect(offCalls[0]).toEqual(['jobs.retry', 'job-failed']);
  });

  it('Complete anyway parks the same deferred action', async () => {
    const { offCalls, onCalls } = await both(ROWS[1], 'Complete anyway', /^Complete anyway$/);
    expect(onCalls).toEqual(offCalls);
    expect((offCalls[0] as unknown[])[1]).toBe('jobs.complete');
  });
});

describe('jobs list under the new look', () => {
  it('reads the same rows, shows chips and hides the search box', async () => {
    h.calls.length = 0;
    const off = render(<Wrap fx={false}><JobsPage /></Wrap>);
    await screen.findAllByText('Storage migration');
    await settle();
    const offCalls = calls();
    expect(screen.getByRole('textbox', { name: 'Search' })).toBeVisible();
    off.unmount();

    h.calls.length = 0;
    const { container } = render(<Wrap fx><JobsPage /></Wrap>);
    await screen.findAllByText('Storage migration');
    await settle();
    // Same read; only the page size is the new look's pager of 50 (F3a, owner Q4).
    expect(calls()).toEqual([['jobs.list', { page: 0, pageSize: 50 }]]);
    expect(offCalls).toEqual([['jobs.list', { page: 0, pageSize: 25 }]]);
    const wrapper = container.querySelector('[data-fx-list]')!.parentElement!.closest('div[class*="has("]');
    expect(wrapper?.className).toContain('input[aria-label=Search]');
    expect(container.querySelector('[data-fx-chip="warn"]')?.textContent).toBe('Needs review');
    expect(screen.getAllByText(/^820 of 1,240/).length).toBeGreaterThan(0);
  });
});
