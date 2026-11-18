/**
 * Foundation follow-up from the first page wave, lists side (switch on):
 * - FX-17: a list without its own header hands its Create to the page header
 *   only when asked; the smaller empty-state words are the list's own choice;
 * - FX-13: `meta.fxAlign: 'end'` right-aligns a column's header and cells,
 *   and a declared status column takes the phone card's top line without a
 *   filter field.
 */
import type { ReactNode } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { PageHeader } from '@/components/platform/page-header';
import { ResourceList } from '@/components/platform/resource-list/resource-list';
import { embeddedListConfig } from '@/components/platform/resource-list/embedded-list-config';
import type { ResourceListConfig } from '@/components/platform/resource-list/types';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import { fxStatusColumnIds } from './list-logic';

vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/products'),
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

interface Product {
  id: string;
  name: string;
  price: string;
  state: string;
}

const ROWS: Product[] = [
  { id: 'p1', name: 'Barcode scanner', price: 'RM 189.00', state: 'Active' },
  { id: 'p2', name: 'Cloud hosting', price: 'USD 1,200.50', state: 'Inactive' },
];

const columns: ColumnDef<Product>[] = [
  { id: 'name', accessorKey: 'name', header: 'Name', cell: ({ row }) => row.original.name },
  {
    id: 'price',
    accessorKey: 'price',
    header: 'Price',
    meta: { fxAlign: 'end' },
    cell: ({ row }) => row.original.price,
  },
  { id: 'state', accessorKey: 'state', header: 'State', cell: ({ row }) => row.original.state },
];

function makeConfig(extra: Partial<ResourceListConfig<Product>> = {}, rows = ROWS): ResourceListConfig<Product> {
  return {
    viewKey: 'test.followup',
    pageTitle: 'Products',
    columns,
    getRowId: (row) => row.id,
    rowHref: (row) => `/products/${row.id}`,
    fetcher: vi.fn(async () => ({ data: rows, total: rows.length, page: 0 })),
    filterFields: [],
    exportColumns: [],
    actions: [],
    createLabel: 'Add product',
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

const realMatchMedia = window.matchMedia;
function phoneWidth() {
  window.matchMedia = ((query: string) => ({
    matches: query.includes('max-width: 719px'),
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
}

afterEach(() => {
  resetPageActionsForTests();
  window.matchMedia = realMatchMedia;
});

/** The page's red action, by its data attribute. */
function redAction(): HTMLElement | null {
  return document.querySelector('[data-fx-main-action] button');
}

describe('FX-17 a list without its own header', () => {
  it('keeps its Create to itself unless the page asks', async () => {
    render(
      <On>
        <PageHeader title="Products" />
        <ResourceList hideHeader config={makeConfig()} />
      </On>,
    );
    await screen.findAllByText('Barcode scanner');
    expect(redAction()).toBeNull();
    expect(screen.getByRole('button', { name: 'Add product' })).toBeInTheDocument();
  });

  it('hands its Create to the page header as the red action when asked', async () => {
    render(
      <On>
        <PageHeader title="Products" />
        <ResourceList hideHeader config={makeConfig({ fx: { createInPageHeader: true } })} />
      </On>,
    );
    await screen.findAllByText('Barcode scanner');
    await waitFor(() => expect(redAction()).not.toBeNull());
    expect(redAction()).toHaveAccessibleName('Add product');
    // Only once: the toolbar no longer offers its own Create.
    expect(screen.getAllByRole('button', { name: 'Add product' })).toHaveLength(1);
  });

  it('shows the full-size empty words; compact only when the list asks', async () => {
    const { unmount } = render(
      <On>
        <ResourceList hideHeader config={makeConfig({ fx: { noun: 'products' } }, [])} />
      </On>,
    );
    const full = await screen.findByText('Products you add show here.');
    expect(full.closest('[data-fx-list-state]')?.className).toContain('py-14');
    unmount();

    const embedded = embeddedListConfig<Product>({
      viewKey: 'test.embedded',
      columns,
      fetcher: async () => ({ data: [], total: 0, page: 0 }),
      getRowId: (row) => row.id,
      rowHref: (row) => `/products/${row.id}`,
      createLabel: 'Add product',
      onCreate: vi.fn(),
    });
    render(
      <On>
        <ResourceList hideHeader config={{ ...embedded, pageTitle: 'Products' }} />
      </On>,
    );
    const compact = await screen.findByText('Products you add show here.');
    expect(compact.closest('[data-fx-list-state]')?.className).toContain('py-6');
  });
});

describe('FX-13 amounts and status', () => {
  it('right-aligns an amount column header and cells together', async () => {
    render(
      <On>
        <ResourceList config={makeConfig()} />
      </On>,
    );
    const cell = (await screen.findAllByText('RM 189.00')).find((el) => el.closest('td'))!.closest('td')!;
    expect(cell.className).toContain('text-end');
    const header = screen.getAllByText('Price').find((el) => el.closest('th'))!.closest('th')!;
    expect(header.className).toContain('text-end');
    const name = (await screen.findAllByText('Barcode scanner')).find((el) => el.closest('td'))!.closest('td')!;
    expect(name.className).not.toContain('text-end');
  });

  it('a declared status column takes the phone card top line without a filter field', async () => {
    phoneWidth();
    render(
      <On>
        <ResourceList config={makeConfig({ fx: { columnKind: { state: 'status' } } })} />
      </On>,
    );
    const name = await screen.findByText('Barcode scanner');
    const card = name.closest('li')!;
    const topLine = card.querySelector('.justify-between')!;
    expect(topLine.textContent).toContain('Barcode scanner');
    expect(topLine.textContent).toContain('Active');
    // Not repeated as an info line under it.
    expect(card.textContent).not.toContain('State :');
  });

  it('an end-aligned amount closes its phone card line', async () => {
    phoneWidth();
    render(
      <On>
        <ResourceList
          config={makeConfig({ fx: { columnKind: { state: 'status' }, cardLines: [['name', 'price']] } })}
        />
      </On>,
    );
    const amount = (await screen.findAllByText('RM 189.00')).find((el) => el.closest('li'))!;
    const box = amount.closest('span.min-w-0')!;
    expect(box.className).toContain('ms-auto');
    expect(box.className).toContain('text-end');
  });

  it('status columns (pure)', () => {
    expect(Array.from(fxStatusColumnIds({ a: 'status', b: 'text' }, { c: 'status', d: 'date' }))).toEqual([
      'a',
      'c',
    ]);
    expect(Array.from(fxStatusColumnIds({ a: null }, undefined))).toEqual([]);
  });
});
