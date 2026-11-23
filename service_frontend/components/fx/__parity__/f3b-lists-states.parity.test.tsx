/**
 * Switch-off parity for the shared pieces slice F3b branches (see
 * parity-utils.ts): the record pager, the export dialog, the bulk actions
 * menu, the form's label/value row, and ResourceList's empty, failed-load and
 * ticked-rows states. Recorded on the code before any F3b change.
 */
import type { ColumnDef } from '@tanstack/react-table';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Archive, Trash2 } from 'lucide-react';
import { describe, expect, it, vi } from 'vitest';
import {
  DataGridTableRowSelect,
  DataGridTableRowSelectAll,
} from '@/components/ui/data-grid-table';
import { Input } from '@/components/ui/input';
import { BulkActions } from '@/components/platform/resource-actions/bulk-actions';
import { FormRow } from '@/components/platform/resource-form/form-row';
import { RecordNav } from '@/components/platform/resource-form/record-nav';
import { ExportDialog } from '@/components/platform/resource-list/export-dialog';
import { ResourceList } from '@/components/platform/resource-list/resource-list';
import type { ResourceListConfig } from '@/components/platform/resource-list/types';
import { encodeListQuery } from '@/lib/list-context';
import { parityHtml as baseParityHtml } from './parity-utils';

/** React 19's `_r_N_` ids renamed in order, so test order cannot shift them. */
function parityHtml(root: Element): string {
  const seen = new Map<string, string>();
  return baseParityHtml(root).replace(/_r_[0-9a-z]+_/g, (id) => {
    if (!seen.has(id)) seen.set(id, `_rid${seen.size}_`);
    return seen.get(id) as string;
  });
}

const nav = vi.hoisted(() => ({ params: new URLSearchParams() }));

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({
    push: vi.fn(),
    prefetch: vi.fn(),
    replace: vi.fn(),
  })),
  useSearchParams: vi.fn(() => nav.params),
  usePathname: vi.fn(() => '/records'),
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { permissions: [] } },
    status: 'authenticated',
  }),
}));

vi.mock('@/lib/impersonation-store', () => ({
  useImpersonationSession: () => null,
}));

vi.mock('@/services/preferences-service', () => ({
  preferencesService: {
    get: vi.fn().mockResolvedValue(null),
    save: vi.fn().mockResolvedValue(undefined),
  },
}));

vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));

vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => ({ openImport: vi.fn() }),
}));

interface Row {
  id: string;
  name: string;
}

const rows: Row[] = [
  { id: 'r1', name: 'Alpha Tan' },
  { id: 'r2', name: 'Bravo Lim' },
  { id: 'r3', name: 'Charlie Ng' },
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
  {
    id: 'name',
    accessorKey: 'name',
    header: 'Name',
    cell: ({ row }) => row.original.name,
  },
];

const actions: ResourceListConfig<Row>['actions'] = [
  {
    id: 'archive',
    label: 'Archive',
    icon: Archive,
    surfaces: { row: true, bulk: true },
    isDisabled: (rs) => rs.length > 2,
    run: vi.fn(),
  },
  {
    id: 'trash',
    label: 'Trash',
    icon: Trash2,
    tone: 'destructive',
    surfaces: { row: true, bulk: true },
    run: vi.fn(),
  },
];

function config(extra: Partial<ResourceListConfig<Row>> = {}): ResourceListConfig<Row> {
  return {
    viewKey: 'parity.f3b',
    columns,
    getRowId: (row) => row.id,
    rowHref: (row) => `/records/${row.id}`,
    fetcher: async () => ({ data: rows, total: 120, page: 0 }),
    exporter: async () => '',
    filterFields: [{ field: 'name', label: 'Name', type: 'text' }],
    exportColumns: [
      { id: 'name', label: 'Name' },
      { id: 'email', label: 'Email' },
    ],
    actions,
    createLabel: 'Add record',
    onCreate: vi.fn(),
    ...extra,
  };
}

describe('parity (switch off): ResourceList states (F3b cases)', () => {
  it('empty list', async () => {
    const { container } = render(
      <ResourceList config={config({ fetcher: async () => ({ data: [], total: 0, page: 0 }) })} />,
    );
    await screen.findByText('No data available');
    await act(async () => {});
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('list whose load failed', async () => {
    const fetcher = vi.fn(async () => {
      throw new Error('boom');
    });
    const { container } = render(<ResourceList config={config({ fetcher })} />);
    await waitFor(() => expect(fetcher).toHaveBeenCalled());
    await act(async () => {});
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('two ticked rows show the bulk bar', async () => {
    const { container } = render(<ResourceList config={config()} />);
    await screen.findByText('Charlie Ng');
    const boxes = screen.getAllByRole('checkbox', { name: 'Select row' });
    fireEvent.click(boxes[0]);
    fireEvent.click(boxes[1]);
    await screen.findByText('2 selected');
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

describe('parity (switch off): BulkActions', () => {
  it('renders its one Actions menu button', () => {
    const { container } = render(
      <BulkActions actions={actions} rows={rows} runtime={{ reload: vi.fn() }} />,
    );
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

describe('parity (switch off): ExportDialog', () => {
  it('whole filtered set', () => {
    render(
      <ExportDialog
        open
        onOpenChange={vi.fn()}
        columns={[
          { id: 'name', label: 'Name' },
          { id: 'email', label: 'Email' },
        ]}
        selectedCount={0}
        onExport={vi.fn()}
      />,
    );
    expect(parityHtml(document.body)).toMatchSnapshot();
  });

  it('ticked rows', () => {
    render(
      <ExportDialog
        open
        onOpenChange={vi.fn()}
        columns={[{ id: 'name', label: 'Name' }]}
        selectedCount={12}
        onExport={vi.fn()}
      />,
    );
    expect(parityHtml(document.body)).toMatchSnapshot();
  });
});

describe('parity (switch off): RecordNav', () => {
  it('shows the circular pager from a list context', async () => {
    nav.params = new URLSearchParams({
      ctx: encodeListQuery({
        page: 0,
        pageSize: 25,
        search: '',
        sort: null,
        filter: null,
        statusView: 'active',
      }),
      i: '2',
    });
    const fetchAt = vi.fn(async (_q: unknown, index: number) => ({ recordId: `r${index}`, total: 120 }));
    const buildHref = (id: string) => `/records/${id}`;
    const { container } = render(<RecordNav fetchAt={fetchAt} buildHref={buildHref} />);
    await screen.findByText('3 / 120');
    expect(parityHtml(container)).toMatchSnapshot();
    nav.params = new URLSearchParams();
  });
});

describe('parity (switch off): FormRow', () => {
  it('a plain value and an input', () => {
    const { container } = render(
      <div>
        <FormRow label="Email">alpha@example.com</FormRow>
        <FormRow label="Name" required>
          <Input aria-label="Name" defaultValue="Alpha Tan" />
        </FormRow>
      </div>,
    );
    expect(parityHtml(container)).toMatchSnapshot();
  });
});
