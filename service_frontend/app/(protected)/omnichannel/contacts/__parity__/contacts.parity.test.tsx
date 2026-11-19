/**
 * Switch-off parity for the Contacts list page (Foundryx UIUX, slice
 * W1-CONTACTS). Recorded on the code BEFORE the slice changed anything, so a
 * later change that alters what a user sees or gets with the switch off fails
 * here. A change that needs one of these snapshots updated is wrong by
 * definition: fix the code, never the snapshot.
 *
 * Covers the page-local pieces the slice branches: the page header and its
 * buttons, the three bulk dialogs, Save as segment, the export hand-off toast,
 * the erase action (its confirm words and toasts), the bulk done toasts the
 * page reports, and the list cells.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { SettingsProvider } from '@/providers/settings-provider';
import type {
  ContactListItem,
  ContactSegment,
  ContactTag,
  WorkspaceMember,
} from '@/types/omnichannel';
import { parityHtml as baseParityHtml } from '@/components/fx/__parity__/parity-utils';

/** React 19's `_r_N_` ids renamed in order, so test order cannot shift them. */
function parityHtml(root: Element): string {
  const seen = new Map<string, string>();
  return baseParityHtml(root)
    .replace(/_r_[0-9a-z]+_/g, (id) => {
      if (!seen.has(id)) seen.set(id, `_rid${seen.size}_`);
      return seen.get(id) as string;
    })
    .replace(/(animation|transition)-duration:\s*[0-9.]+m?s/g, '$1-duration: <t>');
}

/** A call log with functions named, not run, so it can be snapshotted. */
function plain(value: unknown): unknown {
  return JSON.parse(
    JSON.stringify(value, (_k, v) => (typeof v === 'function' ? '[fn]' : v)),
  );
}

const h = vi.hoisted(() => ({
  toastCalls: [] as unknown[],
  reportCalls: [] as unknown[],
  push: vi.fn(),
  bulkAssign: vi.fn(),
  bulkTags: vi.fn(),
  bulkLifecycle: vi.fn(),
  erase: vi.fn(),
  createSegment: vi.fn(),
  permissions: new Set<string>(),
  workspaces: [] as { id: string; name: string }[],
  lastConfig: null as unknown,
}));

vi.mock('@/lib/toast', () => {
  const rec = (kind: string) => (...args: unknown[]) => {
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
  useDatetime: () => ({
    formatDate: (v: string) => v,
    formatDateTime: (v: string) => v,
    formatTime: (v: string) => v,
  }),
}));
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
    workspaces: h.workspaces,
    ready: true,
    setWorkspaceId: vi.fn(),
  }),
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
  {
    id: 'tag-1',
    workspaceId: 'wsp-1',
    name: 'VIP',
    emoji: null,
    color: '#FF5A00',
    description: null,
    contactsCount: 0,
    createdAt: '2026-01-01T00:00:00Z',
  },
];
const MEMBERS: WorkspaceMember[] = [
  {
    id: 'm-1',
    userId: 'u-1',
    name: 'Nurul Huda',
    email: 'nurul@example.com',
    status: 'ACTIVE' as WorkspaceMember['status'],
    assignedAt: '2026-01-01T00:00:00Z',
  },
];
const STAGES = [
  { id: 'st-1', key: 'lead', label: 'Lead', color: '#999', isInitial: true, isTerminal: false, isArchived: false },
  { id: 'st-2', key: 'customer', label: 'Customer', color: '#0a0', isInitial: false, isTerminal: false, isArchived: false },
];

vi.mock('@/hooks/use-contact-segments', () => ({
  useContactSegments: () => ({
    segments: SEGMENTS,
    loading: false,
    create: h.createSegment,
    update: vi.fn(),
    refresh: vi.fn(),
  }),
}));
vi.mock('@/hooks/use-contact-tags', () => ({ useContactTags: () => ({ tags: TAGS }) }));
vi.mock('@/hooks/use-contact-fields', () => ({ useContactFields: () => ({ fields: [] }) }));
vi.mock('@/hooks/use-contact-lifecycle-stages', () => ({
  useContactLifecycleStages: () => ({ stages: STAGES }),
}));
vi.mock('@/hooks/use-workspace-members', () => ({ useWorkspaceMembers: () => ({ members: MEMBERS }) }));
vi.mock('@/hooks/use-contact-bulk', () => ({
  useContactBulk: () => ({ busy: false, assign: h.bulkAssign, tags: h.bulkTags, lifecycle: h.bulkLifecycle }),
  reportBulkResult: (...args: unknown[]) => {
    h.reportCalls.push(args.slice(0, 2));
  },
}));
vi.mock('@/hooks/use-segment-delete-controller', () => ({}));
vi.mock('@/services/channel-service', () => ({
  channelService: { listByWorkspace: vi.fn().mockResolvedValue([]) },
}));
vi.mock('@/services/contact-service', () => ({
  contactService: {
    list: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    exportContacts: vi.fn(),
    eraseContact: (...args: unknown[]) => h.erase(...args),
  },
}));

function contact(over: Partial<ContactListItem> = {}): ContactListItem {
  return {
    id: 'cnt-1', tenantId: 't1', workspaceId: 'wsp-1', name: 'Aisyah binti Rahman', firstName: 'Aisyah',
    lastName: 'Rahman', phone: '+60123456789', email: 'aisyah@example.com', language: null, countryCode: null,
    avatarUrl: null, assignedUserId: null, assignedUserName: null, status: 'OPEN', priority: 'MEDIUM',
    channelId: null, channelType: 'WHATSAPP', cswExpiresAt: null, windowExpiresAt: null,
    humanAgentExpiresAt: null, lastIncomingMessageAt: null, lastMessageAt: null, lastMessagePreview: null,
    unreadCount: 0, customFields: {},
    tags: [{ id: 'tag-1', name: 'VIP', emoji: null, color: '#FF5A00' }],
    lifecycle: { statusId: 'st-1', key: 'lead', label: 'Lead', color: '#999', isWon: false, isLost: false },
    createdAt: '2026-01-01T00:00:00Z',
    channels: [{ channelId: 'ch-1', channelType: 'WHATSAPP', name: 'Kedai WhatsApp' }],
    messageCount: 214, fileCount: 12,
    ...over,
  } as ContactListItem;
}
const ROWS = [contact(), contact({ id: 'cnt-2', name: 'Lim Wei Jie', tags: [] })];

// The list shell is shared (parity-pinned by the foundation); here it only
// exposes the page's config so the page's own wiring can be driven.
vi.mock('@/components/platform/resource-list', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/platform/resource-list')>();
  function ListProbe({ config }: { config: ResourceListConfig<ContactListItem> }) {
    h.lastConfig = config;
    return (
      <div data-testid="resource-list">
        <button type="button" onClick={() => config.onFilterChange?.({ kind: 'group', combinator: 'and', rules: [{ kind: 'condition', field: 'name', operator: 'contains', value: 'a' }] } as never)}>
          probe-filter
        </button>
        {config.actions
          .filter((a) => a.surfaces.bulk)
          .map((a) => (
            <button
              type="button"
              key={a.id}
              onClick={() => a.run?.(ROWS, { reload: () => h.toastCalls.push(['reload', a.id]) })}
            >
              {`probe-${a.id}`}
            </button>
          ))}
      </div>
    );
  }
  return { ...actual, ResourceList: ListProbe };
});

import ContactsPage from '../page';
import { BulkAssignDialog } from '../components/bulk-assign-dialog';
import { BulkLifecycleDialog } from '../components/bulk-lifecycle-dialog';
import { BulkTagsDialog } from '../components/bulk-tags-dialog';
import { SaveSegmentDialog } from '../components/save-segment-dialog';
import { exportPendingToast } from '../components/export-pending-toast';
import { useContactEraseAction } from '../components/use-contact-erase-action';
import { ContactChannelsCell } from '../components/contact-channels-cell';
import { ContactLifecycleCell } from '../components/contact-lifecycle-cell';
import { ContactTagsCell } from '../components/contact-tags-cell';

beforeEach(() => {
  h.toastCalls.length = 0;
  h.reportCalls.length = 0;
  h.permissions = new Set(['contacts.read', 'contacts.manage', 'segments.manage', 'contacts.import', 'contacts.erase']);
  h.workspaces = [];
});

describe('Contacts list, switch off: page', () => {
  it('renders the header, workspace picker and segment buttons as before', async () => {
    h.workspaces = [
      { id: 'wsp-1', name: 'Kedai Bunga HQ' },
      { id: 'wsp-2', name: 'Kedai Bunga Penang' },
    ];
    const { container } = render(
      <SettingsProvider>
        <ContactsPage />
      </SettingsProvider>,
    );
    await screen.findByTestId('resource-list');
    fireEvent.click(screen.getByText('probe-filter'));
    await screen.findByRole('button', { name: 'Save as segment' });
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('keeps the list config it hands the shell', async () => {
    render(
      <SettingsProvider>
        <ContactsPage />
      </SettingsProvider>,
    );
    await screen.findByTestId('resource-list');
    const config = h.lastConfig as ResourceListConfig<ContactListItem>;
    expect(
      plain({
        viewKey: config.viewKey,
        columns: config.columns.map((c) => c.id),
        exportColumns: config.exportColumns,
        actions: config.actions.map((a) => ({
          id: a.id,
          label: typeof a.label === 'function' ? a.label(ROWS) : a.label,
          tone: a.tone,
          surfaces: a.surfaces,
          permission: a.permission,
        })),
        searchPlaceholder: config.searchPlaceholder,
        searchHints: config.searchHints,
        defaultSort: config.defaultSort,
        enableStatusViews: config.enableStatusViews,
        segments: config.segments,
        exportFilename: config.exportFilename,
        createLabel: config.createLabel,
        createPermission: config.createPermission,
        hasOnCreate: typeof config.onCreate === 'function',
        importer: config.importer,
        pageDescription: config.pageDescription ?? null,
        pageTitle: config.pageTitle ?? null,
      }),
    ).toMatchSnapshot();
  });

  it('opens each bulk dialog and reports its result the same way', async () => {
    h.bulkAssign.mockResolvedValue({ ok: ['cnt-1', 'cnt-2'], failed: [] });
    h.bulkTags.mockResolvedValue({ ok: ['cnt-1'], failed: [{ id: 'cnt-2', error: 'Nope' }] });
    h.bulkLifecycle.mockResolvedValue({ ok: ['cnt-1', 'cnt-2'], failed: [] });
    render(
      <SettingsProvider>
        <ContactsPage />
      </SettingsProvider>,
    );
    await screen.findByTestId('resource-list');

    fireEvent.click(screen.getByText('probe-bulk-assign'));
    const assignDialog = await screen.findByRole('dialog');
    expect(parityHtml(assignDialog)).toMatchSnapshot('assign dialog');
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Assign' }));
    });
    await waitFor(() => expect(h.bulkAssign).toHaveBeenCalledWith(['cnt-1', 'cnt-2'], null));

    fireEvent.click(screen.getByText('probe-move-lifecycle'));
    const lifecycleDialog = await screen.findByRole('dialog');
    expect(parityHtml(lifecycleDialog)).toMatchSnapshot('lifecycle dialog');
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

    fireEvent.click(screen.getByText('probe-add-tags'));
    const tagsDialog = await screen.findByRole('dialog');
    expect(parityHtml(tagsDialog)).toMatchSnapshot('add tags dialog');

    expect(plain({ reports: h.reportCalls, toasts: h.toastCalls })).toMatchSnapshot('reports');
  });
});

describe('Contacts list, switch off: dialogs', () => {
  it('bulk assign', () => {
    render(<BulkAssignDialog open onOpenChange={vi.fn()} members={MEMBERS} count={3} onConfirm={vi.fn()} />);
    expect(parityHtml(document.body)).toMatchSnapshot();
  });

  it('bulk lifecycle', () => {
    render(<BulkLifecycleDialog open onOpenChange={vi.fn()} stages={STAGES} count={1} onConfirm={vi.fn()} />);
    expect(parityHtml(document.body)).toMatchSnapshot();
  });

  it('bulk tags, add and remove', () => {
    const { rerender } = render(
      <BulkTagsDialog open onOpenChange={vi.fn()} mode="add" tags={TAGS} count={12} onConfirm={vi.fn()} />,
    );
    expect(parityHtml(document.body)).toMatchSnapshot('add');
    rerender(<BulkTagsDialog open onOpenChange={vi.fn()} mode="remove" tags={TAGS} count={12} onConfirm={vi.fn()} />);
    expect(parityHtml(document.body)).toMatchSnapshot('remove');
  });

  it('save as segment, and its toast', async () => {
    const onSave = vi.fn().mockResolvedValue({ id: 'seg-9' });
    const onOpenChange = vi.fn();
    render(
      <SaveSegmentDialog
        open
        onOpenChange={onOpenChange}
        filter={{ kind: 'group', combinator: 'and', rules: [] }}
        onSave={onSave}
      />,
    );
    expect(parityHtml(document.body)).toMatchSnapshot('dialog');
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Raya buyers' } });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Save segment' }));
    });
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(plain({ saved: onSave.mock.calls, toasts: h.toastCalls })).toMatchSnapshot('toast');
  });
});

describe('Contacts list, switch off: toasts and actions', () => {
  it('export hand-off toast', () => {
    const push = vi.fn();
    exportPendingToast(push);
    expect(plain(h.toastCalls)).toMatchSnapshot();
    const options = (h.toastCalls[0] as [string, string, { action: { onClick: () => void } }])[2];
    options.action.onClick();
    expect(push).toHaveBeenCalledWith('/jobs');
  });

  it('erase action words and toasts', async () => {
    let action: ReturnType<typeof useContactEraseAction> | null = null;
    const onErased = vi.fn();
    function Probe() {
      action = useContactEraseAction('row', onErased);
      return null;
    }
    render(<Probe />);
    const a = action as unknown as ReturnType<typeof useContactEraseAction>;
    const rows = [contact()];
    const confirm = a.confirm!;
    const resolve = (v: unknown) => (typeof v === 'function' ? (v as (r: unknown) => unknown)(rows) : v);
    expect(
      plain({
        id: a.id,
        label: a.label,
        tone: a.tone,
        permission: a.permission,
        surfaces: a.surfaces,
        title: resolve(confirm.title),
        description: resolve(confirm.description),
        confirmLabel: resolve(confirm.confirmLabel),
        expected: confirm.input?.expected(rows),
        hint: confirm.input?.hint?.(rows),
      }),
    ).toMatchSnapshot('words');

    h.erase.mockResolvedValueOnce({ contactId: 'cnt-1', erasedAt: 'x', messages: 214, files: 12 });
    await a.run!(rows, { reload: vi.fn() });
    h.erase.mockRejectedValueOnce(new Error('boom'));
    await a.run!(rows, { reload: vi.fn() });
    expect(plain({ toasts: h.toastCalls, erased: onErased.mock.calls.length })).toMatchSnapshot('toasts');
  });

  it('list cells', () => {
    const row = contact();
    const { container } = render(
      <div>
        <ContactLifecycleCell lifecycle={row.lifecycle} />
        <ContactLifecycleCell lifecycle={null} />
        <ContactTagsCell tags={row.tags} />
        <ContactChannelsCell channels={row.channels} />
      </div>,
    );
    expect(parityHtml(container)).toMatchSnapshot();
  });
});
