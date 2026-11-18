/**
 * Switch-off parity for the broadcasts list, the broadcast page's Recipients
 * list and the broadcast actions (Foundryx UIUX, slice W2-BCAST). Recorded on
 * the code BEFORE the slice changed anything, so a later change that alters
 * what a user sees or what reaches the backend with the switch off fails
 * here. A change that needs one of these snapshots updated is wrong by
 * definition: fix the code, never the snapshot.
 */
import type { ReactElement } from 'react';
import { act, render as rtlRender, renderHook, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import { ResourceList } from '@/components/platform/resource-list';
import type { ResourceAction } from '@/components/platform/resource-list';
import type { Broadcast, BroadcastRecipient } from '@/types/omnichannel';
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

const h = vi.hoisted(() => ({
  calls: [] as unknown[],
  permissions: new Set<string>(['broadcasts.read', 'broadcasts.manage', 'broadcasts.send']),
}));

vi.mock('@/lib/toast', () => {
  const t = (kind: string) => (...args: unknown[]) => {
    h.calls.push([`toast.${kind}`, ...args]);
    return 'toast-id';
  };
  return {
    toast: {
      success: t('success'),
      error: t('error'),
      info: t('info'),
      warning: t('warning'),
      message: t('message'),
      custom: t('custom'),
      dismiss: t('dismiss'),
      fxDone: t('fxDone'),
    },
  };
});

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: (...args: unknown[]) => h.calls.push(['router.push', ...args]),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
  }),
  usePathname: () => '/omnichannel/broadcasts',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { name: 'Kay Tan', timezone: 'Asia/Kuala_Lumpur', permissions: [] } },
    status: 'authenticated',
  }),
}));

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: (key: string) => h.permissions.has(key), ready: true, permissions: h.permissions }),
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
vi.mock('@/hooks/use-workspace-id', () => ({
  useWorkspaceId: () => ({ workspaceId: 'wsp-1', loading: false }),
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/preferences-service', () => ({
  preferencesService: { get: vi.fn().mockResolvedValue(null), save: vi.fn().mockResolvedValue(undefined) },
}));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => ({ openImport: vi.fn() }),
}));

function broadcastRow(overrides: Partial<Broadcast> = {}): Broadcast {
  return {
    id: 'bc-1',
    workspaceId: 'wsp-1',
    name: 'November promo',
    labels: ['promo'],
    channelId: 'chn-1',
    channelName: 'Maju Sales WhatsApp',
    audience: { kind: 'segment', segmentId: 'seg-1', segmentName: 'VIP customers', filter: null, contactIds: null },
    templateId: 'tpl-1',
    templateName: 'promo_nov_2026',
    templateLanguage: 'en',
    bindings: { header: [], body: [], buttons: [] },
    status: 'DRAFT',
    statusLabel: 'Draft',
    scheduledAt: null,
    startedAt: null,
    finishedAt: null,
    counts: { total: 0, sent: 0, delivered: 0, read: 0, failed: 0, skipped: 0 },
    jobId: null,
    error: null,
    createdByUserId: 'u-1',
    createdByName: 'Kay Tan',
    createdAt: '2026-11-18T02:00:00Z',
    updatedAt: '2026-11-18T02:00:00Z',
    ...overrides,
  };
}

const ROWS: Broadcast[] = [
  broadcastRow(),
  broadcastRow({
    id: 'bc-2',
    name: 'Year end sale',
    labels: ['sale', 'q4'],
    status: 'SENDING',
    statusLabel: 'Sending',
    startedAt: '2026-11-18T06:14:00Z',
    counts: { total: 1240, sent: 820, delivered: 600, read: 210, failed: 12, skipped: 3 },
  }),
  broadcastRow({
    id: 'bc-3',
    name: 'Webinar reminder',
    labels: [],
    audience: { kind: 'contacts', contactIds: ['c1', 'c2'] },
    status: 'SCHEDULED',
    statusLabel: 'Scheduled',
    scheduledAt: '2031-03-20T06:30:00Z',
  }),
];

const RECIPIENTS: BroadcastRecipient[] = [
  {
    id: 'rc-1',
    contactId: 'c1',
    contactName: 'Aisyah Rahman',
    phone: '+60 12-345 6789',
    state: 'read',
    errorText: null,
    skipReason: null,
    attemptedAt: '2026-11-18T06:15:00Z',
  } as BroadcastRecipient,
  {
    id: 'rc-2',
    contactId: 'c2',
    contactName: 'Lim Wei Jie',
    phone: null,
    state: 'failed',
    errorText: 'Number is not on WhatsApp',
    skipReason: null,
    attemptedAt: '2026-11-18T06:16:00Z',
  } as BroadcastRecipient,
];

vi.mock('@/services/broadcast-service', () => ({
  broadcastService: {
    list: (...args: unknown[]) => {
      h.calls.push(['broadcast.list', ...args]);
      return Promise.resolve({ data: ROWS, total: ROWS.length, page: 1 });
    },
    recipients: (...args: unknown[]) => {
      h.calls.push(['broadcast.recipients', ...args]);
      return Promise.resolve({ data: RECIPIENTS, total: RECIPIENTS.length, page: 0 });
    },
    send: (...args: unknown[]) => {
      h.calls.push(['broadcast.send', ...args]);
      return Promise.resolve(broadcastRow({ status: 'SENDING' }));
    },
    cancel: (...args: unknown[]) => {
      h.calls.push(['broadcast.cancel', ...args]);
      return Promise.resolve(broadcastRow({ status: 'CANCELLED' }));
    },
    duplicate: (...args: unknown[]) => {
      h.calls.push(['broadcast.duplicate', ...args]);
      return Promise.resolve(broadcastRow({ id: 'bc-copy', name: 'November promo (copy)' }));
    },
    remove: vi.fn(),
    get: vi.fn(),
  },
}));

// Imported after the mocks.
import BroadcastsPage from '../page';
import { useBroadcastActions } from '../components/use-broadcast-actions';
import { useRecipientsListConfig } from '../components/use-recipients-list-config';

function render(ui: ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

async function settle() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 50));
  });
}

function RecipientsHarness() {
  const { config } = useRecipientsListConfig('wsp-1', 'bc-1');
  return <ResourceList config={config} hideHeader />;
}

function calls(): unknown[] {
  return JSON.parse(JSON.stringify(h.calls));
}

const RT = { reload: () => h.calls.push(['reload']) };

beforeEach(() => {
  h.calls.length = 0;
});

describe('switch-off parity: broadcasts list', () => {
  it('renders the list page as today', async () => {
    const { container } = render(<BroadcastsPage />);
    await screen.findByText('Webinar reminder');
    await settle();
    expect(parityHtml(container)).toMatchSnapshot();
    expect(calls()).toMatchSnapshot();
  });

  it('renders the Recipients list as today', async () => {
    const { container } = render(<RecipientsHarness />);
    await screen.findByText('Lim Wei Jie');
    await settle();
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

describe('switch-off parity: broadcast actions', () => {
  function actions(): ResourceAction<Broadcast>[] {
    const { result } = renderHook(() => useBroadcastActions('wsp-1'));
    return result.current;
  }
  const find = (list: ResourceAction<Broadcast>[], id: string) => list.find((a) => a.id === id)!;

  it('keeps the same actions, labels, gates and deferred keys', () => {
    const shape = actions().map((a) => ({
      id: a.id,
      label: a.label,
      tone: a.tone,
      permission: a.permission,
      surfaces: a.surfaces,
      deferred: a.deferred ? { actionKey: a.deferred.actionKey, entityType: a.deferred.entityType } : undefined,
    }));
    expect(shape).toMatchSnapshot();
  });

  it('Send now sends the same requests and toasts as today', async () => {
    const action = find(actions(), 'send');
    await act(async () => {
      await action.run!([ROWS[0], ROWS[2]], RT);
    });
    expect(calls()).toMatchSnapshot();
  });

  it('Cancel sends the same requests and toasts as today', async () => {
    const action = find(actions(), 'cancel');
    await act(async () => {
      await action.run!([ROWS[1]], RT);
    });
    expect(calls()).toMatchSnapshot();
  });

  it('Duplicate sends the same request, toast and navigation as today', async () => {
    const action = find(actions(), 'duplicate');
    await act(async () => {
      await action.run!([ROWS[0]], RT);
    });
    expect(calls()).toMatchSnapshot();
  });

  it('Edit navigates as today', async () => {
    const action = find(actions(), 'edit');
    await act(async () => {
      await action.run!([ROWS[0]], { ...RT, ctx: 'q', index: 2 });
    });
    expect(calls()).toMatchSnapshot();
  });
});
