/**
 * Switch-off parity for the Migration pages (Foundryx UIUX slice W2-WS): the
 * job list and a job's page while it runs (total unknown and known) and once
 * done, rendered with the switch OFF. Recorded on the code as it was before
 * the slice; a change that needs one of these snapshots updated is wrong by
 * definition (fix the code, never the snapshot).
 */
import { Suspense } from 'react';
import { act, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import { SettingsProvider } from '@/providers/settings-provider';
import type { MigrationJob } from '@/types/respondio-migration';
import { MIGRATION_JOBS } from '../components/migration-fixture.test-data';
import MigrationListPage from '../page';
import MigrationJobDetailPage from '../[jobId]/page';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/omnichannel/settings/migration'),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { name: 'Demo Admin', timezone: 'Asia/Kuala_Lumpur', permissions: [] } },
    status: 'authenticated',
  }),
}));
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));
vi.mock('@/components/common/require-permission', () => ({
  RequirePermission: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/preferences-service', () => ({
  preferencesService: { get: vi.fn().mockResolvedValue(null), save: vi.fn().mockResolvedValue(undefined) },
}));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => ({ openImport: vi.fn() }),
}));

let detail: MigrationJob = MIGRATION_JOBS[0];
vi.mock('@/services/respondio-migration-service', () => ({
  respondioMigrationService: {
    listJobs: vi.fn(async () => ({ data: MIGRATION_JOBS, total: MIGRATION_JOBS.length, page: 0 })),
    getJob: vi.fn(async () => detail),
    cancelJob: vi.fn(),
    getSync: vi.fn(async () => null),
  },
}));

function stable(root: Element): string {
  const seen = new Map<string, string>();
  return parityHtml(root).replace(/_r_[0-9a-z]+_/g, (id) => {
    let name = seen.get(id);
    if (!name) {
      name = `_rid${seen.size}_`;
      seen.set(id, name);
    }
    return name;
  });
}

beforeEach(() => {
  vi.useRealTimers();
});

async function renderDetail(job: MigrationJob) {
  detail = job;
  const params = Promise.resolve({ jobId: job.id });
  let container!: HTMLElement;
  await act(async () => {
    ({ container } = render(
      <SettingsProvider>
        <Suspense fallback={null}>
          <MigrationJobDetailPage params={params} />
        </Suspense>
      </SettingsProvider>,
    ));
  });
  await screen.findByText('Progress');
  return container;
}

describe('parity (switch off): Migration list', () => {
  it('jobs in every state', async () => {
    const { container } = render(
      <SettingsProvider>
        <MigrationListPage />
      </SettingsProvider>,
    );
    await screen.findByText('Sales space');
    expect(stable(container)).toMatchSnapshot();
  });
});

describe('parity (switch off): Migration job page', () => {
  it('running, total not known yet', async () => {
    expect(stable(await renderDetail(MIGRATION_JOBS[0]))).toMatchSnapshot();
  });

  it('running with a total', async () => {
    expect(stable(await renderDetail(MIGRATION_JOBS[1]))).toMatchSnapshot();
  });

  it('done with failures', async () => {
    expect(stable(await renderDetail(MIGRATION_JOBS[2]))).toMatchSnapshot();
  });
});
