/**
 * ResourceList with the Foundryx UIUX switch on, slice F3b: the selection
 * bar and "Select all n", the empty, nothing-matches, couldn't-load and
 * no-access states, phone cards, the export panel's words and the record
 * arrows greyed at the ends. Switch off is pinned by components/fx/__parity__.
 */
import type { ReactNode } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { Archive } from 'lucide-react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { encodeListQuery } from '@/lib/list-context';
import { FxProvider } from '@/providers/fx-provider';
import { DataGridTableRowSelect, DataGridTableRowSelectAll } from '@/components/ui/data-grid-table';
import { RecordNav } from '@/components/platform/resource-form/record-nav';
import { ResourceList } from '@/components/platform/resource-list/resource-list';
import type { ResourceListConfig } from '@/components/platform/resource-list/types';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import type { ListQuery } from '@/types/resource';
import { fxListStateKind, fxListStateText } from './fx-list-state';
import { fxCardLayout } from './fx-phone-cards';
import { fxRecordNavEnds } from './fx-record-nav';
import { fxBulkUpdateLabel, fxExportLabel, fxExportScope } from './fx-words';

const nav = vi.hoisted(() => ({ params: new URLSearchParams(), push: vi.fn() }));

vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: nav.push, prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => nav.params),
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
    get: vi.fn(async () => null),
    save: vi.fn(async () => undefined),
  },
}));

interface Row {
  id: string;
  name: string;
  status: string;
  phone: string;
}

const ROWS: Row[] = [
  { id: 'r1', name: 'Alpha Tan', status: 'active', phone: '012-1111' },
  { id: 'r2', name: 'Bravo Lim', status: 'invited', phone: '012-2222' },
  { id: 'r3', name: 'Charlie Ng', status: 'active', phone: '012-3333' },
];

const stop = (e: { stopPropagation: () => void }) => e.stopPropagation();

const columns: ColumnDef<Row>[] = [
  {
    id: 'select',
    meta: { reorderable: false },
    header: () => (
      <div role="presentation" onClick={stop} onKeyDown={stop}>
        <DataGridTableRowSelectAll />
      </div>
    ),
    cell: ({ row }) => (
      <div role="presentation" onClick={stop} onKeyDown={stop}>
        <DataGridTableRowSelect row={row} />
      </div>
    ),
    size: 48,
    enableSorting: false,
    enableHiding: false,
  },
  { id: 'name', accessorKey: 'name', header: 'Name', cell: ({ row }) => row.original.name },
  { id: 'status', accessorKey: 'status', header: 'Status', cell: ({ row }) => row.original.status },
  { id: 'phone', accessorKey: 'phone', header: 'Phone', cell: ({ row }) => row.original.phone },
];

const archiveRun = vi.fn();

function makeConfig(
  fetcher: ResourceListConfig<Row>['fetcher'],
  extra: Partial<ResourceListConfig<Row>> = {},
): ResourceListConfig<Row> {
  return {
    viewKey: 'test.f3b',
    pageTitle: 'Records',
    columns,
    getRowId: (row) => row.id,
    rowHref: (row) => `/records/${row.id}`,
    fetcher,
    exporter: vi.fn(async () => 'csv'),
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
    ],
    exportColumns: [
      { id: 'name', label: 'Name' },
      { id: 'phone', label: 'Phone' },
    ],
    actions: [
      {
        id: 'archive',
        label: 'Archive',
        icon: Archive,
        surfaces: { bulk: true },
        isDisabled: (rows) => rows.some((r) => r.status === 'invited'),
        fxDisabledReason: (rows) => `${rows.filter((r) => r.status === 'invited').length} not active yet`,
        run: archiveRun,
      },
    ],
    createLabel: 'Add record',
    onCreate: vi.fn(),
    ...extra,
  };
}

function On({ children }: { children: ReactNode }) {
  return (
    <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
      {children}
    </FxProvider>
  );
}

function setup(
  fetcher: ResourceListConfig<Row>['fetcher'] = vi.fn(async (q: ListQuery) => ({ data: ROWS, total: 312, page: q.page })),
  extra: Partial<ResourceListConfig<Row>> = {},
  hideHeader = false,
) {
  const config = makeConfig(fetcher, extra);
  const utils = render(
    <On>
      <ResourceList config={config} hideHeader={hideHeader} />
    </On>,
  );
  return { config, fetcher, ...utils };
}

function scroller(container: HTMLElement): HTMLElement {
  return container.querySelector('[data-slot="data-grid-scroller"]') as HTMLElement;
}

const realMatchMedia = window.matchMedia;
function phoneWidth(on: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: on && query.includes('max-width: 719px'),
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
}

beforeEach(() => {
  archiveRun.mockReset();
  nav.push.mockReset();
  nav.params = new URLSearchParams();
});
afterEach(() => {
  resetPageActionsForTests();
  window.matchMedia = realMatchMedia;
});

describe('selection bar', () => {
  it('slides in with the count, offers Select all n, greys what cannot apply and clears', async () => {
    const { container } = setup();
    await waitFor(() => expect(within(scroller(container)).getByText('Charlie Ng')).toBeInTheDocument());
    const boxes = within(scroller(container)).getAllByRole('checkbox', { name: 'Select row' });
    fireEvent.click(boxes[0]);

    const bar = await screen.findByRole('toolbar', { name: 'Selection' });
    expect(within(bar).getByText('1 selected')).toBeInTheDocument();
    const archive = within(bar).getByRole('button', { name: 'Archive' });
    expect(archive).not.toHaveAttribute('aria-disabled');
    fireEvent.click(archive);
    expect(archiveRun).toHaveBeenCalledWith([ROWS[0]], expect.anything());

    // A ticked row the action cannot take greys it with its reason.
    fireEvent.click(boxes[1]);
    await waitFor(() => expect(within(bar).getByText('2 selected')).toBeInTheDocument());
    expect(within(bar).getByRole('button', { name: 'Archive' })).toHaveAttribute('aria-disabled', 'true');

    // Select all n picks every match, past the loaded page.
    fireEvent.click(within(bar).getByRole('button', { name: 'Select all 312' }));
    await waitFor(() => expect(within(bar).getByText('312 selected')).toBeInTheDocument());
    expect(within(bar).queryByRole('button', { name: /Select all/ })).toBeNull();
    expect(within(bar).getByRole('button', { name: 'Archive' })).toHaveAttribute('aria-disabled', 'true');

    // Unticking one row leaves "Select all" mode.
    fireEvent.click(within(scroller(container)).getAllByRole('checkbox', { name: 'Select row' })[2]);
    await waitFor(() => expect(within(bar).getByText('2 selected')).toBeInTheDocument());

    fireEvent.click(within(bar).getByRole('button', { name: 'Clear selection' }));
    await waitFor(() => expect(screen.queryByRole('toolbar', { name: 'Selection' })).toBeNull());
  });

  it('exports every match after Select all n, naming the count', async () => {
    const { container, config } = setup();
    await waitFor(() => expect(within(scroller(container)).getByText('Charlie Ng')).toBeInTheDocument());
    fireEvent.click(within(scroller(container)).getAllByRole('checkbox', { name: 'Select row' })[0]);
    const bar = await screen.findByRole('toolbar', { name: 'Selection' });

    fireEvent.click(within(bar).getByRole('button', { name: 'Export' }));
    let dialog = await screen.findByRole('dialog', { name: 'Export to CSV' });
    expect(within(dialog).getByText('1 ticked row')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Export 1 row' })).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Export to CSV' })).toBeNull());

    fireEvent.click(within(bar).getByRole('button', { name: 'Select all 312' }));
    fireEvent.click(within(bar).getByRole('button', { name: 'Export' }));
    dialog = await screen.findByRole('dialog', { name: 'Export to CSV' });
    expect(within(dialog).getByText('All 312 matching rows')).toBeInTheDocument();
    URL.createObjectURL = vi.fn(() => 'blob:x');
    URL.revokeObjectURL = vi.fn();
    await act(async () => {
      fireEvent.click(within(dialog).getByRole('button', { name: 'Export 312 rows' }));
    });
    expect(config.exporter).toHaveBeenCalledWith(expect.anything(), ['name', 'phone'], undefined);
  });
});

describe('list states', () => {
  it('nothing here yet: says what will appear, with no second Create', async () => {
    setup(vi.fn(async () => ({ data: [], total: 0, page: 0 })));
    const state = await screen.findByText('Records you add show here.');
    expect(state.closest('[data-fx-list-state="empty"]')).not.toBeNull();
    expect(screen.queryByText('No data available')).toBeNull();
    // Only the page's red action creates.
    expect(screen.getAllByRole('button', { name: 'Add record' })).toHaveLength(1);
  });

  it('nothing matches: names the search and clears it', async () => {
    const fetcher = vi.fn(async (q: ListQuery) =>
      q.search ? { data: [], total: 0, page: 0 } : { data: ROWS, total: 3, page: 0 },
    );
    const { container } = setup(fetcher);
    await waitFor(() => expect(within(scroller(container)).getByText('Charlie Ng')).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('Search'), { target: { value: 'zzz' } });
    expect(await screen.findByText('No records match "zzz".')).toBeInTheDocument();
    // The header row stays.
    expect(container.querySelector('[data-fx-list-head]')).not.toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
    await waitFor(() => expect(within(scroller(container)).getByText('Charlie Ng')).toBeInTheDocument());
  });

  it("couldn't load: says what failed, what is safe, and tries again", async () => {
    let fail = true;
    const fetcher = vi.fn(async () => {
      if (fail) throw new Error('500 Internal Server Error');
      return { data: ROWS, total: 3, page: 0 };
    });
    const { container } = setup(fetcher);
    expect(await screen.findByText("Couldn't load the records.")).toBeInTheDocument();
    expect(screen.getByText('Your search and filters are kept.')).toBeInTheDocument();
    expect(screen.queryByText(/500/)).toBeNull();
    fail = false;
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    await waitFor(() => expect(within(scroller(container)).getByText('Charlie Ng')).toBeInTheDocument());
  });

  it('no access: who can open it and the way back', async () => {
    const fetcher = vi.fn(async () => {
      throw Object.assign(new Error('Forbidden'), { status: 403 });
    });
    setup(fetcher);
    expect(await screen.findByText("Your role can't open Records.")).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Go back' })).toBeInTheDocument();
    expect(screen.queryByText(/403|Forbidden/)).toBeNull();
  });

  it('inside a record tab the same words show smaller', async () => {
    // FX-17: compact is the list's own choice (`embeddedListConfig` sets it),
    // no longer implied by a hidden header.
    setup(vi.fn(async () => ({ data: [], total: 0, page: 0 })), { fx: { noun: 'contacts', compactStates: true } }, true);
    const line = await screen.findByText('Contacts you add show here.');
    expect(line.closest('[data-fx-list-state]')?.className).toContain('py-6');
  });

  it('words for each state (pure)', () => {
    const w = { noun: 'quotations', title: 'Quotations' };
    expect(fxListStateText('empty', { ...w, canCreate: true }).line).toBe('Quotations you add show here.');
    expect(fxListStateText('empty', w).line).toBe('Quotations show here as they arrive.');
    expect(fxListStateText('empty', { ...w, trashed: true }).line).toBe('Trashed quotations show here.');
    expect(fxListStateText('no-match', { ...w, search: 'tan', column: 'Client' }).line).toBe(
      'No quotations match "tan" in Client.',
    );
    expect(fxListStateText('no-match', w).line).toBe('No quotations match these filters.');
    expect(fxListStateText('error', w)).toEqual({
      line: "Couldn't load the quotations.",
      safe: 'Your search and filters are kept.',
    });
    expect(fxListStateText('no-access', w).line).toBe("Your role can't open Quotations.");

    const base = { error: null, errorStatus: null, isLoading: false, rowCount: 0, filtered: false };
    expect(fxListStateKind(base)).toBe('empty');
    expect(fxListStateKind({ ...base, filtered: true })).toBe('no-match');
    expect(fxListStateKind({ ...base, rowCount: 3 })).toBeNull();
    expect(fxListStateKind({ ...base, isLoading: true })).toBeNull();
    expect(fxListStateKind({ ...base, error: 'x' })).toBe('error');
    expect(fxListStateKind({ ...base, error: 'x', errorStatus: 403 })).toBe('no-access');
  });
});

describe('phone cards', () => {
  it('shows a card per row under 720px, drops phone-hidden cells and hides the view toggle', async () => {
    phoneWidth(true);
    const { container } = setup(undefined, {
      fx: { phoneHidden: ['phone'], copyable: ['name'], columnKind: { status: 'status' } },
    });
    const cards = await waitFor(() => {
      const el = container.querySelector('[data-fx-phone-cards]');
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });
    const items = within(cards).getAllByRole('listitem');
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveAttribute('data-row-id', 'r1');
    expect(within(items[0]).getByText('Alpha Tan').closest('[data-fx-h2c]')).not.toBeNull();
    expect(within(items[0]).getByText('active')).toBeInTheDocument();
    expect(within(cards).queryByText('012-1111')).toBeNull();
    expect(container.querySelector('table')).toBeNull();
    expect(screen.queryByRole('radio', { name: 'Smart view' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Columns' })).toBeNull();

    // Ticking a card floats the selection bar.
    fireEvent.click(within(items[0]).getByRole('checkbox', { name: 'Select row' }));
    const bar = await screen.findByRole('toolbar', { name: 'Selection' });
    expect(bar).toHaveAttribute('data-fx-selection-bar', 'floating');

    // A card opens its record.
    fireEvent.click(items[1]);
    expect(nav.push).toHaveBeenCalledWith(expect.stringContaining('/records/r2'));
  });

  it('sizes the table columns when a list first shown as cards widens past the phone breakpoint', async () => {
    let narrow = true;
    const listeners = new Set<() => void>();
    window.matchMedia = ((query: string) => ({
      get matches() {
        return narrow && query.includes('max-width: 719px');
      },
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: (_type: string, cb: () => void) => listeners.add(cb),
      removeEventListener: (_type: string, cb: () => void) => listeners.delete(cb),
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;
    const { container } = setup();
    await waitFor(() => expect(container.querySelector('[data-fx-phone-cards]')).not.toBeNull());

    narrow = false;
    act(() => listeners.forEach((cb) => cb()));
    await waitFor(() => expect(container.querySelector('table')).not.toBeNull());
    // Every column has a measured width, not the browser's equal split.
    await waitFor(() => {
      const cols = Array.from(container.querySelectorAll('table colgroup col'));
      expect(cols.length).toBeGreaterThan(0);
      for (const col of cols) expect(col.getAttribute('style') ?? '').toMatch(/width:/);
    });
  });

  it('freezes the header row under the page header wherever the shell puts it', async () => {
    const { container } = setup();
    await waitFor(() => expect(within(scroller(container)).getByText('Charlie Ng')).toBeInTheDocument());
    const head = container.querySelector('[data-fx-list-head]') as HTMLElement;
    // `--fx-head-top` follows the top bar merging into the page header.
    expect(head.className).toContain(
      'top-[calc(var(--fx-head-top,calc(var(--header-height,0px)+var(--shell-top-offset,0px)))+var(--fx-page-head-h,0px))]',
    );
  });

  it('card layout: top line, status, then the rest or the page card lines (pure)', () => {
    const opts = {
      primaryId: 'name',
      structural: new Set(['select', 'actions']),
      phoneHidden: new Set(['phone']),
      statusIds: new Set(['status']),
    };
    const ids = ['select', 'name', 'status', 'phone', 'amount', 'date', 'actions'];
    expect(fxCardLayout(ids, opts)).toEqual({
      top: ['name'],
      status: ['status'],
      lines: [],
      info: ['amount', 'date'],
    });
    expect(fxCardLayout(ids, { ...opts, cardLines: [['amount', 'phone'], ['date']] })).toEqual({
      top: ['name'],
      status: ['status'],
      lines: [['amount'], ['date']],
      info: [],
    });
  });
});

describe('words', () => {
  it('export scope and button, bulk update label', () => {
    expect(fxExportScope(12, 1240)).toBe('12 ticked rows');
    expect(fxExportScope(0, 1240)).toBe('All 1,240 matching rows');
    expect(fxExportLabel(0, 1240)).toBe('Export 1,240 rows');
    expect(fxExportLabel(1, 1240)).toBe('Export 1 row');
    expect(fxBulkUpdateLabel(12, 'products', 'product')).toBe('Update 12 products');
    expect(fxBulkUpdateLabel(1, 'products', 'product')).toBe('Update 1 product');
  });
});

describe('record arrows', () => {
  const query = encodeListQuery({
    page: 0,
    pageSize: 25,
    search: '',
    sort: null,
    filter: null,
    statusView: 'active',
  });
  const fetchAt = vi.fn(async (_q: ListQuery, index: number) => ({ recordId: `r${index}`, total: 120 }));
  const buildHref = (id: string, ctx: string, i: number) => `/records/${id}?ctx=${ctx}&i=${i}`;

  function renderAt(i: number) {
    nav.params = new URLSearchParams({ ctx: query, i: String(i) });
    return render(
      <On>
        <RecordNav fetchAt={fetchAt} buildHref={buildHref} />
      </On>,
    );
  }

  it('greys Previous on the first record and never wraps', async () => {
    renderAt(0);
    expect(await screen.findByText('1 of 120')).toBeInTheDocument();
    const prev = screen.getByRole('button', { name: 'Previous record' });
    expect(prev).toHaveAttribute('aria-disabled', 'true');
    fireEvent.click(prev);
    expect(screen.getByRole('button', { name: 'Next record' })).not.toHaveAttribute('aria-disabled');
    await act(async () => {});
    expect(nav.push).not.toHaveBeenCalled();
  });

  it('greys Next on the last record', async () => {
    renderAt(119);
    expect(await screen.findByText('120 of 120')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next record' })).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByRole('button', { name: 'Previous record' })).not.toHaveAttribute('aria-disabled');
  });

  it('steps to the next record in the middle', async () => {
    renderAt(2);
    expect(await screen.findByText('3 of 120')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Next record' }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(expect.stringContaining('/records/r3')));
  });

  it('ends (pure)', () => {
    expect(fxRecordNavEnds(0, 120)).toEqual({ atFirst: true, atLast: false });
    expect(fxRecordNavEnds(119, 120)).toEqual({ atFirst: false, atLast: true });
    expect(fxRecordNavEnds(5, 120)).toEqual({ atFirst: false, atLast: false });
  });
});
