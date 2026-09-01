/**
 * Onboarding service - channel provisioning via Meta Embedded Signup.
 *
 * The Embedded Signup popup (Meta JS SDK in Phase B, a simulated dialog in
 * Phase A) hands the client an `EmbeddedSignupResult` (auth code + WABA/phone
 * ids). `completeOnboarding` sends that to the backend, which exchanges the code
 * for a permanent token and auto-provisions the channel (plan 04 §5.2).
 *
 * Phase A binds the MOCK; Phase B swaps to the real api-client impl (bottom).
 */
import type { Channel, EmbeddedSignupResult, ManualConnectInput } from '@/types/omnichannel';
import { realOnboardingService } from './onboarding-service.real';

export interface OnboardingService {
  /** Exchange the signup result + provision the channel. Returns the new channel. */
  completeOnboarding(workspaceId: string, result: EmbeddedSignupResult): Promise<Channel>;
  /** Manual connect with a pasted token + phone ids (validation escape hatch). */
  manualConnect(input: ManualConnectInput): Promise<Channel>;
}

// Phase B: real api-client implementation. (Mock retained in *.mock.ts.)
export const onboardingService: OnboardingService = realOnboardingService;
