/**
 * The F2 branches in the shared shells, with the Foundryx UIUX switch on:
 * PageHeader shows the registered actions, ConfirmActionDialog speaks the
 * playbook's words, and the dirty guards ask "Discard changes to <name>?".
 * (Switch off is pinned by components/fx/__parity__.)
 */
import type { ReactElement, ReactNode } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { PageHeader } from '@/components/platform/page-header';
import { ConfirmActionDialog } from '@/components/platform/resource-actions/confirm-action-dialog';
import { ConfirmDismissDialog } from '@/components/common/confirm-dismiss-dialog';
import { ResourceForm } from '@/components/platform/resource-form/resource-form';
import type { ResourceFormConfig } from '@/components/platform/resource-form/types';
import type { ResourceAction } from '@/components/platform/resource-list/types';
import {
  resetPageActionsForTests,
  useRegisterMainAction,
  useRegisterOtherActions,
  type FxMainActionSpec,
  type FxOtherActionSpec,
} from './page-actions-context';

vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));
vi.mock('next/navigation', () => ({
  usePathname: vi.fn(() => '/records/rec-1'),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useRouter: vi.fn(() => ({ push: vi.fn(), back: vi.fn(), prefetch: vi.fn() })),
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
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));

function On({ children }: { children: ReactNode }) {
  return (
    <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
      {children}
    </FxProvider>
  );
}

async function settle(ui: ReactElement): Promise<void> {
  await act(async () => {
    render(ui);
  });
}

afterEach(() => resetPageActionsForTests());

const MAIN: FxMainActionSpec = {
  id: 'add',
  label: 'Add contact',
  fullLabel: 'Add contact to Sales',
};
const OTHERS: FxOtherActionSpec[] = [
  { id: 'export', label: 'Export CSV', icon: 'csv-down', onClick: vi.fn() },
];

function Page() {
  useRegisterMainAction(MAIN);
  useRegisterOtherActions(OTHERS);
  return <PageHeader title="Contacts" />;
}

describe('PageHeader (switch on)', () => {
  it('is the frozen fx header with the registered red action and icon actions', async () => {
    await settle(
      <On>
        <Page />
      </On>,
    );
    const header = document.querySelector('[data-fx-header]');
    expect(header).not.toBeNull();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Contacts');
    const actions = header!.querySelector('[data-fx-header-actions]')!;
    const buttons = Array.from(actions.querySelectorAll('button'));
    expect(buttons.map((b) => b.getAttribute('aria-label'))).toEqual([
      'Export CSV',
      'Add contact to Sales',
    ]);
  });
});

interface Rec {
  id: string;
  slug: string;
}

const purge = {
  id: 'purge',
  label: 'Purge tenant',
  tone: 'destructive',
  surfaces: { row: true },
  confirm: {
    title: (r: Rec[]) => `Purge ${r[0].slug}?`,
    description: 'Its users and records are erased and do not come back.',
    input: { expected: () => 'DELETE', fxExpected: (r: Rec[]) => r[0].slug },
  },
  run: vi.fn(),
} as unknown as ResourceAction<Rec>;

describe('ConfirmActionDialog (switch on)', () => {
  it('asks in the playbook words and types the record name instead of a hold', async () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    await settle(
      <On>
        <ConfirmActionDialog
          pending={purge}
          rows={[{ id: 't1', slug: 'acme' }]}
          onClose={onClose}
          onConfirm={onConfirm}
        />
      </On>,
    );
    expect(screen.getByRole('alertdialog')).toHaveAttribute('data-fx-confirm');
    expect(screen.getByRole('heading', { name: 'Purge acme?' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Keep tenant' })).toBeInTheDocument();
    const action = screen.getByRole('button', { name: 'Purge tenant' });
    fireEvent.change(screen.getByLabelText('Type "acme"'), {
      target: { value: 'ACME' },
    });
    fireEvent.click(action);
    expect(onConfirm).toHaveBeenCalledWith(purge);
    expect(onClose).toHaveBeenCalled();
  });
});

function formConfig(): ResourceFormConfig<{ id: string }> {
  return {
    breadcrumb: [{ label: 'Records', href: '/records' }, { label: 'Record One' }],
    backHref: '/records',
    title: 'Record One',
    tabs: [{ id: 'details', label: 'Details', render: () => <div>Details</div> }],
    actions: [],
    actionRows: [{ id: 'rec-1' }],
    editable: true,
    isDirty: true,
    initialEditing: true,
    onSave: vi.fn(async () => true),
    onCancel: vi.fn(),
  };
}

describe('dirty guards (switch on)', () => {
  it('ResourceForm asks "Discard changes to <name>?" and discards on one click', async () => {
    const config = formConfig();
    await settle(
      <On>
        <ResourceForm config={config} />
      </On>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(
      await screen.findByRole('heading', { name: 'Discard changes to Record One?' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Keep editing' })).toHaveFocus();
    fireEvent.click(screen.getByRole('button', { name: 'Discard changes' }));
    expect(config.onCancel).toHaveBeenCalledTimes(1);
  });

  it('ConfirmDismissDialog names the record', async () => {
    const onConfirm = vi.fn();
    await settle(
      <On>
        <ConfirmDismissDialog
          open
          name="Promo November"
          onOpenChange={vi.fn()}
          onConfirm={onConfirm}
          onCancel={vi.fn()}
        />
      </On>,
    );
    expect(
      screen.getByRole('heading', { name: 'Discard changes to Promo November?' }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Discard changes' }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});
