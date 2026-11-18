/**
 * Migration with the Foundryx UIUX switch on (slice W2-WS): progress in
 * background-work words ("820 of 1,240"), Abort as an Other Action sending
 * the same request, and starting a migration (dry run, then Start migration)
 * sending exactly what it sends with the switch off. Switch off is pinned by
 * `__parity__/migration.parity.test.tsx`. Requests are captured at
 * `apiFetch`, under the real migration service.
 */
import { Suspense, type ReactNode } from 'react';
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type {
  MigrationJob,
  MigrationPreflight,
} from '@/types/respondio-migration';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { SettingsProvider } from '@/providers/settings-provider';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import MigrationJobDetailPage from './[jobId]/page';
import { MIGRATION_JOBS } from './components/migration-fixture.test-data';
import { ScopeSection } from './components/migration-form-sections';
import { MigrationFormView } from './components/migration-form-view';
import {
  fxMigrationCount,
  fxMigrationHeadline,
  fxMigrationLine,
} from './components/migration-fx';

const net = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock('@/lib/api-client', async (orig) => {
  const real = (await orig()) as Record<string, unknown>;
  return { ...real, apiFetch: net.apiFetch };
});
const toasts = vi.hoisted(() => ({
  fxDone: vi.fn(),
  error: vi.fn(),
  success: vi.fn(),
}));
vi.mock('@/lib/toast', async (orig) => {
  const real = (await orig()) as { toast: Record<string, unknown> };
  return { toast: { ...real.toast, ...toasts } };
});
const router = vi.hoisted(() => ({
  push: vi.fn(),
  prefetch: vi.fn(),
  replace: vi.fn(),
  back: vi.fn(),
}));
vi.mock('next/navigation', () => ({
  useRouter: () => router,
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/omnichannel/settings/migration/new'),
}));
vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: {
      user: {
        name: 'Nurul Huda',
        timezone: 'Asia/Kuala_Lumpur',
        permissions: [],
      },
    },
    status: 'authenticated',
  }),
}));
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({
    can: () => true,
    ready: true,
    permissions: new Set<string>(),
  }),
}));
vi.mock('@/components/common/require-permission', () => ({
  RequirePermission: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock('@/lib/impersonation-store', () => ({
  useImpersonationSession: () => null,
}));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/services/integration-service', () => ({
  integrationService: {
    list: vi.fn(async () => ({
      data: [
        {
          id: 'conn-1',
          name: 'respond.io',
          provider: 'respondio',
          status: 'ACTIVE',
        },
      ],
      total: 1,
    })),
  },
}));
vi.mock('@/services/workspace-service', () => ({
  workspaceService: {
    list: vi.fn(async () => ({
      data: [{ id: 'wsp-1', name: 'General' }],
      total: 1,
    })),
  },
}));
vi.mock('@/services/user-service', () => ({
  userService: { list: vi.fn(async () => ({ data: [], total: 0 })) },
}));
vi.mock('@/services/team-service', () => ({
  teamService: { list: vi.fn(async () => ({ data: [], total: 0 })) },
}));

// Seed the two picks the way a user would have made them, then the real hook.
vi.mock('./components/use-migration-form', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('./components/use-migration-form')>();
  const { useEffect } = await import('react');
  return {
    ...actual,
    useMigrationForm: () => {
      const hook = actual.useMigrationForm();
      useEffect(() => {
        hook.form.setValue('connectionId', 'conn-1');
        hook.form.setValue('workspaceId', 'wsp-1');
        // eslint-disable-next-line react-hooks/exhaustive-deps
      }, []);
      return hook;
    },
  };
});

const PREFLIGHT: MigrationPreflight = {
  apiAvailable: true,
  spaceLabel: 'Acme Support',
  channels: [{ id: 'ch-1', name: 'Support line', source: 'whatsapp_cloud' }],
  users: [],
  teams: [],
  fields: [],
  lifecycles: [],
  targetChannels: [
    { id: 'tc-1', name: 'Main WhatsApp', channelType: 'WHATSAPP' },
  ],
  targetStages: [],
  warnings: [],
} as unknown as MigrationPreflight;

const done = (mode: 'dry_run' | 'run'): MigrationJob => ({
  ...MIGRATION_JOBS[2],
  id: `job-${mode}`,
  mode,
  source: 'api',
  connectionId: 'conn-1',
  failureCount: 0,
  failureSample: [],
  progressFailed: 0,
});

let detail: MigrationJob = MIGRATION_JOBS[0];

function look(on: boolean) {
  return function Look({ children }: { children: ReactNode }) {
    return (
      <FxProvider initial={on} initialTheme={FX_DEFAULT_THEME}>
        <SettingsProvider>{children}</SettingsProvider>
      </FxProvider>
    );
  };
}

function writes() {
  return net.apiFetch.mock.calls
    .filter(([, init]) => (init as RequestInit | undefined)?.method)
    .map(([path, init]) => ({
      path,
      method: (init as RequestInit).method,
      body: (init as RequestInit).body ?? null,
    }));
}

beforeEach(() => {
  net.apiFetch.mockReset();
  Object.values(toasts).forEach((fn) => fn.mockReset());
  router.push.mockReset();
  net.apiFetch.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path.startsWith('/omnichannel/migration/preflight')) return PREFLIGHT;
    if (path === '/omnichannel/migration/jobs' && init?.method === 'POST') {
      return done(JSON.parse(String(init.body)).mode);
    }
    if (path.endsWith('/cancel')) return { ...detail, status: 'aborted' };
    if (path.startsWith('/omnichannel/migration/jobs/job-dry_run'))
      return done('dry_run');
    if (path.startsWith('/omnichannel/migration/jobs/')) return detail;
    return {};
  });
});
afterEach(() => resetPageActionsForTests());

describe('background-work words', () => {
  it('counts from the server, never a guess', () => {
    expect(fxMigrationCount(MIGRATION_JOBS[0])).toBe('820 so far');
    expect(fxMigrationCount(MIGRATION_JOBS[1])).toBe('820 of 1,240');
    expect(fxMigrationLine(MIGRATION_JOBS[1])).toBe(
      '820 of 1,240 processed, 2 failed',
    );
    expect(fxMigrationHeadline(MIGRATION_JOBS[0])).toBe(
      'Running in the background',
    );
    expect(fxMigrationHeadline(MIGRATION_JOBS[2])).toBe('Done with errors');
    expect(fxMigrationHeadline({ status: 'aborted', progressFailed: 0 })).toBe(
      'Stopped',
    );
  });
});

async function renderJob(on: boolean, job: MigrationJob) {
  detail = job;
  const params = Promise.resolve({ jobId: job.id });
  let view!: ReturnType<typeof render>;
  await act(async () => {
    view = render(
      <Suspense fallback={null}>
        <MigrationJobDetailPage params={params} />
      </Suspense>,
      { wrapper: look(on) },
    );
  });
  await screen.findByText('Progress');
  return view;
}

describe('the job page', () => {
  it('reads in words under the new look', async () => {
    await renderJob(true, MIGRATION_JOBS[1]);
    expect(screen.getByText('Running in the background')).toBeInTheDocument();
    expect(
      screen.getByText('820 of 1,240 processed, 2 failed'),
    ).toBeInTheDocument();
  });

  it('Abort sends the same request in both looks', async () => {
    const offView = await renderJob(false, MIGRATION_JOBS[1]);
    fireEvent.pointerDown(
      screen.getByRole('button', { name: /actions|more/i }),
      { button: 0, pointerType: 'mouse' },
    );
    fireEvent.click(await screen.findByRole('menuitem', { name: /Abort/ }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    const off = writes();
    offView.unmount();
    net.apiFetch.mockClear();

    await renderJob(true, MIGRATION_JOBS[1]);
    fireEvent.click(
      await screen.findByRole('button', { name: 'Abort migration' }),
    );
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(off).toEqual([
      {
        path: '/omnichannel/migration/jobs/job-2/cancel',
        method: 'POST',
        body: null,
      },
    ]);
    expect(writes()).toEqual(off);
    expect(toasts.fxDone).toHaveBeenCalledWith({
      what: 'Migration from Support space aborted',
      forWhom: 'General',
      byWhom: 'Nurul Huda',
    });
  });

  it('a finished job offers no Abort', async () => {
    await renderJob(true, MIGRATION_JOBS[2]);
    expect(
      screen.queryByRole('button', { name: 'Abort migration' }),
    ).not.toBeInTheDocument();
  });
});

describe('starting a migration: the same requests in both looks', () => {
  async function startIn(on: boolean) {
    net.apiFetch.mockClear();
    const view = render(<MigrationFormView />, { wrapper: look(on) });
    const review = (await screen.findByText('Review')).closest(
      'div[class]',
    )!.parentElement!;
    const dry = within(review).getByRole('button', { name: 'Run dry run' });
    await waitFor(() => expect(dry).toBeEnabled());
    fireEvent.click(dry);
    const start = within(review).getByRole('button', {
      name: 'Start migration',
    });
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);
    await waitFor(() =>
      expect(router.push).toHaveBeenCalledWith(
        '/omnichannel/settings/migration/job-run',
      ),
    );
    const sent = writes();
    view.unmount();
    router.push.mockReset();
    return sent;
  }

  it('dry run and Start migration post the same bodies', async () => {
    const off = await startIn(false);
    const on = await startIn(true);
    expect(off.map((w) => JSON.parse(String(w.body)).mode)).toEqual([
      'dry_run',
      'run',
    ]);
    expect(on).toEqual(off);
  });
});

describe('the scope switch is named under the new look only', () => {
  it('adds the name with the switch on and nothing with it off', () => {
    const props = {
      contactsOnly: false,
      messagesSince: null,
      editing: true,
      onChange: vi.fn(),
    };
    const off = render(<ScopeSection {...props} />, { wrapper: look(false) });
    expect(off.container.querySelector('[role="switch"]')).not.toHaveAttribute(
      'aria-label',
    );
    off.unmount();
    render(<ScopeSection {...props} />, { wrapper: look(true) });
    expect(
      screen.getByRole('switch', {
        name: 'Contacts only (skip message history)',
      }),
    ).toBeInTheDocument();
  });
});
