/**
 * Onboarding service - channel provisioning via Meta Embedded Signup.
 *
 * The Embedded Signup popup (Meta JS SDK in Phase B, a simulated dialog in
 * Phase A) hands the client an `EmbeddedSignupResult` (auth code + WABA/phone
 * ids). `completeOnboarding` sends that to the backend, which exchanges the code
 * for a permanent token and auto-provisions the channel (plan 04 §5.2).
 *
 * `completeOnboarding` / `manualConnect` are bound to the real api-client impl
 * (WhatsApp already shipped past Phase A). `listMetaPages` / `connectMetaChannel`
 * (plan 32 / A7a - Messenger + Instagram) are S0 MOCK: the real
 * `/omnichannel/onboarding/meta/*` routes land in S3, wired in S6. Swapping
 * each is a one-line change at this boundary, per method.
 */
import type {
  Channel,
  EmbeddedSignupResult,
  ListMetaPagesInput,
  ManualConnectInput,
  MetaConnectInput,
  MetaPagesResult,
} from '@/types/omnichannel';
import { realOnboardingService } from './onboarding-service.real';
import { mockOnboardingService } from './onboarding-service.mock';

export interface OnboardingService {
  /** Exchange the signup result + provision the channel. Returns the new channel. */
  completeOnboarding(workspaceId: string, result: EmbeddedSignupResult): Promise<Channel>;
  /** Manual connect with a pasted token + phone ids (validation escape hatch). */
  manualConnect(input: ManualConnectInput): Promise<Channel>;
  /** Exchange a Messenger/Instagram OAuth code for the connectable pages
   *  (and, for Instagram, each page's linked professional account). */
  listMetaPages(input: ListMetaPagesInput): Promise<MetaPagesResult>;
  /** Finalize the connect for the page/account picked from `listMetaPages`. */
  connectMetaChannel(input: MetaConnectInput): Promise<Channel>;
}

export const onboardingService: OnboardingService = {
  completeOnboarding: realOnboardingService.completeOnboarding,
  manualConnect: realOnboardingService.manualConnect,
  // S0 MOCK - swap to real in S6 (POST /omnichannel/onboarding/meta/pages).
  listMetaPages: mockOnboardingService.listMetaPages,
  // S0 MOCK - swap to real in S6 (POST /omnichannel/onboarding/meta/connect).
  connectMetaChannel: mockOnboardingService.connectMetaChannel,
};
