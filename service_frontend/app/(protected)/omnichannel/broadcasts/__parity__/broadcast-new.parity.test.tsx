/**
 * Switch-off parity for the new broadcast form and the broadcast page
 * (Foundryx UIUX, slice W1-BROADCAST). Recorded on the code BEFORE the slice
 * changed anything, so a later change that alters what a user sees or what
 * reaches the backend with the switch off fails here. A change that needs one
 * of these snapshots updated is wrong by definition: fix the code, never the
 * snapshot.
 *
 * Covers: the new broadcast page (empty and filled, send now and schedule),
 * the request bodies of Create, Send now, Schedule, Save and Test send, the
 * toasts and the navigation after each, and the broadcast page for a draft
 * and for a broadcast that has left Draft.
 */
import type { ReactElement } from 'react';
import { act, fireEvent, render as rtlRender, screen, waitFor } from '@testing-library/react';
import { SettingsProvider } from '@/providers/settings-provider';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Broadcast, Channel, WhatsAppTemplate } from '@/types/omnichannel';
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
  push: vi.fn(),
  params: { id: 'bc-1' } as Record<string, string>,
  search: new URLSearchParams(),
  pathname: '/omnichannel/broadcasts/new',
  broadcast: null as unknown,
  permissions: new Set<string>(['broadcasts.read', 'broadcasts.manage', 'broadcasts.send']),
}));

const rec =
  (name: string, result?: (...args: unknown[]) => unknown) =>
  (...args: unknown[]) => {
    h.calls.push([name, ...args]);
    return result ? result(...args) : undefined;
  };

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
    push: (...args: unknown[]) => {
      h.calls.push(['router.push', ...args]);
      h.push(...args);
    },
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
  }),
  usePathname: () => h.pathname,
  useSearchParams: () => h.search,
  useParams: () => h.params,
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

vi.mock('@/hooks/use-conversation-socket', () => ({
  useConversationSocket: () => undefined,
}));

vi.mock('@/hooks/use-deferred-action', () => ({
  useDeferredAction: () => ({ state: { status: 'idle' }, start: vi.fn(), cancel: vi.fn() }),
}));

vi.mock('@/hooks/use-contact-segments', () => ({
  useContactSegments: () => ({
    segments: [{ id: 'seg-1', name: 'VIP customers' }],
    loading: false,
    reload: vi.fn(),
  }),
}));
vi.mock('@/hooks/use-contact-tags', () => ({ useContactTags: () => ({ tags: [], loading: false }) }));
vi.mock('@/hooks/use-contact-fields', () => ({ useContactFields: () => ({ fields: [], loading: false }) }));
vi.mock('@/hooks/use-contact-lifecycle-stages', () => ({
  useContactLifecycleStages: () => ({ stages: [], loading: false }),
}));
vi.mock('@/hooks/use-workspace-members', () => ({ useWorkspaceMembers: () => ({ members: [], loading: false }) }));
vi.mock('@/hooks/use-channel-type-options', () => ({ useChannelTypeOptions: () => [] }));
vi.mock('@/hooks/use-contact-picker', () => ({
  useContactPicker: () => ({
    query: '',
    setQuery: vi.fn(),
    loading: false,
    options: [
      { label: 'Aisyah Rahman (+60 12-345 6789)', value: 'ct-1' },
      { label: 'Lim Wei Jie (+60 13-222 1111)', value: 'ct-2' },
    ],
  }),
}));

vi.mock('@/app/(protected)/omnichannel/broadcasts/components/use-recipients-list-config', () => ({
  useRecipientsListConfig: () => ({
    config: { columns: [], fetchList: vi.fn() },
    reload: vi.fn(),
    reloadToken: 0,
  }),
}));

function channel(): Channel {
  return {
    id: 'chn-1',
    tenantId: 'tenant-1',
    workspaceId: 'wsp-1',
    workspaceName: 'Default',
    channelType: 'WHATSAPP',
    name: 'Maju Sales WhatsApp',
    status: 'ACTIVE',
    isActive: true,
    wabaId: null,
    phoneNumberId: 'pn-1',
    displayPhoneNumber: '+60 3-7890 1200',
    businessAccountName: null,
    verifiedName: null,
    lastVerifiedAt: null,
    profileSyncedAt: null,
    externalAccountId: null,
    externalAccountName: null,
    widgetKey: null,
    isTrashed: false,
    createdAt: '2026-07-07T10:00:00Z',
    updatedAt: '2026-07-07T10:00:00Z',
  };
}

function template(): WhatsAppTemplate {
  return {
    id: 'tpl-1',
    channelId: 'chn-1',
    name: 'promo_nov_2026',
    language: 'en',
    category: 'MARKETING',
    bodyText: 'Hi {{1}}, our November promo is on.',
    variableCount: 1,
    headerFormat: null,
    headerVariableCount: 0,
    buttonVariableCount: 0,
    status: 'APPROVED',
  };
}

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
    bindings: { header: [], body: [{ source: 'contactField', field: 'firstName', fallback: 'there' }], buttons: [] },
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

vi.mock('@/services/broadcast-service', () => ({
  broadcastService: {
    get: (...args: unknown[]) => {
      h.calls.push(['broadcast.get', ...args]);
      return Promise.resolve(h.broadcast);
    },
    audiencePreview: () => Promise.resolve({ count: 23 }),
    create: (...args: unknown[]) => {
      h.calls.push(['broadcast.create', ...args]);
      return Promise.resolve(broadcastRow({ id: 'bc-new' }));
    },
    update: (...args: unknown[]) => {
      h.calls.push(['broadcast.update', ...args]);
      return Promise.resolve(broadcastRow());
    },
    send: (...args: unknown[]) => {
      h.calls.push(['broadcast.send', ...args]);
      return Promise.resolve(broadcastRow({ id: 'bc-new', status: 'SENDING' }));
    },
    testSend: (...args: unknown[]) => {
      h.calls.push(['broadcast.testSend', ...args]);
      return Promise.resolve({ messageId: 'msg-1' });
    },
    duplicate: vi.fn(),
    cancel: vi.fn(),
    remove: vi.fn(),
    list: vi.fn(),
    recipients: vi.fn(),
  },
}));

vi.mock('@/services/channel-service', () => ({
  channelService: { listByWorkspace: () => Promise.resolve([channel()]) },
}));
vi.mock('@/services/conversation-service', () => ({
  conversationService: { listTemplates: () => Promise.resolve([template()]) },
}));
vi.mock('@/services/whatsapp-template-service', () => ({
  whatsappTemplateService: {
    get: () =>
      Promise.resolve({
        doc: {
          name: 'promo_nov_2026',
          language: 'en',
          category: 'MARKETING',
          header: null,
          body: { text: 'Hi {{1}}, our November promo is on.', examples: ['Alex'] },
          footer: null,
          buttons: [],
        },
      }),
  },
}));

// Imported after the mocks.
import NewBroadcastPage from '../new/page';
import BroadcastFormPage from '../[id]/page';

void rec;

function render(ui: ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

async function settle() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 350));
  });
}

async function pick(combobox: string, option: string) {
  fireEvent.click(screen.getByRole('combobox', { name: combobox }));
  fireEvent.click(await screen.findByRole('option', { name: option }));
  await settle();
}

/** Fills every required field of a new broadcast through the screen. */
async function fillNewBroadcast() {
  const name = document.querySelector('input:not([type])') as HTMLInputElement;
  fireEvent.change(name, { target: { value: 'November promo' } });
  await pick('Segment', 'VIP customers');
  await pick('Channel', 'Maju Sales WhatsApp');
  await pick('Template', 'promo_nov_2026 (en)');
  fireEvent.change(screen.getByTestId('broadcast-binding-body-0-fallback'), { target: { value: 'there' } });
  await settle();
}

function callsAfter(marker: number): unknown[] {
  return JSON.parse(JSON.stringify(h.calls.slice(marker)));
}

beforeEach(() => {
  h.calls.length = 0;
  h.push.mockReset();
  h.search = new URLSearchParams();
  h.pathname = '/omnichannel/broadcasts/new';
  h.params = { id: 'bc-1' };
  h.broadcast = null;
});

describe('switch-off parity: new broadcast', () => {
  it('renders the empty form as today', async () => {
    const { container } = render(<NewBroadcastPage />);
    await settle();
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('renders the filled form as today', async () => {
    const { container } = render(<NewBroadcastPage />);
    await settle();
    await fillNewBroadcast();
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('sends now with the same requests, toast and navigation as today', async () => {
    render(<NewBroadcastPage />);
    await settle();
    await fillNewBroadcast();
    const marker = h.calls.length;
    fireEvent.click(screen.getByRole('button', { name: 'Send now' }));
    await waitFor(() => expect(h.push).toHaveBeenCalled());
    await settle();
    expect(callsAfter(marker)).toMatchSnapshot();
  });

  it('schedules with the same requests, toast and navigation as today', async () => {
    const { container } = render(<NewBroadcastPage />);
    await settle();
    await fillNewBroadcast();
    fireEvent.click(screen.getByRole('radio', { name: 'Schedule for' }));
    await settle();
    fireEvent.change(screen.getByLabelText('Scheduled for'), { target: { value: '2031-03-20T14:30' } });
    await settle();
    expect(parityHtml(container)).toMatchSnapshot();
    const marker = h.calls.length;
    fireEvent.click(screen.getByRole('button', { name: 'Schedule broadcast' }));
    await waitFor(() => expect(h.push).toHaveBeenCalled());
    await settle();
    expect(callsAfter(marker)).toMatchSnapshot();
  });

  it('saves a draft with the same request as today', async () => {
    render(<NewBroadcastPage />);
    await settle();
    await fillNewBroadcast();
    const marker = h.calls.length;
    fireEvent.click(screen.getByRole('button', { name: /^Create|^Save/ }));
    await waitFor(() => expect(h.push).toHaveBeenCalled());
    await settle();
    expect(callsAfter(marker)).toMatchSnapshot();
  });

  it('sends a test message with the same requests as today', async () => {
    const { baseElement } = render(<NewBroadcastPage />);
    await settle();
    await fillNewBroadcast();
    const marker = h.calls.length;
    fireEvent.click(screen.getByRole('button', { name: 'Send test message' }));
    await settle();
    expect(parityHtml(baseElement.querySelector('[role="dialog"]') as Element)).toMatchSnapshot();
    await pick('Test-send contact', 'Aisyah Rahman (+60 12-345 6789)');
    fireEvent.click(screen.getByRole('button', { name: 'Send test' }));
    await settle();
    expect(callsAfter(marker)).toMatchSnapshot();
  });

  it('blocks Create with the same toast as today when a field is missing', async () => {
    render(<NewBroadcastPage />);
    await settle();
    const marker = h.calls.length;
    fireEvent.click(screen.getByRole('button', { name: /^Create|^Save/ }));
    await settle();
    expect(callsAfter(marker)).toMatchSnapshot();
  });
});

describe('switch-off parity: broadcast page', () => {
  it('renders a draft opened for editing as today', async () => {
    h.pathname = '/omnichannel/broadcasts/bc-1';
    h.search = new URLSearchParams('edit=1');
    h.broadcast = broadcastRow();
    const { container } = render(<BroadcastFormPage />);
    await settle();
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('renders a scheduled broadcast as today', async () => {
    h.pathname = '/omnichannel/broadcasts/bc-1';
    h.broadcast = broadcastRow({ status: 'SCHEDULED', statusLabel: 'Scheduled', scheduledAt: '2031-03-20T06:30:00Z' });
    const { container } = render(<BroadcastFormPage />);
    await settle();
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('renders a sending broadcast as today', async () => {
    h.pathname = '/omnichannel/broadcasts/bc-1';
    h.broadcast = broadcastRow({
      status: 'SENDING',
      statusLabel: 'Sending',
      startedAt: '2026-11-18T06:14:00Z',
      counts: { total: 23, sent: 10, delivered: 6, read: 2, failed: 1, skipped: 0 },
    });
    const { container } = render(<BroadcastFormPage />);
    await settle();
    expect(parityHtml(container)).toMatchSnapshot();
  });
});
