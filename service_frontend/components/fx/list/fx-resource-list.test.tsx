/**
 * ResourceList with the Foundryx UIUX switch on (slice F3a): the view toggle
 * and its memory, the Columns panel, header search, filter and sort sent to
 * the server, the pager, and the list's Create as the page's red action.
 * Switch off is pinned by components/fx/__parity__.
 */
import type { ReactNode } from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ColumnDef } from '@tanstack/react-table';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { ResourceList } from '@/components/platform/resource-list/resource-list';
import type { ResourceListConfig } from '@/components/platform/resource-list/types';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import type { ListQuery, ViewPreferences } from '@/types/resource';

const stored = new Map<string, ViewPreferences>();
const saves: [string, ViewPreferences][] = [];

vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/records'),
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
    get: vi.fn(async (key: string) => stored.get(key) ?? null),
    save: vi.fn(async (key: string, prefs: ViewPreferences) => {
      saves.push([key, prefs]);
    }),
  },
}));

interface Row {
  id: string;
  name: string;
  status: string;
  createdAt: string;
}

const ROWS: Row[] = Array.from({ length: 3 }, (_, i) => ({
  id: `r${i + 1}`,
  name: ['Alpha Tan', 'Bravo Lim', 'Charlie Ng'][i],
  status: i === 1 ? 'invited' : 'active',
  createdAt: `2026-11-0${i + 1}`,
}));

const columns: ColumnDef<Row>[] = [
  {
    id: 'name',
    accessorKey: 'name',
    header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
    cell: ({ row }) => row.original.name,
    meta: { headerTitle: 'Name' },
  },
  {
    id: 'status',
    accessorKey: 'status',
    header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
    cell: ({ row }) => row.original.status,
    enableSorting: false,
    meta: { headerTitle: 'Status' },
  },
  {
    id: 'createdAt',
    accessorKey: 'createdAt',
    header: 'Created',
    cell: ({ row }) => row.original.createdAt,
  },
];

function makeConfig(fetcher: ResourceListConfig<Row>['fetcher'], extra: Partial<ResourceListConfig<Row>> = {}) {
  const config: ResourceListConfig<Row> = {
    viewKey: 'test.list',
    columns,
    getRowId: (row) => row.id,
    rowHref: (row) => `/records/${row.id}`,
    fetcher,
    filterFields: [
      { field: 'name', label: 'Name', type: 'text' },
      {
        field: 'status',
        label: 'Status',
        type: 'enum',
        options: [
          { label: 'Active', value: 'active' },
          { label: 'Invited', value: 'invited' },
        ],
      },
      { field: 'createdAt', label: 'Created', type: 'date' },
    ],
    exportColumns: [],
    actions: [],
    createLabel: 'Add record',
    onCreate: vi.fn(),
    ...extra,
  };
  return config;
}

function On({ children }: { children: ReactNode }) {
  return (
    <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
      {children}
    </FxProvider>
  );
}

function setup(extra: Partial<ResourceListConfig<Row>> = {}, total = 312) {
  const fetcher = vi.fn(async (q: ListQuery) => ({ data: ROWS, total, page: q.page }));
  const config = makeConfig(fetcher, extra);
  const utils = render(
    <On>
      <ResourceList config={config} />
    </On>,
  );
  return { fetcher, config, ...utils };
}

/** The visible table (the measuring copy is hidden and inert). */
function visibleTable(container: HTMLElement): HTMLElement {
  return container.querySelector('[data-slot="data-grid-scroller"]') as HTMLElement;
}

beforeEach(() => {
  stored.clear();
  saves.length = 0;
});
afterEach(() => resetPageActionsForTests());

describe('FxResourceList: view toggle', () => {
  it('starts on Smart view and remembers Table view per list', async () => {
    const { container } = setup();
    await waitFor(() => expect(within(visibleTable(container)).getByText('Charlie Ng')).toBeInTheDocument());
    const smart = screen.getByRole('radio', { name: 'Smart view' });
    expect(smart).toHaveAttribute('data-state', 'on');

    fireEvent.click(screen.getByRole('radio', { name: 'Table view' }));
    expect(container.querySelector('[data-fx-list-table]')).toHaveAttribute('data-fx-list-table', 'table');
    await waitFor(() => expect(saves.some(([key]) => key === 'test.list:fx')).toBe(true), { timeout: 2000 });
    const [, meta] = saves.find(([key]) => key === 'test.list:fx')!;
    expect(meta.order).toContain('view=table');
  });

  it('opens on the view saved for this list', async () => {
    stored.set('test.list:fx', { order: ['view=table'], widths: {}, hidden: [] });
    const { container } = setup();
    await waitFor(() =>
      expect(container.querySelector('[data-fx-list-table]')).toHaveAttribute('data-fx-list-table', 'table'),
    );
    expect(screen.getByRole('radio', { name: 'Table view' })).toHaveAttribute('data-state', 'on');
  });
});

describe('FxResourceList: header search, filter and sort', () => {
  it('a text header search reaches the server as a contains filter and goes back to page 1', async () => {
    const { fetcher, container } = setup();
    await waitFor(() => expect(within(visibleTable(container)).getByText('Charlie Ng')).toBeInTheDocument());

    fireEvent.click(screen.getAllByRole('button', { name: 'Search Name' })[0]);
    const box = await screen.findByPlaceholderText('Search Name');
    fireEvent.change(box, { target: { value: 'tan' } });
    fireEvent.keyDown(box, { key: 'Enter' });

    await waitFor(() => {
      const last = fetcher.mock.calls.at(-1)?.[0] as ListQuery;
      expect(last.page).toBe(0);
      expect(JSON.stringify(last.filter)).toContain('"field":"name","operator":"contains","value":"tan"');
    });

    // At rest the name turns link-blue instead of being covered.
    fireEvent.blur(box);
    const label = await waitFor(() => {
      const el = container.querySelector('[data-fx-list-head] [data-fx-header-label]');
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });
    expect(label.className).toContain('text-(--fx-link)');
  });

  it('status ticks send an in filter', async () => {
    const { fetcher, container } = setup();
    await waitFor(() => expect(within(visibleTable(container)).getByText('Charlie Ng')).toBeInTheDocument());
    fireEvent.click(screen.getAllByRole('button', { name: 'Filter Status' })[0]);
    const dialog = await screen.findByRole('dialog', { name: 'Filter Status' });
    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Invited' }));
    await waitFor(() => {
      const last = fetcher.mock.calls.at(-1)?.[0] as ListQuery;
      expect(JSON.stringify(last.filter)).toContain('"field":"status","operator":"in","value":["invited"]');
    });
  });

  it('the sort icon goes up, then down, then back to the list order', async () => {
    const { fetcher, container } = setup();
    await waitFor(() => expect(within(visibleTable(container)).getByText('Charlie Ng')).toBeInTheDocument());
    const sortName = () => screen.getAllByRole('button', { name: 'Sort by Name' }).at(-1) as HTMLElement;
    const lastSort = () => (fetcher.mock.calls.at(-1)?.[0] as ListQuery).sort;

    fireEvent.click(sortName());
    await waitFor(() => expect(lastSort()).toEqual({ id: 'name', desc: false }));
    expect(container.querySelector('[data-fx-sort-arrow="asc"]')).not.toBeNull();
    fireEvent.click(sortName());
    await waitFor(() => expect(lastSort()).toEqual({ id: 'name', desc: true }));
    fireEvent.click(sortName());
    await waitFor(() => expect(lastSort()).toBeNull());
  });

  it('a column the list cannot sort or filter gets no header tools', async () => {
    const { container } = setup({ filterFields: [] });
    await waitFor(() => expect(within(visibleTable(container)).getByText('Charlie Ng')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: 'Filter Status' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Sort by Status' })).toBeNull();
    expect(screen.getAllByRole('button', { name: 'Sort by Name' }).length).toBeGreaterThan(0);
  });
});

describe('FxResourceList: Columns panel', () => {
  it('is titled for the selected view, hides a column and keeps at least one shown', async () => {
    const { container } = setup();
    await waitFor(() => expect(within(visibleTable(container)).getByText('Charlie Ng')).toBeInTheDocument());
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Columns' }));
    });
    const panel = await screen.findByRole('dialog', { name: 'Smart view columns' });
    expect(within(panel).getByText('Apply the same to Table view')).toBeInTheDocument();

    fireEvent.click(within(panel).getByRole('switch', { name: 'Show Status' }));
    await waitFor(() =>
      expect(within(visibleTable(container)).queryByText('invited')).not.toBeInTheDocument(),
    );
    fireEvent.click(within(panel).getByRole('switch', { name: 'Show Created' }));
    expect(within(panel).getByRole('switch', { name: 'Show Name' })).toBeDisabled();

    await waitFor(() => expect(saves.some(([key]) => key === 'test.list:fx:smart')).toBe(true), { timeout: 2000 });
    const [, smart] = saves.filter(([key]) => key === 'test.list:fx:smart').at(-1)!;
    expect(smart.hidden).toEqual(['status', 'createdAt']);
  });
});

describe('FxResourceList: pager and red action', () => {
  it('defaults to 50 rows and shows the range of every match', async () => {
    const { fetcher, container } = setup();
    await waitFor(() => expect(within(visibleTable(container)).getByText('Charlie Ng')).toBeInTheDocument());
    expect((fetcher.mock.calls[0][0] as ListQuery).pageSize).toBe(50);
    expect(container.querySelector('[data-fx-showing]')).toHaveTextContent('Showing 1-50 of 312');
    expect(screen.getByRole('button', { name: 'Page 7' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Next page' }));
    await waitFor(() => expect((fetcher.mock.calls.at(-1)?.[0] as ListQuery).page).toBe(1));
    await waitFor(() =>
      expect(container.querySelector('[data-fx-showing]')).toHaveTextContent('Showing 51-100 of 312'),
    );
  });

  it('makes the list Create the page red action', async () => {
    const { container, config } = setup();
    await waitFor(() => expect(within(visibleTable(container)).getByText('Charlie Ng')).toBeInTheDocument());
    const main = await screen.findByRole('button', { name: 'Add record' });
    fireEvent.click(main);
    expect(config.onCreate).toHaveBeenCalled();
    expect(container.querySelector('[data-fx-header-actions]')).toContainElement(main);
  });
});
