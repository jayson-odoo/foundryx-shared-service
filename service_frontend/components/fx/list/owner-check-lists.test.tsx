/**
 * Owner's local check, lists side:
 * - the frozen header row: the rows sit in their own layer under it, and it
 *   tucks under the page header instead of leaving a hairline gap;
 * - "Joined = Today": both looks ask the server for the user's whole local
 *   day (the switch-off Filters panel and the header filter share the list
 *   hook), not for one UTC midnight.
 */
import type { ReactNode } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { render, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { encodeListQuery } from '@/lib/list-context';
import { FxProvider } from '@/providers/fx-provider';
import { ResourceList } from '@/components/platform/resource-list/resource-list';
import type { ResourceListConfig } from '@/components/platform/resource-list/types';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import type { FilterGroup, ListQuery, ListResult } from '@/types/resource';

const { searchParams } = vi.hoisted(() => ({ searchParams: { current: new URLSearchParams() } }));

vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => searchParams.current),
  usePathname: vi.fn(() => '/user-management/users'),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { permissions: [], timezone: 'Asia/Kuala_Lumpur' } },
    status: 'authenticated',
  }),
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => ({ openImport: vi.fn() }),
}));
vi.mock('@/services/preferences-service', () => ({
  preferencesService: {
    get: vi.fn(async () => null),
    save: vi.fn(async () => undefined),
  },
}));

interface Person {
  id: string;
  name: string;
  joined: string;
}

const ROWS: Person[] = [{ id: 'u1', name: 'Joined today', joined: '2026-11-18T17:11:08Z' }];

const columns: ColumnDef<Person>[] = [
  { id: 'name', accessorKey: 'name', header: 'Name', cell: ({ row }) => row.original.name },
  { id: 'joined', accessorKey: 'joined', header: 'Joined', cell: ({ row }) => row.original.joined },
];

function makeConfig(fetcher: ResourceListConfig<Person>['fetcher']): ResourceListConfig<Person> {
  return {
    viewKey: 'test.owner-check',
    pageTitle: 'Users',
    columns,
    getRowId: (row) => row.id,
    rowHref: (row) => `/user-management/users/${row.id}`,
    fetcher,
    filterFields: [
      { field: 'name', label: 'Name', type: 'text' },
      { field: 'joined', label: 'Joined', type: 'date' },
    ],
    exportColumns: [],
    actions: [],
  };
}

function On({ children }: { children: ReactNode }) {
  return (
    <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
      {children}
    </FxProvider>
  );
}

const realRO = globalThis.ResizeObserver;
afterEach(() => {
  resetPageActionsForTests();
  globalThis.ResizeObserver = realRO;
  searchParams.current = new URLSearchParams();
});

const TODAY_KL = ['2026-11-18T16:00:00.000Z', '2026-11-19T15:59:59.999Z'];

function withFilter(filter: FilterGroup) {
  const query: ListQuery = { page: 0, pageSize: 25, search: '', sort: null, filter, statusView: 'active' };
  searchParams.current = new URLSearchParams({ ctx: encodeListQuery(query) });
}

/** The first `between` condition anywhere in the filter tree. */
function betweenValue(filter: FilterGroup | null | undefined): unknown {
  for (const rule of filter?.rules ?? []) {
    if (rule.kind === 'group') {
      const inner = betweenValue(rule);
      if (inner) return inner;
    } else if (rule.operator === 'between') return rule.value;
  }
  return undefined;
}

describe('Joined = Today in the user zone', () => {
  it('switch off: the Filters panel range goes out as the whole Kuala Lumpur day', async () => {
    withFilter({
      kind: 'group',
      combinator: 'and',
      rules: [{ kind: 'condition', field: 'joined', operator: 'between', value: ['2026-11-19', '2026-11-19'] }],
    });
    const fetcher = vi.fn<(q: ListQuery) => Promise<ListResult<Person>>>(async () => ({ data: ROWS, total: 1, page: 0 }));
    render(<ResourceList config={makeConfig(fetcher)} />);
    await waitFor(() => expect(fetcher).toHaveBeenCalled());
    expect(betweenValue(fetcher.mock.calls[0][0].filter)).toEqual(TODAY_KL);
  });

  it('switch on: the header date filter goes out as the whole Kuala Lumpur day', async () => {
    withFilter({
      kind: 'group',
      combinator: 'and',
      rules: [
        { kind: 'group', combinator: 'and', rules: [] },
        {
          kind: 'group',
          combinator: 'and',
          rules: [{ kind: 'condition', field: 'joined', operator: 'between', value: ['2026-11-19', '2026-11-19'] }],
        },
      ],
    });
    const fetcher = vi.fn<(q: ListQuery) => Promise<ListResult<Person>>>(async () => ({ data: ROWS, total: 1, page: 0 }));
    render(
      <On>
        <ResourceList config={makeConfig(fetcher)} />
      </On>,
    );
    await waitFor(() => expect(fetcher).toHaveBeenCalled());
    expect(betweenValue(fetcher.mock.calls[0][0].filter)).toEqual(TODAY_KL);
  });
});

describe('the frozen header row', () => {
  it('keeps the rows in their own layer under it', async () => {
    const fetcher = vi.fn<(q: ListQuery) => Promise<ListResult<Person>>>(async () => ({ data: ROWS, total: 1, page: 0 }));
    render(
      <On>
        <ResourceList config={makeConfig(fetcher)} />
      </On>,
    );
    await waitFor(() => expect(document.querySelector('[data-fx-list-head]')).not.toBeNull());
    const table = document.querySelector('[data-fx-list-table]')!;
    const body = table.querySelector(':scope > [data-slot="data-grid-scroller"]')!;
    expect(body.className).toContain('relative');
    expect(body.className).toContain('z-0');
  });

  it('sits under a page header of fractional height without a gap', async () => {
    // Only the page header's observer is told about a resize.
    const headerWatchers: (() => void)[] = [];
    globalThis.ResizeObserver = class {
      constructor(private cb: ResizeObserverCallback) {}
      observe(target: Element) {
        if (!target.hasAttribute('data-fx-header')) return;
        headerWatchers.push(() =>
          this.cb([{ target, contentRect: { width: 1000, height: 58.45 } } as ResizeObserverEntry], this as never),
        );
      }
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;
    const realRect = HTMLElement.prototype.getBoundingClientRect;
    HTMLElement.prototype.getBoundingClientRect = function rect(this: HTMLElement) {
      if (this.hasAttribute('data-fx-header')) return { height: 58.45, top: 0, bottom: 58.45 } as DOMRect;
      return realRect.call(this);
    };
    try {
      const fetcher = vi.fn<(q: ListQuery) => Promise<ListResult<Person>>>(async () => ({ data: ROWS, total: 1, page: 0 }));
      render(
        <On>
          <ResourceList config={makeConfig(fetcher)} />
        </On>,
      );
      await waitFor(() => expect(document.querySelector('[data-fx-list]')).not.toBeNull());
      await waitFor(() => expect(headerWatchers.length).toBeGreaterThan(0));
      headerWatchers.forEach((tell) => tell());
      await waitFor(() =>
        expect((document.querySelector('[data-fx-list]') as HTMLElement).style.getPropertyValue('--fx-page-head-h')).toBe(
          '58px',
        ),
      );
    } finally {
      HTMLElement.prototype.getBoundingClientRect = realRect;
    }
  });
});
