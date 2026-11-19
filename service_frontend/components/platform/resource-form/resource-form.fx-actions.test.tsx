/**
 * FX-22 / FX-25: `ResourceForm` under the Foundryx UIUX switch takes its red
 * action and More list from `config.fx` (registered with the page header,
 * hidden while a dialog is open), and keeps a tab mounted once shown so its
 * state survives switching. A form without those fields keeps its own
 * buttons and gear. Switch off is pinned by components/fx/__parity__.
 */
import type { ReactNode } from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import type { ResourceAction } from '@/components/platform/resource-list/types';
import { ResourceForm } from './resource-form';
import type { ResourceFormConfig } from './types';

vi.mock('next/navigation', () => ({
  usePathname: vi.fn(() => '/records/rec-1'),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), back: vi.fn() })),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { permissions: [] } }, status: 'authenticated' }),
}));
vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));
vi.mock('@/lib/impersonation-store', () => ({
  useImpersonationSession: () => null,
}));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/hooks/use-deferred-action', () => ({
  useDeferredAction: () => ({ state: { status: 'idle' }, start: vi.fn(async () => ({})), cancel: vi.fn() }),
}));

interface Rec {
  id: string;
  name: string;
}

function makeActions() {
  return {
    duplicate: { id: 'duplicate', label: 'Duplicate', surfaces: { form: true }, run: vi.fn() },
    archive: { id: 'archive', label: 'Archive', surfaces: { form: true }, run: vi.fn() },
    invite: {
      id: 'invite',
      label: 'Send invitation',
      surfaces: { form: true },
      isDisabled: () => true,
      fxDisabledReason: () => 'Already active',
      run: vi.fn(),
    },
  } satisfies Record<string, ResourceAction<Rec>>;
}

function Details() {
  return <input aria-label="Note" />;
}

function config(
  actions: ResourceAction<Rec>[],
  overrides: Partial<ResourceFormConfig<Rec>> = {},
): ResourceFormConfig<Rec> {
  return {
    breadcrumb: [{ label: 'Records', href: '/records' }, { label: 'Record One' }],
    backHref: '/records',
    title: 'Record One',
    entityNoun: 'record',
    tabs: [
      { id: 'details', label: 'Details', render: () => <Details /> },
      { id: 'activity', label: 'Activity', render: () => <div>Activity tab</div> },
    ],
    actions,
    actionRows: [{ id: 'rec-1', name: 'Record One' }],
    editable: true,
    isDirty: false,
    onSave: vi.fn(async () => true),
    onCancel: vi.fn(),
    ...overrides,
  };
}

function On({ children }: { children: ReactNode }) {
  return (
    <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
      {children}
    </FxProvider>
  );
}

async function renderOn(cfg: ResourceFormConfig<Rec>) {
  let utils!: ReturnType<typeof render>;
  await act(async () => {
    utils = render(<ResourceForm config={cfg} />, { wrapper: On });
  });
  return utils;
}

function redAction(): HTMLElement | null {
  return document.querySelector('[data-fx-main-action] button');
}

function headerActions(): HTMLElement {
  return document.querySelector('[data-fx-header-actions]') as HTMLElement;
}

async function switchTab(name: string) {
  const tab = screen.getByRole('tab', { name });
  await act(async () => {
    fireEvent.mouseDown(tab, { button: 0 });
    fireEvent.click(tab);
  });
}

afterEach(() => {
  resetPageActionsForTests();
});

describe('FX-22 red action and More list from config', () => {
  it('an action becomes the red action; the More list and icons fill the header', async () => {
    const a = makeActions();
    await renderOn(
      config([a.duplicate, a.archive, a.invite], {
        fx: {
          mainActionId: 'duplicate',
          fullLabel: (rows) => `Duplicate ${rows[0].name}`,
          moreActionIds: ['archive'],
          iconFor: { duplicate: 'copy' },
        },
      }),
    );
    await waitFor(() => expect(redAction()).not.toBeNull());
    expect(redAction()).toHaveAccessibleName('Duplicate Record One');
    const header = headerActions();
    // Edit and the greyed Send invitation as icons; Archive only in More.
    expect(within(header).getByRole('button', { name: 'Edit' })).toBeInTheDocument();
    expect(within(header).getByRole('button', { name: 'Send invitation' })).toHaveAttribute(
      'aria-disabled',
      'true',
    );
    expect(within(header).queryByRole('button', { name: 'Archive' })).toBeNull();
    expect(within(header).getByRole('button', { name: 'More' })).toBeInTheDocument();
    // The record card's gear and Edit button are gone: nothing twice.
    expect(screen.queryByRole('button', { name: 'Actions' })).toBeNull();

    fireEvent.click(redAction()!);
    expect(a.duplicate.run).toHaveBeenCalledWith(
      [{ id: 'rec-1', name: 'Record One' }],
      expect.objectContaining({ reload: expect.any(Function) }),
    );
  });

  it("'save': Edit at rest, Save while editing, never a second Save button", async () => {
    const cfg = config([], { fx: { mainActionId: 'save' } });
    await renderOn(cfg);
    await waitFor(() => expect(redAction()).toHaveAccessibleName('Edit record'));
    await act(async () => {
      fireEvent.click(redAction()!);
    });
    await waitFor(() => expect(redAction()).toHaveAccessibleName('Save record'));
    expect(screen.getAllByRole('button', { name: 'Save record' })).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(redAction()!);
    });
    expect(cfg.onSave).toHaveBeenCalledTimes(1);
  });

  it('the red action hides while the discard dialog is open', async () => {
    await renderOn(config([], { initialEditing: true, isDirty: true, fx: { mainActionId: 'save' } }));
    await waitFor(() => expect(redAction()).not.toBeNull());
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await screen.findByRole('alertdialog');
    await waitFor(() => expect(redAction()).toBeNull());
  });

  it('a form without fx choices keeps its own Edit button and gear', async () => {
    const a = makeActions();
    await renderOn(config([a.duplicate]));
    expect(redAction()).toBeNull();
    expect(screen.getByRole('button', { name: 'Actions' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Edit/ })).toBeInTheDocument();
  });
});

describe('FX-25 tabs keep their state', () => {
  it('what was typed in a tab is still there after switching away and back', async () => {
    await renderOn(config([]));
    const note = screen.getByRole('textbox', { name: 'Note' });
    fireEvent.change(note, { target: { value: 'half-typed' } });
    await switchTab('Activity');
    await screen.findByText('Activity tab');
    await switchTab('Details');
    expect(screen.getByRole('textbox', { name: 'Note' })).toHaveValue('half-typed');
  });

  it('a per-section editing page (no global Edit) keeps working the same way', async () => {
    await renderOn(config([], { editable: false }));
    const note = screen.getByRole('textbox', { name: 'Note' });
    fireEvent.change(note, { target: { value: 'section edit' } });
    await switchTab('Activity');
    expect(screen.getByText('Activity tab')).toBeVisible();
    await switchTab('Details');
    expect(screen.getByRole('textbox', { name: 'Note' })).toHaveValue('section edit');
    expect(redAction()).toBeNull();
  });
});
