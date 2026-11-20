/**
 * Broadcasts list and broadcast page under the Foundryx UIUX switch (slice
 * W2-BCAST): the words, the counts that roll, the header actions of the
 * broadcast page, the hand-over from the done page, draft editing, and that
 * every write reaches the backend exactly as it does with the switch off.
 */
import type { ReactElement } from 'react';
import { act, fireEvent, render as rtlRender, renderHook, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Broadcast, Channel, WhatsAppTemplate } from '@/types/omnichannel';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { SettingsProvider } from '@/providers/settings-provider';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';

const h = vi.hoisted(() => ({
  calls: [] as unknown[],
  params: { id: 'bc-1' } as Record<string, string>,
  search: new URLSearchParams(),
  broadcast: null as unknown,
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
  usePathname: () => '/omnichannel/broadcasts/bc-1',
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
vi.mock('@/hooks/use-workspace-id', () => ({ useWorkspaceId: () => ({ workspaceId: 'wsp-1', loading: false }) }));
vi.mock('@/hooks/use-conversation-socket', () => ({ useConversationSocket: () => undefined }));
vi.mock('@/hooks/use-deferred-action', () => ({
  useDeferredAction: () => ({ state: { status: 'idle' }, start: vi.fn(), cancel: vi.fn() }),
}));
vi.mock('@/hooks/use-contact-segments', () => ({
  useContactSegments: () => ({ segments: [{ id: 'seg-1', name: 'VIP customers' }], loading: false, reload: vi.fn() }),
}));
vi.mock('@/hooks/use-contact-tags', () => ({ useContactTags: () => ({ tags: [], loading: false }) }));
vi.mock('@/hooks/use-contact-fields', () => ({ useContactFields: () => ({ fields: [], loading: false }) }));
vi.mock('@/hooks/use-contact-lifecycle-stages', () => ({ useContactLifecycleStages: () => ({ stages: [], loading: false }) }));
vi.mock('@/hooks/use-workspace-members', () => ({ useWorkspaceMembers: () => ({ members: [], loading: false }) }));
vi.mock('@/hooks/use-channel-type-options', () => ({ useChannelTypeOptions: () => [] }));
vi.mock('@/hooks/use-contact-picker', () => ({
  useContactPicker: () => ({ query: '', setQuery: vi.fn(), loading: false, options: [] }),
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/preferences-service', () => ({
  preferencesService: { get: vi.fn().mockResolvedValue(null), save: vi.fn().mockResolvedValue(undefined) },
}));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/providers/import-activity-provider', () => ({ useImportActivity: () => ({ openImport: vi.fn() }) }));

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

vi.mock('@/services/broadcast-service', () => ({
  broadcastService: {
    get: (...args: unknown[]) => {
      h.calls.push(['broadcast.get', ...args]);
      return Promise.resolve(h.broadcast);
    },
    audiencePreview: () => Promise.resolve({ count: 23 }),
    create: vi.fn(),
    update: (...args: unknown[]) => {
      h.calls.push(['broadcast.update', ...args]);
      return Promise.resolve(h.broadcast);
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
    testSend: (...args: unknown[]) => {
      h.calls.push(['broadcast.testSend', ...args]);
      return Promise.resolve({ messageId: 'msg-1' });
    },
    remove: vi.fn(),
    list: vi.fn(),
    recipients: () => Promise.resolve({ data: [], total: 0, page: 0 }),
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
import BroadcastFormPage from '../[id]/page';
import { setBroadcastDone, clearBroadcastDone } from './broadcast-done-store';
import { useBroadcastActions } from './use-broadcast-actions';
import { useBroadcastsListConfig } from './use-broadcasts-list-config';
import { useRecipientsListConfig } from './use-recipients-list-config';
import { deliveryProgress } from './fx-broadcast-detail';
import { fxCancelledToast, fxDuplicatedToast, fxSendNowLabel, fxSendingToast } from './fx-broadcast-words';
import { FxRollingCount, rollStep } from './fx-rolling-count';

function render(ui: ReactElement, fx: boolean) {
  return rtlRender(
    <FxProvider initial={fx} initialTheme={FX_DEFAULT_THEME}>
      <SettingsProvider>{ui}</SettingsProvider>
    </FxProvider>,
  );
}

async function settle() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 300));
  });
}

const writes = () =>
  (JSON.parse(JSON.stringify(h.calls)) as unknown[][]).filter(
    (c) => typeof c[0] === 'string' && /^broadcast\.(send|cancel|duplicate|update|create|testSend|remove)$/.test(c[0]),
  );

beforeEach(() => {
  h.calls.length = 0;
  h.search = new URLSearchParams();
  h.params = { id: 'bc-1' };
  h.broadcast = null;
  resetPageActionsForTests();
  clearBroadcastDone('bc-1');
});

describe('words (pure)', () => {
  it('says what was sent, cancelled and copied, for how many and by whom, with no Undo', () => {
    const one = broadcastRow({ counts: { total: 23, sent: 0, delivered: 0, read: 0, failed: 0, skipped: 0 } });
    expect(fxSendingToast([one], 'Kay')).toEqual({ what: '“November promo” is sending', forWhom: 'to 23 contacts', byWhom: 'Kay' });
    expect(fxSendingToast([broadcastRow(), broadcastRow({ id: 'b2' })])).toEqual({
      what: '2 broadcasts are sending',
      forWhom: undefined,
      byWhom: undefined,
    });
    expect(fxCancelledToast([one], 'Kay')).toEqual({ what: '“November promo” cancelled', byWhom: 'Kay' });
    expect(fxDuplicatedToast(one, broadcastRow({ name: 'November promo (copy)' }), 'Kay')).toEqual({
      what: '“November promo” copied as “November promo (copy)”',
      byWhom: 'Kay',
    });
    for (const t of [fxSendingToast([one]), fxCancelledToast([one]), fxDuplicatedToast(one, one)]) {
      expect(t.undo).toBeUndefined();
    }
  });

  it('the red action names the count and template once the recipients are counted', () => {
    expect(fxSendNowLabel([broadcastRow()])).toBe('Send November promo now with promo_nov_2026');
    expect(
      fxSendNowLabel([broadcastRow({ counts: { total: 1240, sent: 0, delivered: 0, read: 0, failed: 0, skipped: 0 } })]),
    ).toBe('Send now to 1,240 contacts with promo_nov_2026');
    expect(fxSendNowLabel([broadcastRow(), broadcastRow()])).toBe('Send 2 broadcasts now');
  });

  it('progress counts every recipient tried', () => {
    expect(deliveryProgress({ total: 0, sent: 0, delivered: 0, read: 0, failed: 0, skipped: 0 })).toBe(0);
    expect(deliveryProgress({ total: 200, sent: 90, delivered: 50, read: 10, failed: 6, skipped: 4 })).toBe(50);
    expect(deliveryProgress({ total: 10, sent: 10, delivered: 10, read: 10, failed: 1, skipped: 0 })).toBe(100);
  });
});

describe('counts roll', () => {
  it('eases to the new number and lands on it exactly', () => {
    expect(rollStep(10, 20, 0)).toBe(10);
    expect(rollStep(10, 20, 0.5)).toBeGreaterThan(15);
    expect(rollStep(10, 20, 1)).toBe(20);
    expect(rollStep(10, 20, 3)).toBe(20);
  });

  it('rolls through frames when motion is allowed, and shows the end value', () => {
    const frames: FrameRequestCallback[] = [];
    vi.stubGlobal('matchMedia', () => ({ matches: false }));
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => frames.push(cb));
    vi.stubGlobal('cancelAnimationFrame', () => undefined);
    const now = vi.spyOn(performance, 'now').mockReturnValue(0);
    const { container, rerender } = rtlRender(<FxRollingCount value={10} />);
    expect(container.textContent).toBe('10');
    rerender(<FxRollingCount value={1010} />);
    act(() => frames.shift()?.(175));
    const mid = Number(container.textContent?.replace(/,/g, ''));
    expect(mid).toBeGreaterThan(10);
    expect(mid).toBeLessThan(1010);
    act(() => frames.shift()?.(400));
    expect(container.textContent).toBe('1,010');
    now.mockRestore();
    vi.unstubAllGlobals();
  });

  it('changes at once with reduced motion', () => {
    vi.stubGlobal('matchMedia', () => ({ matches: true }));
    const { container, rerender } = rtlRender(<FxRollingCount value={3} />);
    rerender(<FxRollingCount value={7} />);
    expect(container.textContent).toBe('7');
    vi.unstubAllGlobals();
  });
});

describe('list configs', () => {
  it('the broadcasts list names its red action, icons, card lines and noun', () => {
    const { result } = renderHook(() => useBroadcastsListConfig('wsp-1'));
    const fx = result.current.fx!;
    expect(fx.mainActionId).toBe('create');
    expect(fx.noun).toBe('broadcasts');
    expect(fx.columnKind).toEqual({ status: 'status' });
    const ids = result.current.columns.map((c) => c.id);
    for (const id of [...fx.copyable!, ...fx.phoneHidden!, ...fx.cardLines!.flat()]) expect(ids).toContain(id);
    const amounts = result.current.columns.filter((c) => c.meta?.fxAlign === 'end').map((c) => c.id);
    expect(amounts).toEqual(['recipients']);
  });

  it('the recipients list keeps the smaller states and names its noun', () => {
    const { result } = renderHook(() => useRecipientsListConfig('wsp-1', 'bc-1'));
    const fx = result.current.config.fx!;
    expect(fx.noun).toBe('recipients');
    expect(fx.compactStates).toBe(true);
    const ids = result.current.config.columns.map((c) => c.id);
    for (const id of [...fx.copyable!, ...fx.phoneHidden!, ...fx.cardLines!.flat()]) expect(ids).toContain(id);
  });
});

describe('the same writes in both looks', () => {
  function actionsWith(fx: boolean) {
    const { result } = renderHook(() => useBroadcastActions('wsp-1'), {
      wrapper: ({ children }) => (
        <FxProvider initial={fx} initialTheme={FX_DEFAULT_THEME}>
          {children}
        </FxProvider>
      ),
    });
    return result.current;
  }

  async function run(fx: boolean, id: string, rows: Broadcast[]) {
    h.calls.length = 0;
    const action = actionsWith(fx).find((a) => a.id === id)!;
    await act(async () => {
      await action.run!(rows, { reload: () => h.calls.push(['reload']) });
    });
    return JSON.parse(JSON.stringify(h.calls)) as unknown[][];
  }

  for (const [id, rows] of [
    ['send', [broadcastRow(), broadcastRow({ id: 'bc-2', status: 'SCHEDULED' })]],
    ['cancel', [broadcastRow({ status: 'SENDING' })]],
    ['duplicate', [broadcastRow()]],
  ] as [string, Broadcast[]][]) {
    it(`${id}: identical requests, reloads and navigation; only the toast differs`, async () => {
      const off = await run(false, id, rows);
      const on = await run(true, id, rows);
      const notToast = (c: unknown[]) => !String(c[0]).startsWith('toast.');
      expect(on.filter(notToast)).toEqual(off.filter(notToast));
      expect(off.some((c) => c[0] === 'toast.success')).toBe(true);
      const done = on.find((c) => c[0] === 'toast.fxDone') as [string, { byWhom?: string; undo?: unknown }];
      expect(done[1].byWhom).toBe('Kay Tan');
      expect(done[1].undo).toBeUndefined();
    });
  }

  it('delete keeps its grace-window handler and gains only the name for its countdown', () => {
    const del = actionsWith(true).find((a) => a.id === 'delete')!;
    expect(del.deferred?.actionKey).toBe('broadcasts.delete');
    expect(del.deferred?.payload).toBeUndefined();
    expect(del.deferred?.fxName?.([broadcastRow()])).toBe('November promo');
    expect(del.deferred?.fxName?.([broadcastRow(), broadcastRow()])).toBeUndefined();
  });
});

describe('the broadcast page', () => {
  it('a scheduled broadcast: Send now is the red action and sends what the switch-off menu sends', async () => {
    h.broadcast = broadcastRow({
      status: 'SCHEDULED',
      statusLabel: 'Scheduled',
      scheduledAt: '2031-03-20T06:30:00Z',
      counts: { total: 23, sent: 0, delivered: 0, read: 0, failed: 0, skipped: 0 },
    });
    render(<BroadcastFormPage />, true);
    await settle();
    const main = screen.getByRole('button', { name: 'Send now to 23 contacts with promo_nov_2026' });
    expect(screen.getByRole('button', { name: 'Send test message' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Duplicate' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Delivery' })).toBeInTheDocument();
    h.calls.length = 0;
    fireEvent.click(main);
    await settle();
    expect(writes()).toEqual([['broadcast.send', 'wsp-1', 'bc-1', null]]);
  });

  it('a sending broadcast: no red action, Cancel sends the same request as today, counts show', async () => {
    h.broadcast = broadcastRow({
      status: 'SENDING',
      statusLabel: 'Sending',
      startedAt: '2026-11-18T06:14:00Z',
      counts: { total: 1240, sent: 820, delivered: 600, read: 210, failed: 12, skipped: 3 },
    });
    render(<BroadcastFormPage />, true);
    await settle();
    expect(screen.queryByRole('button', { name: /^Send now/ })).toBeNull();
    expect(screen.getByText('1,240')).toBeInTheDocument();
    expect(screen.getByRole('progressbar', { name: 'Recipients tried' })).toHaveAttribute('aria-valuenow', '67');
    // The test send is a header icon now, never also an in-page button.
    expect(screen.getAllByRole('button', { name: 'Send test message' })).toHaveLength(1);
    h.calls.length = 0;
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await settle();
    expect(writes()).toEqual([['broadcast.cancel', 'wsp-1', 'bc-1']]);
  });

  it('a draft opened for editing still opens the form', async () => {
    h.search = new URLSearchParams('edit=1');
    h.broadcast = broadcastRow();
    const { container } = render(<BroadcastFormPage />, true);
    await settle();
    expect((container.querySelector('input:not([type])') as HTMLInputElement).value).toBe('November promo');
    expect(screen.getAllByRole('button', { name: /Save/ }).length).toBeGreaterThan(0);
  });

  it('right after a send the done page shows first, and View delivery opens this page', async () => {
    h.broadcast = broadcastRow({ status: 'SENDING', statusLabel: 'Sending' });
    setBroadcastDone('bc-1', { mode: 'now', audienceCount: 23, byWhom: 'Kay Tan', pressedAt: '2026-11-18T06:14:00Z' });
    render(<BroadcastFormPage />, true);
    await settle();
    fireEvent.click(screen.getByRole('button', { name: /View delivery/ }));
    await settle();
    expect(screen.getByRole('region', { name: 'Delivery' })).toBeInTheDocument();
  });
});
