/**
 * Switch-off parity for the foundation follow-up (see parity-utils.ts):
 * shells rendered with the page-level `fx` choices filled in, which the
 * switch-off path must ignore, recorded on the code before the follow-up.
 * - ResourceForm with `fx` (main action, More list, icons), read mode and
 *   after a tab switch;
 * - an embedded list (`embeddedListConfig`) with nothing in it;
 * - the users' "Impersonate" confirm.
 */
import type { ReactElement } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ResourceForm } from '@/components/platform/resource-form/resource-form';
import type { ResourceFormConfig } from '@/components/platform/resource-form/types';
import { ResourceList } from '@/components/platform/resource-list/resource-list';
import { embeddedListConfig } from '@/components/platform/resource-list/embedded-list-config';
import type { ResourceAction } from '@/components/platform/resource-list/types';
import { ConfirmActionDialog } from '@/components/platform/resource-actions/confirm-action-dialog';
import { useUserActions } from '@/app/(protected)/user-management/users/components/use-user-actions';
import type { User } from '@/types/user';
import { parityHtml } from './parity-utils';

vi.mock('next/navigation', () => ({
  usePathname: vi.fn(() => '/records/rec-1'),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), back: vi.fn() })),
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { id: 'me', permissions: [] } },
    status: 'authenticated',
  }),
}));

vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));

vi.mock('@/lib/impersonation-store', () => ({
  useImpersonationSession: () => null,
}));

vi.mock('@/hooks/use-impersonation', () => ({
  useImpersonation: () => ({ start: vi.fn() }),
}));

vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));

interface Rec {
  id: string;
  name: string;
}

const formActions: ResourceAction<Rec>[] = [
  { id: 'duplicate', label: 'Duplicate', surfaces: { form: true }, run: vi.fn() },
  { id: 'archive', label: 'Archive', surfaces: { form: true }, run: vi.fn() },
  {
    id: 'trash',
    label: 'Trash',
    tone: 'destructive',
    surfaces: { form: true },
    deferred: { actionKey: 'records.trash', entityType: 'record' },
  },
];

function formConfig(overrides: Partial<ResourceFormConfig<Rec>> = {}): ResourceFormConfig<Rec> {
  return {
    breadcrumb: [{ label: 'Records', href: '/records' }, { label: 'Record One' }],
    backHref: '/records',
    title: 'Record One',
    tabs: [
      { id: 'details', label: 'Details', render: () => <input aria-label="Note" defaultValue="" /> },
      { id: 'activity', label: 'Activity', render: () => <div>Activity tab</div> },
    ],
    actions: formActions,
    actionRows: [{ id: 'rec-1', name: 'Record One' }],
    editable: true,
    isDirty: false,
    onSave: vi.fn(async () => true),
    onCancel: vi.fn(),
    fx: {
      mainActionId: 'duplicate',
      fullLabel: (rows) => `Duplicate ${rows[0]?.name ?? ''}`,
      iconFor: { duplicate: 'copy', archive: 'move' },
      moreActionIds: ['archive'],
    },
    ...overrides,
  };
}

async function settle(ui: ReactElement): Promise<HTMLElement> {
  let container!: HTMLElement;
  await act(async () => {
    ({ container } = render(ui));
  });
  return container;
}

describe('parity (switch off): ResourceForm with fx choices', () => {
  it('read mode renders as before', async () => {
    const container = await settle(<ResourceForm config={formConfig()} />);
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('after switching to the second tab renders as before', async () => {
    const container = await settle(<ResourceForm config={formConfig()} />);
    const tab = screen.getByRole('tab', { name: 'Activity' });
    await act(async () => {
      fireEvent.mouseDown(tab, { button: 0 });
      fireEvent.click(tab);
    });
    await screen.findByText('Activity tab');
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('edit mode with a save main action renders as before', async () => {
    const container = await settle(
      <ResourceForm
        config={formConfig({
          initialEditing: true,
          fx: { mainActionId: 'save', moreActionIds: ['archive'] },
        })}
      />,
    );
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

describe('parity (switch off): embedded list', () => {
  it('an empty embedded list renders as before', async () => {
    const config = embeddedListConfig<Rec>({
      viewKey: 'records.embedded',
      columns: [{ id: 'name', accessorKey: 'name', header: 'Name' }],
      fetcher: async () => ({ data: [], total: 0, page: 0 }),
      getRowId: (row) => row.id,
      rowHref: (row) => `/records/${row.id}`,
      createLabel: 'Add record',
      onCreate: vi.fn(),
    });
    const { container } = render(<ResourceList hideHeader config={config} />);
    await waitFor(() => expect(container.textContent).not.toBe(''));
    await act(async () => {});
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

function ImpersonateHarness({ rows }: { rows: User[] }) {
  const actions = useUserActions();
  const impersonate = actions.find((a) => a.id === 'impersonate') ?? null;
  return (
    <ConfirmActionDialog pending={impersonate} rows={rows} onClose={vi.fn()} onConfirm={vi.fn()} />
  );
}

describe('parity (switch off): users Impersonate confirm', () => {
  it('names no one, as before', async () => {
    const user = { id: 'u-2', name: 'Jane Doe', email: 'jane@example.com', status: 'ACTIVE' } as unknown as User;
    render(<ImpersonateHarness rows={[user]} />);
    await screen.findByRole('alertdialog');
    await waitFor(() => {
      for (const el of Array.from(
        document.querySelectorAll<HTMLElement>('[data-slot^="alert-dialog-"]'),
      )) {
        expect(el.style.opacity === '' || el.style.opacity === '1').toBe(true);
      }
    });
    expect(parityHtml(document.body)).toMatchSnapshot();
  });
});
