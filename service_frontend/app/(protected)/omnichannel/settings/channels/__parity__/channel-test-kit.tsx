/**
 * Shared fixtures and service stand-ins for the channels pages' switch-off
 * parity tests and their switch-on request tests (Foundryx UIUX, slice
 * W2-CHAN). Every service call lands in `calls` with its arguments, so a test
 * can compare what reached the backend with the switch off and with it on.
 *
 * Test files mock the services with factories that import this module:
 *   vi.mock('@/services/channel-service', async () => (await import('./channel-test-kit')).channelServiceMock);
 */
import { act } from '@testing-library/react';
import { parityHtml as baseParityHtml } from '@/components/fx/__parity__/parity-utils';
import type { Channel, ChannelProfile, WebchatConfig, Workspace } from '@/types/omnichannel';
import type { TemplateDetail, TemplateManageItem } from '@/types/whatsapp-template';
import type { WebhookEndpoint } from '@/types/whatsapp-webhook';

/** Every recorded service call and toast, in order. */
export const calls: unknown[][] = [];

export function resetCalls(): void {
  calls.length = 0;
}

/** Only the calls that write data or send something (no reads, no toasts). */
export const WRITE_CALLS = new Set([
  'channel.update',
  'channel.saveProfile',
  'channel.testConnection',
  'channel.syncConfig',
  'channel.syncProfile',
  'channel.replaceChannelToken',
  'channel.disconnect',
  'channel.restore',
  'channel.remove',
  'webchat.connect',
  'webchat.updateConfig',
  'webchat.rotateSecret',
  'webchat.signOutVisitors',
  'onboarding.completeOnboarding',
  'onboarding.manualConnect',
  'onboarding.listMetaPages',
  'onboarding.connectMetaChannel',
  'webhook.create',
  'webhook.update',
  'webhook.rotate',
  'webhook.enable',
  'webhook.disable',
  'webhook.remove',
  'template.saveDraft',
  'template.edit',
  'template.submit',
  'template.remove',
  'template.sync',
  'template.uploadSample',
  'pending.park',
]);

export function writeCalls(): unknown[][] {
  return calls.filter((c) => WRITE_CALLS.has(String(c[0])));
}

/** React 19's `_r_N_` ids renamed in order, and timings masked. */
export function parityHtml(root: Element): string {
  const seen = new Map<string, string>();
  return baseParityHtml(root)
    .replace(/_r_[0-9a-z]+_/g, (id) => {
      if (!seen.has(id)) seen.set(id, `_rid${seen.size}_`);
      return seen.get(id) as string;
    })
    .replace(/(animation|transition)-duration:\s*[0-9.]+m?s/g, '$1-duration: <t>');
}

export async function settle(ms = 50): Promise<void> {
  await act(async () => {
    await new Promise((r) => setTimeout(r, ms));
  });
}

// --- fixtures ---------------------------------------------------------------

export function channel(overrides: Partial<Channel> = {}): Channel {
  return {
    id: 'chn-1',
    tenantId: 'tenant-1',
    workspaceId: 'wsp-1',
    workspaceName: 'Default workspace',
    channelType: 'WHATSAPP',
    name: 'Maju Sales WhatsApp',
    status: 'ACTIVE',
    isActive: true,
    wabaId: 'waba-1',
    phoneNumberId: 'pn-1',
    displayPhoneNumber: '+60 3-7890 1200',
    businessAccountName: 'Maju Trading Sdn Bhd',
    verifiedName: 'Maju Sales',
    lastVerifiedAt: '2026-11-17T06:14:00Z',
    profileSyncedAt: null,
    externalAccountId: null,
    externalAccountName: null,
    widgetKey: null,
    isTrashed: false,
    createdAt: '2026-07-07T10:00:00Z',
    updatedAt: '2026-07-07T10:00:00Z',
    ...overrides,
  };
}

export const CHANNELS: Channel[] = [
  channel(),
  channel({
    id: 'chn-2',
    name: 'Support line',
    status: 'ERROR',
    displayPhoneNumber: '+60 12-345 6789',
    lastVerifiedAt: null,
  }),
  channel({
    id: 'chn-3',
    channelType: 'FACEBOOK',
    name: 'Maju Messenger',
    displayPhoneNumber: null,
    phoneNumberId: null,
    wabaId: null,
    businessAccountName: null,
    verifiedName: null,
    externalAccountId: 'pg-702',
    externalAccountName: 'Maju Concierge',
  }),
];

export const PROFILE: ChannelProfile = {
  about: 'Open daily',
  address: '1 Jalan Maju, Kuala Lumpur',
  description: 'Office supplies',
  email: 'hello@maju.example',
  vertical: '',
  website1: 'https://maju.example',
  website2: '',
  profilePictureUrl: null,
  profileSyncedAt: null,
};

export const WEBCHAT_CONFIG: WebchatConfig = {
  widgetKey: 'wk_0123456789abcdef0123456789abcd',
  allowedOrigins: ['https://maju.example'],
  tokenEpoch: 1,
  appearance: { accentColor: '#FF5A00', position: 'right', headerTitle: 'Chat with us', agentDisplayName: 'Maju' },
  greeting: 'Hi there',
  offlineGreeting: 'We are away',
  preChat: { askName: true, askEmail: false, askPhone: false },
  snippet: '<script src="https://widget.example/w.js" data-key="wk"></script>',
};

export const WORKSPACES: Workspace[] = [
  {
    id: 'wsp-1',
    tenantId: 'tenant-1',
    name: 'Default workspace',
    status: 'ACTIVE',
    channelCount: 1,
    memberCount: 1,
    isDefault: true,
    isTrashed: false,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  } as Workspace,
];

export function endpoint(overrides: Partial<WebhookEndpoint> = {}): WebhookEndpoint {
  return {
    id: 'whe-1',
    tenantId: 'tenant-1',
    workspaceId: 'wsp-1',
    channelId: 'chn-1',
    name: 'CRM sync',
    url: 'https://hooks.maju.example/wa',
    events: ['message.inbound', 'message.status'],
    status: 'ACTIVE',
    consecutiveFailures: 0,
    lastSuccessAt: '2026-11-17T06:14:00Z',
    disabledAt: null,
    disabledReason: null,
    createdAt: '2026-07-07T10:00:00Z',
    updatedAt: '2026-07-07T10:00:00Z',
    registeredByKeyName: null,
    ...overrides,
  };
}

export function templateItem(overrides: Partial<TemplateManageItem> = {}): TemplateManageItem {
  return {
    id: 'tpl-1',
    channelId: 'chn-1',
    name: 'order_update',
    language: 'en_US',
    category: 'UTILITY',
    status: 'LOCAL_DRAFT',
    quality: null,
    rejectedReason: null,
    bodyPreview: 'Hi {{1}}, your order is on its way.',
    variableCount: 1,
    metaTemplateId: null,
    lastSyncedAt: null,
    createdAt: '2026-11-01T02:00:00Z',
    ...overrides,
  };
}

export function templateDetail(overrides: Partial<TemplateDetail> = {}): TemplateDetail {
  return {
    ...templateItem(),
    doc: {
      name: 'order_update',
      category: 'UTILITY',
      language: 'en_US',
      header: { format: 'TEXT', text: 'Order update', example: null },
      body: { text: 'Hi {{1}}, your order is on its way.', examples: ['Aisyah'] },
      footer: { text: 'Maju Trading' },
      buttons: [{ type: 'QUICK_REPLY', text: 'Thanks' }],
    },
    components: [],
    ...overrides,
  } as TemplateDetail;
}

// --- service stand-ins --------------------------------------------------------

/** Mutable answers a test may change before rendering. */
export const answers = {
  channel: channel() as Channel,
  testOk: true,
  manualFails: false,
  templateDetail: templateDetail() as TemplateDetail,
};

const rec =
  <R,>(name: string, result: (...args: unknown[]) => R) =>
  (...args: unknown[]): R => {
    calls.push([name, ...args]);
    return result(...args);
  };

const ok = <T,>(value: T) => Promise.resolve(value);

export const channelServiceMock = {
  channelService: {
    list: (...args: unknown[]) => {
      calls.push(['channel.list', ...args]);
      return ok({ data: CHANNELS, total: CHANNELS.length, page: 0 });
    },
    get: (...args: unknown[]) => {
      calls.push(['channel.get', ...args]);
      return ok(answers.channel);
    },
    getAt: () => ok({ channel: null, total: 0 }),
    listByWorkspace: () => ok(CHANNELS),
    update: rec('channel.update', (_id, input) => ok({ ...answers.channel, ...(input as object) })),
    testConnection: rec('channel.testConnection', () =>
      ok(
        answers.testOk
          ? { ok: true, message: 'Connection OK.', checkedAt: '2026-11-18T06:14:00Z' }
          : { ok: false, message: 'Access token expired or revoked.', checkedAt: '2026-11-18T06:14:00Z' },
      ),
    ),
    syncConfig: rec('channel.syncConfig', () => ok(answers.channel)),
    getProfile: () => ok(PROFILE),
    syncProfile: rec('channel.syncProfile', () => ok(PROFILE)),
    saveProfile: rec('channel.saveProfile', (_id, input) => ok({ ...PROFILE, ...(input as object) })),
    replaceChannelToken: rec('channel.replaceChannelToken', () =>
      ok({ ...answers.channel, status: 'ACTIVE', subscribed: true, tokenExpiresAt: null }),
    ),
    disconnect: rec('channel.disconnect', () => ok(undefined)),
    restore: rec('channel.restore', () => ok(undefined)),
    remove: rec('channel.remove', () => ok(undefined)),
    exportCsv: () => ok(''),
  },
};

export const webchatServiceMock = {
  webchatService: {
    connect: rec('webchat.connect', (input) =>
      ok({
        ...channel({
          id: 'chn-web',
          channelType: 'WEBCHAT',
          name: (input as { name: string }).name,
          displayPhoneNumber: null,
        }),
        widgetSecret: 'wsec_live_0123456789abcdefa91c',
      }),
    ),
    getConfig: () => ok(WEBCHAT_CONFIG),
    updateConfig: rec('webchat.updateConfig', () => ok(WEBCHAT_CONFIG)),
    rotateSecret: rec('webchat.rotateSecret', () => ok({ widgetSecret: 'wsec_live_rotated0123456789b2d4' })),
    signOutVisitors: rec('webchat.signOutVisitors', () => ok({ tokenEpoch: 2 })),
  },
};

export const onboardingServiceMock = {
  onboardingService: {
    completeOnboarding: rec('onboarding.completeOnboarding', () =>
      ok(channel({ id: 'chn-new', name: 'Foundryx Retail (Sandbox)' })),
    ),
    manualConnect: rec('onboarding.manualConnect', () =>
      answers.manualFails
        ? Promise.reject(new Error('Meta rejected the token.'))
        : ok(channel({ id: 'chn-manual', tokenExpiresAt: null })),
    ),
    listMetaPages: rec('onboarding.listMetaPages', () =>
      ok({
        sessionId: 'sess-1',
        expiresAt: '2026-11-18T07:00:00Z',
        pages: [
          { id: 'pg-701', name: 'Maju Events', connected: true },
          { id: 'pg-702', name: 'Maju Concierge', connected: false, igAccountId: 'ig-702', igUsername: 'maju.concierge' },
        ],
      }),
    ),
    connectMetaChannel: rec('onboarding.connectMetaChannel', () =>
      ok(
        channel({
          id: 'chn-fb',
          channelType: 'FACEBOOK',
          name: 'Maju Concierge (Messenger)',
          displayPhoneNumber: null,
          externalAccountName: 'Maju Concierge',
        }),
      ),
    ),
  },
};

export const webhookServiceMock = {
  whatsappWebhookService: {
    list: (...args: unknown[]) => {
      calls.push(['webhook.list', ...args]);
      return ok([endpoint()]);
    },
    listForWorkspace: () => ok([endpoint()]),
    create: rec('webhook.create', (_c, input) =>
      ok({ endpoint: endpoint({ id: 'whe-2', ...(input as object) }), signingSecret: 'whsec_0123456789abcdefa91c' }),
    ),
    update: rec('webhook.update', () => ok(endpoint())),
    rotate: rec('webhook.rotate', () => ok({ signingSecret: 'whsec_rotated0123456789b2d4' })),
    enable: rec('webhook.enable', () => ok(endpoint())),
    disable: rec('webhook.disable', () => ok(endpoint({ status: 'DISABLED' }))),
    remove: rec('webhook.remove', () => ok(undefined)),
    deliveries: () => ok([]),
  },
};

export const templateServiceMock = {
  whatsappTemplateService: {
    listManage: (...args: unknown[]) => {
      calls.push(['template.listManage', ...args]);
      return ok({
        data: [
          templateItem(),
          templateItem({ id: 'tpl-2', name: 'promo_nov_2026', status: 'APPROVED', category: 'MARKETING' }),
        ],
        total: 2,
        page: 0,
      });
    },
    get: () => ok(answers.templateDetail),
    saveDraft: rec('template.saveDraft', (_c, doc) => ok({ ...templateDetail({ id: 'tpl-new' }), doc })),
    edit: rec('template.edit', (_c, id, doc) => ok({ ...answers.templateDetail, id, doc })),
    submit: rec('template.submit', (_c, id) => ok({ ...answers.templateDetail, id, status: 'PENDING' })),
    remove: rec('template.remove', () => ok(undefined)),
    sync: rec('template.sync', () => ok([])),
    uploadSample: rec('template.uploadSample', () => ok({ sampleKey: 'sample-1', mime: 'image/png' })),
  },
};

export const workspaceServiceMock = {
  workspaceService: {
    list: () => ok({ data: WORKSPACES, total: WORKSPACES.length, page: 0 }),
    get: () => ok(WORKSPACES[0]),
  },
};

export const pendingActionsServiceMock = {
  pendingActionsService: {
    park: rec('pending.park', () =>
      ok({ id: 'pa-1', status: 'PENDING', executeAt: new Date(Date.now() + 10_000).toISOString(), windowSeconds: 10 }),
    ),
    cancel: () => ok({ id: 'pa-1', status: 'CANCELLED' }),
    current: () => ok({ pending: null }),
  },
};

export const preferencesServiceMock = {
  preferencesService: {
    get: () => ok(null),
    save: () => ok(undefined),
  },
};

const toastFn = (kind: string) => (...args: unknown[]) => {
  calls.push([`toast.${kind}`, ...args]);
  return 'toast-id';
};

export const toastMock = {
  toast: {
    success: toastFn('success'),
    error: toastFn('error'),
    info: toastFn('info'),
    warning: toastFn('warning'),
    message: toastFn('message'),
    custom: toastFn('custom'),
    dismiss: toastFn('dismiss'),
    fxDone: toastFn('fxDone'),
  },
};
