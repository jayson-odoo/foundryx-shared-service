/**
 * Mock web chat admin service (plan 34 / A7b, Phase A / S0). In-memory
 * `WebchatConfig` store keyed by channel id, sharing the channel row store
 * with `channel-service.mock.ts` so a freshly "connected" channel appears in
 * the mock channels list immediately (mirrors the Messenger/Instagram mock's
 * `__mockProvisionMetaChannel` pattern).
 *
 * The widget SECRET never lives in `WebchatConfig` (D-A7B-10) - it is kept in
 * a separate, never-read-back store and only ever handed to the caller by
 * `connect`/`rotateSecret` (AC-WEB-06/18/19).
 */
import type {
  ConnectWebchatInput,
  ConnectWebchatResult,
  RotateWidgetSecretResult,
  SignOutVisitorsResult,
  UpdateWebchatConfigInput,
  WebchatConfig,
} from '@/types/omnichannel';
import { __mockProvisionWebchatChannel } from './channel-service.mock';
import { delay } from './mock-query';
import type { WebchatService } from './webchat-service';

function defaultConfig(widgetKey: string, allowedOrigins: string[]): WebchatConfig {
  return {
    widgetKey,
    allowedOrigins,
    tokenEpoch: 0,
    appearance: {
      accentColor: '#FF5A00',
      position: 'right',
      headerTitle: 'Chat with us',
      agentDisplayName: 'Support',
    },
    greeting: 'Hi! How can we help you today?',
    offlineGreeting: "We're offline right now - leave a message and we'll reply.",
    preChat: { askName: true, askEmail: true, askPhone: false },
    snippet: `<script src="https://app.example/omnichannel/widget/${widgetKey}.js" async></script>`,
  };
}

/** Config store, seeded for the dev seed channel `chn-web-001` (S0 MOCK,
 *  matches `channel-service.mock.ts`'s seeded row). */
const configs: Record<string, WebchatConfig> = {
  'chn-web-001': defaultConfig('wk_demo0000000000000000000001', ['http://localhost:3012']),
};

/** Widget secrets - a channel id -> secret map that NO read method exposes;
 *  only `connect`/`rotateSecret` ever return the current value. */
const secrets: Record<string, string> = {
  'chn-web-001': 'whsec_demo_seed_secret_never_shown_again',
};

function mintSecret(): string {
  return `whsec_${crypto.randomUUID().replace(/-/g, '')}`;
}

export const mockWebchatService: WebchatService = {
  async connect(input: ConnectWebchatInput): Promise<ConnectWebchatResult> {
    const channel = __mockProvisionWebchatChannel(input.workspaceId, input.name);
    const widgetKey = channel.widgetKey ?? `wk_${channel.id}`;
    configs[channel.id] = defaultConfig(widgetKey, input.allowedOrigins);
    const widgetSecret = mintSecret();
    secrets[channel.id] = widgetSecret;
    return delay({ ...channel, widgetSecret });
  },

  async getConfig(channelId: string): Promise<WebchatConfig> {
    const config = configs[channelId];
    if (!config) throw new Error('Widget configuration not found');
    return delay(config, 200);
  },

  async updateConfig(channelId: string, input: UpdateWebchatConfigInput): Promise<WebchatConfig> {
    const current = configs[channelId];
    if (!current) throw new Error('Widget configuration not found');
    const next: WebchatConfig = {
      ...current,
      allowedOrigins: input.allowedOrigins ?? current.allowedOrigins,
      appearance: { ...current.appearance, ...input.appearance },
      greeting: input.greeting ?? current.greeting,
      offlineGreeting: input.offlineGreeting ?? current.offlineGreeting,
      preChat: { ...current.preChat, ...input.preChat },
    };
    configs[channelId] = next;
    return delay(next, 250);
  },

  async rotateSecret(channelId: string): Promise<RotateWidgetSecretResult> {
    if (!configs[channelId]) throw new Error('Widget configuration not found');
    const widgetSecret = mintSecret();
    secrets[channelId] = widgetSecret;
    return delay({ widgetSecret }, 250);
  },

  async signOutVisitors(channelId: string): Promise<SignOutVisitorsResult> {
    const current = configs[channelId];
    if (!current) throw new Error('Widget configuration not found');
    const next = { ...current, tokenEpoch: current.tokenEpoch + 1 };
    configs[channelId] = next;
    return delay({ tokenEpoch: next.tokenEpoch }, 250);
  },
};
