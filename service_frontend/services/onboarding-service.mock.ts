/**
 * Mock onboarding service (Phase A). Simulates the backend token-exchange +
 * auto-provision step: turns an Embedded Signup result into a channel row in the
 * shared mock channel store.
 *
 * MOCK_WABA_OPTIONS feeds the simulated Embedded Signup popup so the prototype
 * can demonstrate "pick your WhatsApp number" without the real Meta SDK.
 */
import type {
  ListMetaPagesInput,
  MetaConnectInput,
  MetaPageOption,
  MetaPagesResult,
  MockWabaOption,
} from '@/types/omnichannel';
import type { OnboardingService } from './onboarding-service';
import { __mockExternalAccountInUse, __mockProvisionChannel, __mockProvisionMetaChannel } from './channel-service.mock';
import { delay } from './mock-query';

/** WhatsApp numbers the (simulated) Meta popup offers to connect. */
export const MOCK_WABA_OPTIONS: MockWabaOption[] = [
  {
    wabaId: 'waba-901',
    businessName: 'Foundryx Events Co.',
    phoneNumberId: 'pn-901',
    displayPhoneNumber: '+65 8900 1234',
  },
  {
    wabaId: 'waba-902',
    businessName: 'Foundryx Concierge',
    phoneNumberId: 'pn-902',
    displayPhoneNumber: '+60 12 345 6789',
  },
];

/**
 * Facebook Pages the (simulated) Messenger/Instagram Business Login offers to
 * connect - mirrors `MOCK_WABA_OPTIONS`'s role for WhatsApp. A page already
 * bound to a live channel is filtered out at read time (AC-CHN-02), not baked
 * into this seed, so "already connected" stays demonstrable end to end.
 */
const MOCK_META_PAGES: MetaPageOption[] = [
  { id: 'pg-701', name: 'Foundryx Events Co.', connected: false, igAccountId: 'ig-701', igUsername: 'foundryx.events' },
  { id: 'pg-702', name: 'Foundryx Concierge', connected: false, igAccountId: 'ig-702', igUsername: 'foundryx.concierge' },
  { id: 'pg-703', name: 'Foundryx VIP Desk', connected: false },
];

let sessionSeq = 0;

/** Synchronous read used by the simulated dialog (mirrors the annotated list
 *  `listMetaPages` returns) - a page/account already bound to a live channel
 *  carries `connected: true`; the picker filters those out (AC-CHN-02), same
 *  rule the real `/meta/pages` response will carry. */
export function mockMetaPageOptions(channelType: 'FACEBOOK' | 'INSTAGRAM'): MetaPageOption[] {
  return MOCK_META_PAGES.filter((p) => channelType !== 'INSTAGRAM' || p.igAccountId).map((p) => ({
    ...p,
    connected: __mockExternalAccountInUse(p.id) || (!!p.igAccountId && __mockExternalAccountInUse(p.igAccountId)),
  }));
}

export const mockOnboardingService: OnboardingService = {
  async completeOnboarding(workspaceId, result) {
    // Simulate the backend code→token exchange + Graph API provisioning latency.
    const channel = __mockProvisionChannel(workspaceId, result);
    return delay(channel, 600);
  },
  async manualConnect(input) {
    const channel = __mockProvisionChannel(input.workspaceId, {
      code: 'manual',
      wabaId: input.wabaId ?? '',
      phoneNumberId: input.phoneNumberId ?? '',
      displayPhoneNumber: input.phoneNumber ?? input.phoneNumberId ?? '',
      businessName: 'WhatsApp (manual)',
    });
    return delay(channel, 400);
  },

  // ---- plan 32 / A7a - Messenger + Instagram (standing mock, not wired) ---
  async listMetaPages(input: ListMetaPagesInput): Promise<MetaPagesResult> {
    // Instagram only offers pages whose linked account is present (D-A7-14/44).
    const result: MetaPagesResult = {
      sessionId: `meta-session-${++sessionSeq}`,
      expiresAt: new Date(Date.now() + 5 * 60_000).toISOString(),
      pages: mockMetaPageOptions(input.channelType),
    };
    return delay(result, 500);
  },

  async connectMetaChannel(input: MetaConnectInput) {
    const page = MOCK_META_PAGES.find((p) => p.id === input.pageId);
    if (!page) throw new Error('Page not found.');
    const externalAccountId = input.channelType === 'INSTAGRAM' ? page.igAccountId : page.id;
    if (!externalAccountId) throw new Error('Page not found.');
    if (__mockExternalAccountInUse(externalAccountId)) {
      throw new Error('This page is already connected to another channel.');
    }
    const channel = __mockProvisionMetaChannel(input.workspaceId, input.channelType, {
      externalAccountId,
      externalAccountName: input.channelType === 'INSTAGRAM' ? (page.igUsername ?? page.name) : page.name,
    });
    return delay(channel, 600);
  },
};
