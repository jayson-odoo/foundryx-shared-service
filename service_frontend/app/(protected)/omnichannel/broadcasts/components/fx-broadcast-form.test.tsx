/**
 * The new broadcast under the Foundryx UIUX switch (slice W1-BROADCAST): the
 * red action's labels, blocked reasons and pulses, the icon actions, the
 * schedule's date, time list and zone line, the done page, and the core
 * guarantee that both looks send byte-for-byte the same requests for the
 * same input.
 */
import type { ReactElement } from 'react';
import { act, fireEvent, render as rtlRender, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import { FxProvider } from '@/providers/fx-provider';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import type { Broadcast, Channel, WhatsAppTemplate } from '@/types/omnichannel';
import { EMPTY_BROADCAST_FORM_VALUES, type BroadcastFormValues } from '../components/broadcast-schema';
import {
  BC_PULSE,
  broadcastBlocked,
  broadcastMainLabels,
  contactsCount,
  fxClockLabel,
  joinScheduledAt,
  splitScheduledAt,
  timeOptions,
} from '../components/fx-broadcast-actions';
import { broadcastDoneLines } from '../components/broadcast-done-view';
import { clearBroadcastDone, peekBroadcastDone, setBroadcastDone } from '../components/broadcast-done-store';
import { zonedTimeToUtc } from '@/lib/datetime';

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

vi.mock('./use-recipients-list-config', () => ({
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

function render(ui: ReactElement, fx: boolean) {
  return rtlRender(
    <FxProvider initial={fx} initialTheme={FX_DEFAULT_THEME}>
      <SettingsProvider>{ui}</SettingsProvider>
    </FxProvider>,
  );
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

function nameInput(): HTMLInputElement {
  return (screen.getByText('Name *').parentElement as HTMLElement).querySelector('input') as HTMLInputElement;
}

async function fillNewBroadcast() {
  fireEvent.change(nameInput(), { target: { value: 'November promo' } });
  await pick('Segment', 'VIP customers');
  await pick('Channel', 'Maju Sales WhatsApp');
  await pick('Template', 'promo_nov_2026 (en)');
  fireEvent.change(screen.getByTestId('broadcast-binding-body-0-fallback'), { target: { value: 'there' } });
  await settle();
}

/** The requests that reached the backend (broadcast service calls only). */
function requests(): unknown[] {
  return JSON.parse(JSON.stringify(h.calls.filter((c) => String((c as unknown[])[0]).startsWith('broadcast.') && (c as unknown[])[0] !== 'broadcast.get')));
}

function mainAction(): HTMLButtonElement {
  return document.querySelector('[data-fx-main-action] button') as HTMLButtonElement;
}

beforeEach(() => {
  h.calls.length = 0;
  h.push.mockReset();
  h.search = new URLSearchParams();
  h.pathname = '/omnichannel/broadcasts/new';
  h.params = { id: 'bc-1' };
  h.broadcast = null;
  h.permissions = new Set(['broadcasts.read', 'broadcasts.manage', 'broadcasts.send']);
});

afterEach(() => {
  resetPageActionsForTests();
  clearBroadcastDone('bc-new');
});

vi.setConfig({ testTimeout: 30000 });

const TZ = 'Asia/Kuala_Lumpur';

function values(over: Partial<BroadcastFormValues> = {}): BroadcastFormValues {
  return {
    ...EMPTY_BROADCAST_FORM_VALUES,
    name: 'November promo',
    channelId: 'chn-1',
    audience: { kind: 'segment', segmentId: 'seg-1' },
    templateId: 'tpl-1',
    bindings: { header: [], body: [{ source: 'contactField', field: 'firstName', fallback: 'there' }], buttons: [] },
    ...over,
  };
}

describe('red action labels', () => {
  it('names the send now with the count and the template', () => {
    expect(broadcastMainLabels({ mode: 'now', audienceCount: 23, templateName: 'promo_nov_2026', when: '' })).toEqual({
      label: 'Send now',
      fullLabel: 'Send now to 23 contacts with promo_nov_2026',
    });
    expect(broadcastMainLabels({ mode: 'now', audienceCount: 1, templateName: 'promo_nov_2026', when: '' }).fullLabel).toBe(
      'Send now to 1 contact with promo_nov_2026',
    );
  });

  it('names the schedule with the template, count and time', () => {
    expect(
      broadcastMainLabels({ mode: 'schedule', audienceCount: 23, templateName: 'promo_nov_2026', when: '20 Mar 2031, 2:30 pm' }),
    ).toEqual({ label: 'Schedule broadcast', fullLabel: 'Schedule promo_nov_2026 to 23 contacts for 20 Mar 2031, 2:30 pm' });
  });

  it('keeps the short label while the count, template or time is unknown', () => {
    expect(broadcastMainLabels({ mode: 'now', audienceCount: null, templateName: 'x', when: '' }).fullLabel).toBeUndefined();
    expect(broadcastMainLabels({ mode: 'schedule', audienceCount: 3, templateName: 'x', when: '' }).fullLabel).toBeUndefined();
    expect(contactsCount(1240)).toBe('1,240 contacts');
  });
});

describe('blocked reason and pulse target', () => {
  const none = { date: null, time: null };
  it('goes in the order the form reads', () => {
    expect(broadcastBlocked({ ...EMPTY_BROADCAST_FORM_VALUES }, none)).toEqual({ reason: 'Name the broadcast.', pulseTarget: BC_PULSE.name });
    expect(broadcastBlocked(values({ name: 'x'.repeat(201) }), none)?.pulseTarget).toBe(BC_PULSE.name);
    expect(broadcastBlocked(values({ audience: { kind: 'segment' } }), none)).toEqual({ reason: 'Pick who gets it.', pulseTarget: BC_PULSE.audience });
    expect(broadcastBlocked(values({ audience: { kind: 'contacts', contactIds: [] } }), none)?.pulseTarget).toBe(BC_PULSE.audience);
    expect(broadcastBlocked(values({ channelId: '', templateId: '' }), none)).toEqual({ reason: 'Pick a channel.', pulseTarget: BC_PULSE.channel });
    expect(broadcastBlocked(values({ templateId: '' }), none)).toEqual({ reason: 'Pick a template.', pulseTarget: BC_PULSE.template });
    expect(
      broadcastBlocked(values({ bindings: { header: [], body: [{ source: 'contactField', field: 'firstName', fallback: '' }], buttons: [] } }), none),
    ).toEqual({ reason: 'Fill in every template value.', pulseTarget: BC_PULSE.bindings });
  });

  it('names the missing date, the missing time or a past time', () => {
    const sched = values({ scheduleMode: 'schedule', scheduledAt: null });
    expect(broadcastBlocked(sched, none)).toEqual({ reason: 'Pick a date to send.', pulseTarget: BC_PULSE.date });
    expect(broadcastBlocked(sched, { date: '2031-03-20', time: null })).toEqual({ reason: 'Pick a time to send.', pulseTarget: BC_PULSE.time });
    expect(
      broadcastBlocked(values({ scheduleMode: 'schedule', scheduledAt: '2020-01-01T00:00:00.000Z' }), { date: '2020-01-01', time: '08:00' }),
    ).toEqual({ reason: 'Pick a time in the future.', pulseTarget: BC_PULSE.time });
  });

  it('is not blocked exactly when the switch-off form allows Send', () => {
    expect(broadcastBlocked(values(), none)).toBeUndefined();
    expect(broadcastBlocked(values({ scheduleMode: 'schedule', scheduledAt: '2031-03-20T06:30:00.000Z' }), { date: '2031-03-20', time: '14:30' })).toBeUndefined();
  });
});

describe('schedule date and time', () => {
  it('reads the time list on the 12-hour clock', () => {
    expect(fxClockLabel('00:00')).toBe('12:00 am');
    expect(fxClockLabel('12:30')).toBe('12:30 pm');
    expect(fxClockLabel('14:30')).toBe('2:30 pm');
    const opts = timeOptions(null);
    expect(opts).toHaveLength(48);
    expect(opts[29]).toEqual({ label: '2:30 pm', value: '14:30' });
    expect(timeOptions('10:17').some((o) => o.value === '10:17' && o.label === '10:17 am')).toBe(true);
  });

  it('turns a picked day and time into the same instant the switch-off field sends', () => {
    const fx = joinScheduledAt({ date: '2031-03-20', time: '14:30' }, TZ);
    const legacy = (zonedTimeToUtc('2031-03-20T14:30', TZ) as Date).toISOString();
    expect(fx).toBe(legacy);
    expect(fx).toBe('2031-03-20T06:30:00.000Z');
    expect(joinScheduledAt({ date: '2031-03-20', time: null }, TZ)).toBeNull();
    expect(splitScheduledAt('2031-03-20T06:30:00.000Z', TZ)).toEqual({ date: '2031-03-20', time: '14:30' });
    expect(splitScheduledAt(null, TZ)).toEqual({ date: null, time: null });
  });
});

describe('done page words', () => {
  const fmt = { dateTime: (iso: string) => `DT(${iso})`, time: (iso: string) => `T(${iso})` };
  it('says what went out, to how many, by whom and when (send now)', () => {
    const lines = broadcastDoneLines(
      broadcastRow({ status: 'SENDING', startedAt: '2026-11-18T06:14:00Z', counts: { total: 23, sent: 0, delivered: 0, read: 0, failed: 0, skipped: 0 } }),
      { mode: 'now', byWhom: 'Kay Tan', audienceCount: 20, pressedAt: '2026-11-18T06:13:59Z' },
      fmt,
    );
    expect(lines).toEqual({
      title: 'Broadcast sending',
      headline: '“November promo” is going to 23 contacts',
      detail: 'Started at T(2026-11-18T06:14:00Z) on Maju Sales WhatsApp with the promo_nov_2026 template, by Kay Tan.',
      loop: 'Delivery counts update on the broadcast’s page as they come in.',
    });
  });

  it('uses the count shown at send time before recipients exist (schedule)', () => {
    const lines = broadcastDoneLines(
      broadcastRow({ status: 'SCHEDULED', scheduledAt: '2031-03-20T06:30:00Z' }),
      { mode: 'schedule', byWhom: null, audienceCount: 23, pressedAt: '2026-11-18T06:13:59Z' },
      fmt,
    );
    expect(lines.title).toBe('Broadcast scheduled');
    expect(lines.headline).toBe('“November promo” goes to 23 contacts');
    expect(lines.detail).toBe('Scheduled for DT(2031-03-20T06:30:00Z) on Maju Sales WhatsApp with the promo_nov_2026 template.');
  });
});

describe('new broadcast with the switch on', () => {
  it('shows one red action, blocked with the reason, pulsing the missing field', async () => {
    render(<NewBroadcastPage />, true);
    await settle();
    expect(document.querySelectorAll('[data-fx-main-action]')).toHaveLength(1);
    expect(mainAction().getAttribute('aria-disabled')).toBe('true');
    expect(screen.getByText('Name the broadcast.')).toBeTruthy();
    // No Send buttons at the bottom of the page.
    expect(screen.queryByRole('button', { name: 'Send test message' })).toBeNull();
    fireEvent.click(mainAction());
    expect(document.querySelector(`[data-fx-pulse-target="${BC_PULSE.name}"]`)?.hasAttribute('data-fx-pulsing')).toBe(true);
    expect(h.calls.filter((c) => (c as unknown[])[0] === 'broadcast.send')).toHaveLength(0);

    fireEvent.change(nameInput(), { target: { value: 'November promo' } });
    await settle();
    expect(screen.getByText('Pick who gets it.')).toBeTruthy();
    fireEvent.click(mainAction());
    expect(document.querySelector(`[data-fx-pulse-target="${BC_PULSE.audience}"]`)?.hasAttribute('data-fx-pulsing')).toBe(true);
  });

  it('names the send in full once the form is complete, and the icon actions', async () => {
    render(<NewBroadcastPage />, true);
    await settle();
    await fillNewBroadcast();
    expect(mainAction().getAttribute('aria-disabled')).toBeNull();
    expect(mainAction().getAttribute('aria-label')).toBe('Send now to 23 contacts with promo_nov_2026');
    expect(screen.getByRole('button', { name: 'Save as draft' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Send a test message' }).getAttribute('aria-disabled')).toBeNull();
    expect(screen.getByRole('button', { name: 'Discard changes' })).toBeTruthy();
  });

  it('greys Send a test message until a channel and template are picked, and hides the red action without send permission', async () => {
    h.permissions = new Set(['broadcasts.read', 'broadcasts.manage']);
    render(<NewBroadcastPage />, true);
    await settle();
    expect(document.querySelector('[data-fx-main-action]')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Send a test message' })).toBeNull();
    resetPageActionsForTests();
  });

  it('switches to Schedule broadcast with a date field, a 12-hour time list and the zone line', async () => {
    render(<NewBroadcastPage />, true);
    await settle();
    await fillNewBroadcast();
    fireEvent.click(screen.getByRole('radio', { name: 'Schedule for' }));
    await settle();
    expect(mainAction().textContent).toContain('Schedule broadcast');
    expect(screen.getByText('Pick a date to send.')).toBeTruthy();
    expect(document.querySelector('[data-fx-zone-line]')?.textContent).toContain('GMT+8');
    const date = screen.getByLabelText('Date');
    fireEvent.change(date, { target: { value: '20 Mar 2031' } });
    fireEvent.blur(date);
    await settle();
    expect((date as HTMLInputElement).value).toBe('20 Mar 2031');
    expect(screen.getByText('Pick a time to send.')).toBeTruthy();
    await pick('Time', '2:30 pm');
    expect(mainAction().getAttribute('aria-label')).toBe('Schedule promo_nov_2026 to 23 contacts for 20 Mar 2031, 2:30 pm');
  });

  it('discards in a single click through the discard dialog', async () => {
    render(<NewBroadcastPage />, true);
    await settle();
    fireEvent.change(nameInput(), { target: { value: 'November promo' } });
    await settle();
    fireEvent.click(screen.getByRole('button', { name: 'Discard changes' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(within(dialog).getByText('Discard changes to November promo?')).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Discard changes' }));
    await settle();
    expect(h.push).toHaveBeenCalledWith('/omnichannel/broadcasts');
  });

  it('leaves at once on Discard when nothing was typed', async () => {
    render(<NewBroadcastPage />, true);
    await settle();
    fireEvent.click(screen.getByRole('button', { name: 'Discard changes' }));
    await settle();
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(h.push).toHaveBeenCalledWith('/omnichannel/broadcasts');
  });
});

describe('both looks send the same requests for the same input', () => {
  async function run(fx: boolean, act1: () => Promise<void>): Promise<unknown[]> {
    h.calls.length = 0;
    const view = render(<NewBroadcastPage />, fx);
    await settle();
    await fillNewBroadcast();
    await act1();
    await settle();
    const out = requests();
    view.unmount();
    resetPageActionsForTests();
    return out;
  }

  it('Send now', async () => {
    const off = await run(false, async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Send now' }));
    });
    const on = await run(true, async () => {
      fireEvent.click(mainAction());
    });
    expect(off.length).toBe(2);
    expect(on).toEqual(off);
  });

  it('Schedule', async () => {
    const off = await run(false, async () => {
      fireEvent.click(screen.getByRole('radio', { name: 'Schedule for' }));
      await settle();
      fireEvent.change(screen.getByLabelText('Scheduled for'), { target: { value: '2031-03-20T14:30' } });
      await settle();
      fireEvent.click(screen.getByRole('button', { name: 'Schedule broadcast' }));
    });
    const on = await run(true, async () => {
      fireEvent.click(screen.getByRole('radio', { name: 'Schedule for' }));
      await settle();
      const date = screen.getByLabelText('Date');
      fireEvent.change(date, { target: { value: '20 Mar 2031' } });
      fireEvent.blur(date);
      await settle();
      await pick('Time', '2:30 pm');
      fireEvent.click(mainAction());
    });
    expect(off.length).toBe(2);
    expect((off[1] as unknown[])[3]).toBe('2031-03-20T06:30:00.000Z');
    expect(on).toEqual(off);
  });

  it('Save as draft', async () => {
    const off = await run(false, async () => {
      fireEvent.click(screen.getByRole('button', { name: /^Create|^Save/ }));
    });
    const on = await run(true, async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Save as draft' }));
    });
    expect(off.length).toBe(1);
    expect(on).toEqual(off);
  });

  it('Send a test message', async () => {
    const off = await run(false, async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Send test message' }));
      await settle();
      await pick('Test-send contact', 'Aisyah Rahman (+60 12-345 6789)');
      fireEvent.click(screen.getByRole('button', { name: 'Send test' }));
    });
    const on = await run(true, async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Send a test message' }));
      await settle();
      await pick('Test-send contact', 'Aisyah Rahman (+60 12-345 6789)');
      fireEvent.click(screen.getByRole('button', { name: 'Send test' }));
    });
    expect(off.length).toBe(2);
    expect(on).toEqual(off);
  });
});

describe('done page after a send with the switch on', () => {
  it('records the send, opens the done page, and View delivery leaves it', async () => {
    const view = render(<NewBroadcastPage />, true);
    await settle();
    await fillNewBroadcast();
    fireEvent.click(mainAction());
    await waitFor(() => expect(h.push).toHaveBeenCalledWith('/omnichannel/broadcasts/bc-new'));
    expect(h.calls.some((c) => String((c as unknown[])[0]).startsWith('toast.'))).toBe(false);
    expect(peekBroadcastDone('bc-new')).toMatchObject({ mode: 'now', byWhom: 'Kay Tan', audienceCount: 23 });
    view.unmount();
    resetPageActionsForTests();

    h.params = { id: 'bc-new' };
    h.pathname = '/omnichannel/broadcasts/bc-new';
    h.broadcast = broadcastRow({ id: 'bc-new', status: 'SENDING', statusLabel: 'Sending', startedAt: '2026-11-18T06:14:00Z' });
    render(<BroadcastFormPage />, true);
    await settle();
    expect(screen.getByText('“November promo” is going to 23 contacts')).toBeTruthy();
    expect(screen.getByText(/on Maju Sales WhatsApp with the promo_nov_2026 template, by Kay Tan\./)).toBeTruthy();
    expect(screen.getByText(/2:14 pm/)).toBeTruthy();
    expect(screen.getByText('Delivery counts update on the broadcast’s page as they come in.')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Back to broadcasts' }).getAttribute('href')).toBe('/omnichannel/broadcasts');
    expect(mainAction().getAttribute('aria-label')).toBe('View delivery of November promo');
    // A reload would open the ordinary page: the record is used once.
    expect(peekBroadcastDone('bc-new')).toBeNull();

    fireEvent.click(mainAction());
    await settle();
    expect(screen.queryByText('“November promo” is going to 23 contacts')).toBeNull();
    expect(screen.getByRole('tab', { name: /Recipients/ })).toBeTruthy();
  });

  it('never shows the done page with the switch off', async () => {
    setBroadcastDone('bc-1', { mode: 'now', byWhom: 'Kay Tan', audienceCount: 23, pressedAt: '2026-11-18T06:13:59Z' });
    h.pathname = '/omnichannel/broadcasts/bc-1';
    h.broadcast = broadcastRow({ status: 'SENDING', statusLabel: 'Sending' });
    render(<BroadcastFormPage />, false);
    await settle();
    expect(screen.queryByText(/is going to/)).toBeNull();
    expect(screen.getByRole('tab', { name: /Recipients/ })).toBeTruthy();
  });
});
