/**
 * Contacts list with the Foundryx UIUX switch on (slice W1-CONTACTS): the
 * typed erase confirm, the bulk panels' words, the export hand-off toast,
 * the header's red action and More menu, Hold to Copy columns, the noun in
 * the list's states, and the done toasts with Undo. The switch-off page is
 * pinned by `__parity__/contacts.parity.test.tsx`.
 */
import { act, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { SettingsProvider } from '@/providers/settings-provider';
import { ConfirmActionDialog } from '@/components/platform/resource-actions/confirm-action-dialog';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { resetPageActionsForTests, usePageActions } from '@/components/fx/actions/page-actions-context';
import { fxListStateText } from '@/components/fx/list/fx-list-state';
import { fxCardLayout } from '@/components/fx/list/fx-phone-cards';
import type { ContactListItem, ContactSegment, ContactTag, WorkspaceMember } from '@/types/omnichannel';

const h = vi.hoisted(() => ({
  toastCalls: [] as unknown[][],
  reportCalls: [] as unknown[][],
  push: vi.fn(),
  bulkAssign: vi.fn(),
  bulkTags: vi.fn(),
  bulkLifecycle: vi.fn(),
  segmentRemove: vi.fn(),
  createSegment: vi.fn(),
  permissions: new Set<string>(),
  workspaces: [] as { id: string; name: string }[],
  lastConfig: null as unknown,
}));

vi.mock('next-themes', () => ({ useTheme: () => ({ theme: 'light', setTheme: vi.fn(), resolvedTheme: 'light' }) }));
vi.mock('@/lib/toast', () => {
  const rec =
    (kind: string) =>
    (...args: unknown[]) => {
      h.toastCalls.push([kind, ...args]);
      return 'toast-id';
    };
  return {
    toast: {
      success: rec('success'),
      error: rec('error'),
      info: rec('info'),
      warning: rec('warning'),
      message: rec('message'),
      custom: rec('custom'),
      dismiss: rec('dismiss'),
      fxDone: rec('fxDone'),
    },
  };
});
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: h.push, replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => '/omnichannel/contacts',
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: (key: string) => h.permissions.has(key), ready: true, permissions: h.permissions }),
}));
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDate: (v: string) => v, formatDateTime: (v: string) => v, formatTime: (v: string) => v }),
}));
vi.mock('@/hooks/use-terminology', () => ({
  useTerminology: () => ({ ready: true, label: (k: string) => k, labelPlural: (k: string) => k, t: (k: string) => k, refetch: vi.fn() }),
}));
vi.mock('@/hooks/use-contacts', () => ({
  useActiveWorkspace: () => ({ workspaceId: 'wsp-1', workspaces: h.workspaces, ready: true, setWorkspaceId: vi.fn() }),
}));

const SEGMENTS: ContactSegment[] = [
  {
    id: 'seg-1',
    workspaceId: 'wsp-1',
    name: 'VIP customers',
    description: null,
    filter: { kind: 'group', combinator: 'and', rules: [] },
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  },
];
const TAGS: ContactTag[] = [
  { id: 'tag-1', workspaceId: 'wsp-1', name: 'VIP', emoji: null, color: null, description: null, contactsCount: 0, createdAt: 'x' },
  { id: 'tag-2', workspaceId: 'wsp-1', name: 'Raya', emoji: null, color: null, description: null, contactsCount: 0, createdAt: 'x' },
];
const MEMBERS: WorkspaceMember[] = [
  { id: 'm-1', userId: 'u-1', name: 'Nurul Huda', email: 'nurul@example.com', status: 'ACTIVE' as WorkspaceMember['status'], assignedAt: 'x' },
];
const STAGES = [
  { id: 'st-1', key: 'lead', label: 'Lead', color: '#999', isInitial: true, isTerminal: false, isArchived: false },
  { id: 'st-2', key: 'customer', label: 'Customer', color: '#0a0', isInitial: false, isTerminal: false, isArchived: false },
];

vi.mock('@/hooks/use-contact-segments', () => ({
  useContactSegments: () => ({ segments: SEGMENTS, loading: false, create: h.createSegment, update: vi.fn(), refresh: vi.fn() }),
}));
vi.mock('@/hooks/use-contact-tags', () => ({ useContactTags: () => ({ tags: TAGS }) }));
vi.mock('@/hooks/use-contact-fields', () => ({ useContactFields: () => ({ fields: [] }) }));
vi.mock('@/hooks/use-contact-lifecycle-stages', () => ({ useContactLifecycleStages: () => ({ stages: STAGES }) }));
vi.mock('@/hooks/use-workspace-members', () => ({ useWorkspaceMembers: () => ({ members: MEMBERS }) }));
vi.mock('@/hooks/use-contact-bulk', () => ({
  useContactBulk: () => ({ busy: false, assign: h.bulkAssign, tags: h.bulkTags, lifecycle: h.bulkLifecycle }),
  reportBulkResult: (...args: unknown[]) => {
    h.reportCalls.push(args.slice(0, 2));
  },
}));
vi.mock('@/services/channel-service', () => ({ channelService: { listByWorkspace: vi.fn().mockResolvedValue([]) } }));
vi.mock('@/services/contact-service', () => ({
  contactService: { list: vi.fn().mockResolvedValue({ data: [], total: 0, page: 0 }), exportContacts: vi.fn(), eraseContact: vi.fn() },
}));
vi.mock('@/services/contact-segment-service', () => ({
  contactSegmentService: { remove: (...args: unknown[]) => h.segmentRemove(...args) },
}));

function contact(over: Partial<ContactListItem> = {}): ContactListItem {
  return {
    id: 'cnt-1', tenantId: 't1', workspaceId: 'wsp-1', name: 'Aisyah binti Rahman', firstName: 'Aisyah',
    lastName: 'Rahman', phone: '+60123456789', email: 'aisyah@example.com', language: null, countryCode: null,
    avatarUrl: null, assignedUserId: null, assignedUserName: null, status: 'OPEN', priority: 'MEDIUM',
    channelId: null, channelType: 'WHATSAPP', cswExpiresAt: null, windowExpiresAt: null,
    humanAgentExpiresAt: null, lastIncomingMessageAt: null, lastMessageAt: null, lastMessagePreview: null,
    unreadCount: 0, customFields: {}, tags: [], lifecycle: null, createdAt: '2026-01-01T00:00:00Z',
    channels: [], messageCount: 214, fileCount: 12,
    ...over,
  } as ContactListItem;
}
const ROWS = [
  contact({ assignedUserId: 'u-9', tags: [{ id: 'tag-1', name: 'VIP', emoji: null, color: null }] }),
  contact({ id: 'cnt-2', name: 'Lim Wei Jie' }),
];

vi.mock('@/components/platform/resource-list', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/platform/resource-list')>();
  function ListProbe({ config }: { config: ResourceListConfig<ContactListItem> }) {
    h.lastConfig = config;
    return (
      <div data-testid="resource-list">
        <button
          type="button"
          onClick={() =>
            config.onFilterChange?.({
              kind: 'group',
              combinator: 'and',
              rules: [{ kind: 'condition', field: 'name', operator: 'contains', value: 'a' }],
            } as never)
          }
        >
          probe-filter
        </button>
        {config.actions
          .filter((a) => a.surfaces.bulk)
          .map((a) => (
            <button type="button" key={a.id} onClick={() => a.run?.(ROWS, { reload: vi.fn() })}>
              {`probe-${a.id}`}
            </button>
          ))}
      </div>
    );
  }
  return { ...actual, ResourceList: ListProbe };
});

import ContactsPage from './page';
import { BulkLifecycleDialog } from './components/bulk-lifecycle-dialog';
import { BulkTagsDialog } from './components/bulk-tags-dialog';
import {
  fxAssignUndoPlan,
  fxBulkDoneWhat,
  fxBulkPanelWords,
  fxExportPendingWords,
  fxTagsUndoPlan,
} from './components/contacts-fx';
import { fxExportPendingToast } from './components/export-pending-toast';
import { CONTACTS_FX } from './components/use-contacts-list-config';
import { useContactsFxDone } from './components/use-contacts-fx-done';
import { contactEraseExpected, contactErasedWords, useContactEraseAction } from './components/use-contact-erase-action';

function Fx({ children }: { children: ReactNode }) {
  return (
    <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
      <SettingsProvider>{children}</SettingsProvider>
    </FxProvider>
  );
}

function HeaderProbe() {
  const page = usePageActions();
  return <span data-testid="main-action">{page.main?.label ?? ''}</span>;
}

beforeEach(() => {
  h.toastCalls.length = 0;
  h.reportCalls.length = 0;
  h.permissions = new Set(['contacts.read', 'contacts.manage', 'segments.manage', 'contacts.import', 'contacts.erase']);
  h.workspaces = [];
  resetPageActionsForTests();
});
afterEach(() => resetPageActionsForTests());

describe('erase: typed confirm with the contact name', () => {
  it('asks for the name, else phone, email, or ERASE', () => {
    expect(contactEraseExpected(contact())).toBe('Aisyah binti Rahman');
    expect(contactEraseExpected(contact({ name: '  ' }))).toBe('+60123456789');
    expect(contactEraseExpected(contact({ name: '', phone: null }))).toBe('aisyah@example.com');
    expect(contactEraseExpected(contact({ name: '', phone: null, email: null }))).toBe('ERASE');
  });

  it('unlocks Erase contact only for the name, ignoring case and spaces', async () => {
    let action: ReturnType<typeof useContactEraseAction> | null = null;
    function Probe() {
      action = useContactEraseAction('row', vi.fn());
      return null;
    }
    const onConfirm = vi.fn();
    const rows = [contact()];
    const { rerender } = render(
      <Fx>
        <Probe />
      </Fx>,
    );
    rerender(
      <Fx>
        <Probe />
        <ConfirmActionDialog pending={action} rows={rows} onClose={vi.fn()} onConfirm={onConfirm} />
      </Fx>,
    );
    const dialog = await screen.findByRole('alertdialog');
    expect(within(dialog).getByText('Erase Aisyah binti Rahman?')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Keep contact' })).toBeInTheDocument();
    const input = within(dialog).getByLabelText('Type "Aisyah binti Rahman"');
    const erase = within(dialog).getByRole('button', { name: 'Erase contact' });

    for (const wrong of ['ERASE', 'Aisyah', 'Aisyah binti Rahmann', 'Lim Wei Jie']) {
      fireEvent.change(input, { target: { value: wrong } });
      expect(erase).toHaveAttribute('aria-disabled', 'true');
      fireEvent.click(erase);
    }
    expect(onConfirm).not.toHaveBeenCalled();
    // No press and hold: a typed confirm replaces it.
    expect(dialog.querySelector('[data-fx-hold]')).toBeNull();

    fireEvent.change(input, { target: { value: '  aisyahBINTI   rahman ' } });
    expect(erase).not.toHaveAttribute('aria-disabled');
    fireEvent.click(erase);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('says who was erased with what, by whom, with no Undo', () => {
    expect(contactErasedWords('Aisyah binti Rahman', 214, 1)).toEqual({
      what: 'Aisyah binti Rahman erased',
      howMany: 'with 214 messages and 1 file',
    });
  });
});

describe('bulk panels name their field', () => {
  it('words', () => {
    expect(fxBulkPanelWords('lifecycle', 12).action).toBe("Update 12 contacts' lifecycle");
    expect(fxBulkPanelWords('lifecycle', 1).action).toBe("Update 1 contact's lifecycle");
    expect(fxBulkPanelWords('assign', 1240).action).toBe("Update 1,240 contacts' assignee");
    expect(fxBulkPanelWords('add-tags', 3).action).toBe('Add tags to 3 contacts');
    expect(fxBulkPanelWords('remove-tags', 1).action).toBe('Remove tags from 1 contact');
    expect(fxBulkPanelWords('lifecycle', 2).title).toBe('Lifecycle stage');
  });

  it('the lifecycle panel names its field and greys its action until a stage is picked', () => {
    render(
      <Fx>
        <BulkLifecycleDialog open onOpenChange={vi.fn()} stages={STAGES} count={12} onConfirm={vi.fn()} />
      </Fx>,
    );
    const panel = screen.getByRole('dialog');
    expect(panel).toHaveAttribute('data-fx-bulk-panel', 'lifecycle');
    expect(within(panel).getByText('Lifecycle stage')).toBeInTheDocument();
    expect(within(panel).getByRole('button', { name: "Update 12 contacts' lifecycle" })).toHaveAttribute(
      'aria-disabled',
      'true',
    );
  });

  it('the remove tags panel', () => {
    render(
      <Fx>
        <BulkTagsDialog open onOpenChange={vi.fn()} mode="remove" tags={TAGS} count={2} onConfirm={vi.fn()} />
      </Fx>,
    );
    expect(screen.getByText('Tags to remove', { selector: 'h2' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Remove tags from 2 contacts' })).toBeInTheDocument();
  });
});

describe('export hand-off toast', () => {
  it('words', () => {
    expect(fxExportPendingWords(1240)).toBe('The export of 1,240 contacts is still running. It will be in Jobs.');
    expect(fxExportPendingWords(1)).toBe('The export of 1 contact is still running. It will be in Jobs.');
    expect(fxExportPendingWords(null)).toBe('The export of the contacts is still running. It will be in Jobs.');
  });

  it('View jobs opens the Jobs sheet', () => {
    const openJobs = vi.fn();
    fxExportPendingToast(12, openJobs);
    const [kind, words, options] = h.toastCalls[0] as [string, string, { action: { label: string; onClick: () => void } }];
    expect(kind).toBe('info');
    expect(words).toBe('The export of 12 contacts is still running. It will be in Jobs.');
    expect(options.action.label).toBe('View jobs');
    options.action.onClick();
    expect(openJobs).toHaveBeenCalled();
  });
});

describe('list config under the switch', () => {
  it('Hold to Copy on name, phone and email; noun; phone cards', () => {
    expect(CONTACTS_FX.copyable).toEqual(['name', 'phone', 'email']);
    expect(CONTACTS_FX.noun).toBe('contacts');
    expect(fxListStateText('no-match', { noun: CONTACTS_FX.noun!, title: 'Contacts', search: 'tan' }).line).toBe(
      'No contacts match "tan".',
    );
    expect(fxListStateText('error', { noun: CONTACTS_FX.noun!, title: 'Contacts' }).line).toBe(
      "Couldn't load the contacts.",
    );
    const ids = ['select', 'name', 'phone', 'email', 'lifecycle', 'tags', 'assignee', 'channel', 'lastMessageAt', 'createdAt', 'actions'];
    const layout = fxCardLayout(ids, {
      primaryId: 'name',
      structural: new Set(['select', 'actions']),
      phoneHidden: new Set(),
      statusIds: new Set(['lifecycle']),
      cardLines: CONTACTS_FX.cardLines,
    });
    expect(layout).toEqual({
      top: ['name'],
      status: ['lifecycle'],
      lines: [['phone', 'email'], ['assignee', 'channel'], ['tags'], ['lastMessageAt']],
      info: [],
    });
  });

  it('hands the shell the fx config and leaves Create to the page header', async () => {
    render(
      <Fx>
        <ContactsPage />
      </Fx>,
    );
    await screen.findByTestId('resource-list');
    const config = h.lastConfig as ResourceListConfig<ContactListItem>;
    expect(config.fx).toBe(CONTACTS_FX);
    expect(config.onCreate).toBeUndefined();
    expect(config.actions.find((a) => a.id === 'erase-contact')?.confirm?.fxKeepLabel).toBe('Keep contact');
  });
});

describe('page header under the switch', () => {
  it('red Add contact, More holding Save as segment and Manage segments, workspace as branch picker', async () => {
    h.workspaces = [
      { id: 'wsp-1', name: 'Kedai Bunga HQ' },
      { id: 'wsp-2', name: 'Kedai Bunga Penang' },
    ];
    render(
      <Fx>
        <HeaderProbe />
        <ContactsPage />
      </Fx>,
    );
    await screen.findByTestId('resource-list');
    await waitFor(() => expect(screen.getByTestId('main-action')).toHaveTextContent('Add contact'));
    expect(screen.getByRole('button', { name: 'Add contact' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Add contact' }));
    expect(h.push).toHaveBeenCalledWith('/omnichannel/contacts/new');

    // The old text buttons are gone; the two segment actions are in More.
    expect(screen.queryByRole('button', { name: 'Manage segments' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('probe-filter'));
    const more = await screen.findByRole('button', { name: 'More' });
    fireEvent.pointerDown(more, { button: 0, ctrlKey: false });
    const items = await screen.findAllByRole('menuitem');
    expect(items.map((i) => i.textContent)).toEqual(['Save as segment', 'Manage segments']);

    const picker = document.querySelector('[data-fx-branch-picker]');
    expect(picker).not.toBeNull();
    expect(picker?.textContent).toContain('Workspace');
  });

  it('no Add contact without contacts.manage', async () => {
    h.permissions = new Set(['contacts.read']);
    render(
      <Fx>
        <HeaderProbe />
        <ContactsPage />
      </Fx>,
    );
    await screen.findByTestId('resource-list');
    expect(screen.getByTestId('main-action')).toHaveTextContent('');
    expect(screen.queryByRole('button', { name: 'More' })).not.toBeInTheDocument();
  });
});

describe('done toasts with Undo', () => {
  it('assign: named, with Undo that puts the old assignees back', async () => {
    h.bulkAssign.mockResolvedValue({ ok: ['cnt-1', 'cnt-2'], failed: [] });
    render(
      <Fx>
        <ContactsPage />
      </Fx>,
    );
    await screen.findByTestId('resource-list');
    fireEvent.click(screen.getByText('probe-bulk-assign'));
    expect(await screen.findByText('Assignee', { selector: 'h2' })).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: "Update 2 contacts' assignee" }));
    });
    await waitFor(() => expect(h.toastCalls.some((c) => c[0] === 'fxDone')).toBe(true));
    const done = h.toastCalls.find((c) => c[0] === 'fxDone')![1] as { what: string; seconds?: number; undo?: () => void };
    expect(done.what).toBe('2 contacts unassigned');
    expect(done.seconds).toBe(5);
    h.bulkAssign.mockClear();
    h.bulkAssign.mockResolvedValue({ ok: ['cnt-1'], failed: [] });
    await act(async () => {
      done.undo!();
    });
    expect(h.bulkAssign).toHaveBeenCalledWith(['cnt-1'], 'u-9');
    expect(h.reportCalls).toEqual([]);
  });

  it('lifecycle: toast without Undo', async () => {
    h.bulkLifecycle.mockResolvedValue({ ok: ['cnt-1'], failed: [] });
    render(
      <Fx>
        <ContactsPage />
      </Fx>,
    );
    await screen.findByTestId('resource-list');
    // One ticked row is named in the toast.
    const config = h.lastConfig as ResourceListConfig<ContactListItem>;
    act(() => {
      config.actions.find((a) => a.id === 'move-lifecycle')!.run!([ROWS[0]], { reload: vi.fn() });
    });
    expect(await screen.findByText('Lifecycle stage', { selector: 'h2' })).toBeInTheDocument();
    expect(fxBulkDoneWhat('lifecycle', [ROWS[0]], 'Customer')).toBe('Aisyah binti Rahman moved to Customer');
  });

  it('a change where some failed keeps the per-contact report; Save as segment has Undo', async () => {
    const bulk = { busy: false, assign: h.bulkAssign, tags: h.bulkTags, lifecycle: h.bulkLifecycle };
    const refresh = vi.fn();
    const { result } = renderHook(() => useContactsFxDone(bulk, 'wsp-1', refresh));
    result.current.reportBulk({
      kind: 'add-tags',
      rows: ROWS,
      result: { ok: ['cnt-1'], failed: [{ id: 'cnt-2', error: 'Nope' }] },
      target: ['VIP'],
      sent: { kind: 'tags', mode: 'add', tagIds: ['tag-1'] },
      reload: vi.fn(),
    });
    expect(h.reportCalls).toEqual([[{ ok: ['cnt-1'], failed: [{ id: 'cnt-2', error: 'Nope' }] }, 'tagged']]);
    expect(h.toastCalls).toEqual([]);

    h.segmentRemove.mockResolvedValue(undefined);
    result.current.reportSegmentSaved('Raya buyers', { id: 'seg-9' });
    const done = h.toastCalls[0][1] as { what: string; undo?: () => void; seconds?: number };
    expect(done.what).toBe('Segment "Raya buyers" saved');
    expect(done.seconds).toBe(5);
    await act(async () => {
      done.undo!();
    });
    expect(h.segmentRemove).toHaveBeenCalledWith('wsp-1', 'seg-9');
    await waitFor(() => expect(refresh).toHaveBeenCalled());
  });

  it('undo plans', () => {
    expect(fxAssignUndoPlan(ROWS, ['cnt-1', 'cnt-2'], 'u-1')).toEqual([
      { ids: ['cnt-1'], assigneeUserId: 'u-9' },
      { ids: ['cnt-2'], assigneeUserId: null },
    ]);
    expect(fxAssignUndoPlan(ROWS, ['cnt-2'], null)).toEqual([]);
    expect(fxTagsUndoPlan(ROWS, ['cnt-1', 'cnt-2'], 'add', ['tag-1', 'tag-2'])).toEqual([
      { ids: ['cnt-2'], mode: 'remove', tagIds: ['tag-1'] },
      { ids: ['cnt-1', 'cnt-2'], mode: 'remove', tagIds: ['tag-2'] },
    ]);
    expect(fxTagsUndoPlan(ROWS, ['cnt-1', 'cnt-2'], 'remove', ['tag-1'])).toEqual([
      { ids: ['cnt-1'], mode: 'add', tagIds: ['tag-1'] },
    ]);
    expect(fxBulkDoneWhat('add-tags', ROWS, ['VIP', 'Raya'])).toBe('Tags "VIP", "Raya" added to 2 contacts');
    expect(fxBulkDoneWhat('assign', [ROWS[0]], 'Nurul Huda')).toBe('Aisyah binti Rahman assigned to Nurul Huda');
  });
});
