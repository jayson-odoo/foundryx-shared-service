/**
 * Onboarding service - channel provisioning via Meta Embedded Signup.
 *
 * The Embedded Signup popup (Meta JS SDK when configured, a simulated dialog
 * otherwise) hands the client an `EmbeddedSignupResult` (auth code + WABA/
 * phone ids). `completeOnboarding` sends that to the backend, which exchanges
 * the code for a permanent token and auto-provisions the channel (plan 04
 * §5.2). `listMetaPages`/`connectMetaChannel` (plan 32 / A7a - Messenger +
 * Instagram) exchange a Meta OAuth code for the connectable pages, then
 * finalize the connect for the one picked - the dev-safe backend adapter
 * (`not settings.meta_app_id`) makes both real calls work with no Meta app
 * (canned sandbox pages), so the wizard's "simulated" path reuses this SAME
 * real service boundary rather than a parallel mock data source.
 *
 * `onboarding-service.mock.ts` remains the standing frontend-first mock for
 * future tuning; the app no longer binds to it (mirrors `channel-service.ts`/
 * `conversation-service.ts`).
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

export const onboardingService: OnboardingService = realOnboardingService;
