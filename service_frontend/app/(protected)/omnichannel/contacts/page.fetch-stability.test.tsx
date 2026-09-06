/**
 * Finding 7 (review round 1): `useContactActions`/`page.tsx` passed a fresh
 * callbacks object literal to `useContactActions` on every render, which
 * `useMemo`d a new `actions` array reference on every render too - which
 * flowed into `useContactsListConfig`'s own deps and produced a new
 * `config`/`config.fetcher` reference on EVERY page render, not just when
 * the underlying list-config data actually changed. `useResourceList`'s
 * fetch effect keys off `fetcher` identity (`hooks/use-resource-list.ts`),
 * so ANY unrelated state change anywhere on the page (e.g. opening a local
 * dialog) used to refetch the whole contact list.
 *
 * This test stands in for the real `ResourceList` with a minimal stub that
 * mirrors that ONE contract (`useEffect(() => fetcher(query), [fetcher])`)
 * so the assertion is about `config.fetcher`'s IDENTITY stability, not the
 * whole shell's internals: after the page's own data settles, opening
 * "Manage segments" (a purely LOCAL, unrelated `useState`) must NOT trigger
 * another list fetch.
 */
import { useEffect } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import type { ContactSegment } from '@/types/omnichannel';
import type { ListQuery, ListResult } from '@/types/resource';
import ContactsPage from './page';

// The global `next/navigation` stub (`vitest.setup.ts`) mints a NEW router
// object (and new `vi.fn()`s) on every `useRouter()` call - override with
// ONE stable object for this file, matching how the real `useRouter()`
// behaves (a stable object across re-renders); a fresh object per call
// would itself look like "changed data every render" and mask the exact
// bug under test.
const ROUTER = { push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() };
vi.mock('next/navigation', () => ({
  useRouter: () => ROUTER,
  usePathname: () => '/omnichannel/contacts',
  useSearchParams: () => new URLSearchParams(),
}));

function renderPage(ui: React.ReactElement) {
  return render(<SettingsProvider>{ui}</SettingsProvider>);
}

vi.mock('@/hooks/use-can', () => ({
  // `segments.manage` granted so "Manage segments" renders - it's the
  // unrelated, purely-local state toggle this test exercises.
  useCan: () => ({ can: () => true, ready: true, permissions: new Set(['contacts.read', 'segments.manage']) }),
}));
// Stable references (mirrors the REAL `useDatetime`, which `useMemo`s its
// returned functions) - a fresh object/functions per call would itself
// look like "changed data every render" and mask the exact bug under test.
const DATETIME = {
  formatDate: (v: string) => v,
  formatDateTime: (v: string) => v,
  formatTime: (v: string) => v,
};
vi.mock('@/hooks/use-datetime', () => ({ useDatetime: () => DATETIME }));
vi.mock('@/hooks/use-terminology', () => ({
  useTerminology: () => ({
    ready: true,
    label: (k: string) => k,
    labelPlural: (k: string) => k,
    t: (k: string) => k,
    refetch: vi.fn(),
  }),
}));
vi.mock('@/hooks/use-contacts', () => ({
  useActiveWorkspace: () => ({
    workspaceId: 'wsp-1',
    workspaces: [],
    ready: true,
    setWorkspaceId: vi.fn(),
  }),
}));

// STABLE module-level references (mirrors production `useState`-backed
// hooks, which return the SAME array across re-renders unless the
// underlying data actually changes) - a fresh `[]` literal per mock-hook
// invocation would itself look like "new data every render" and mask the
// exact bug this test targets.
const SEGMENTS: ContactSegment[] = [
  {
    id: 'seg-1',
    workspaceId: 'wsp-1',
    name: 'VIP contacts',
    description: null,
    filter: { kind: 'group', combinator: 'and', rules: [] },
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  },
];
const TAGS: never[] = [];
const FIELDS: never[] = [];
const STAGES: never[] = [];
const MEMBERS: never[] = [];

vi.mock('@/hooks/use-contact-segments', () => ({
  useContactSegments: () => ({
    segments: SEGMENTS,
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    refresh: vi.fn(),
  }),
}));
vi.mock('@/hooks/use-contact-tags', () => ({ useContactTags: () => ({ tags: TAGS }) }));
vi.mock('@/hooks/use-contact-fields', () => ({ useContactFields: () => ({ fields: FIELDS }) }));
vi.mock('@/hooks/use-contact-lifecycle-stages', () => ({
  useContactLifecycleStages: () => ({ stages: STAGES }),
}));
vi.mock('@/hooks/use-workspace-members', () => ({ useWorkspaceMembers: () => ({ members: MEMBERS }) }));
vi.mock('@/hooks/use-contact-bulk', () => ({
  useContactBulk: () => ({ busy: false, assign: vi.fn(), tags: vi.fn(), lifecycle: vi.fn() }),
  reportBulkResult: vi.fn(),
}));
vi.mock('@/services/channel-service', () => ({
  channelService: { listByWorkspace: vi.fn().mockResolvedValue([]) },
}));

const listMock = vi.fn(
  async (): Promise<ListResult<unknown>> => ({ data: [], total: 0, page: 0 }),
);
vi.mock('@/services/contact-service', () => ({
  contactService: {
    list: (...args: unknown[]) => listMock(...(args as [string, ListQuery])),
    exportContacts: vi.fn(),
  },
}));

vi.mock('@/components/platform/resource-list', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/platform/resource-list')>();
  return {
    ...actual,
    // Minimal stand-in mirroring the ONE contract under test
    // (`useResourceList`'s `useEffect(fetch, [fetcher, query, reloadKey])`)
    // without the shell's other internals (view prefs, filters, ...).
    ResourceList: ({ config }: { config: { fetcher: (q: ListQuery) => Promise<unknown> } }) => {
      useEffect(() => {
        void config.fetcher({ page: 0, pageSize: 25, sort: null, search: '', filter: null });
        // eslint-disable-next-line react-hooks/exhaustive-deps -- identity IS the thing under test
      }, [config.fetcher]);
      return <div data-testid="resource-list" />;
    },
  };
});

describe('ContactsPage - fetch stability (finding 7)', () => {
  it('an unrelated local state change (opening "Manage segments") does NOT refetch the list', async () => {
    const user = userEvent.setup();
    renderPage(<ContactsPage />);

    await screen.findByTestId('resource-list');
    // Let the channel-types lookup's promise resolve + its state-setting
    // re-render flush, and the fetch count settle.
    await waitFor(() => expect(listMock.mock.calls.length).toBeGreaterThanOrEqual(1));
    await new Promise((resolve) => setTimeout(resolve, 20));
    const settledCount = listMock.mock.calls.length;

    // A purely LOCAL, unrelated `useState` toggle (`manageSegmentsOpen`) -
    // before the fix, `actions`/`config.fetcher` recomputed on THIS render
    // too and the list refetched for no reason.
    await user.click(screen.getByRole('button', { name: 'Manage segments' }));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();

    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(listMock.mock.calls.length).toBe(settledCount);
  });
});
