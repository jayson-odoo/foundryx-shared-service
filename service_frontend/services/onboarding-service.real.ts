/**
 * Real onboarding service - POSTs the Embedded Signup result to FastAPI, which
 * exchanges the code for a permanent token and provisions the channel. Wired in
 * Phase B (plan 04 §5.2 → `POST /omnichannel/onboarding/oauth-callback`).
 */
import { apiFetch } from '@/lib/api-client';
import type { Channel, EmbeddedSignupResult, ManualConnectInput } from '@/types/omnichannel';
import type { OnboardingService } from './onboarding-service';

/**
 * The real backend only implements the WhatsApp routes so far - `listMetaPages`
 * / `connectMetaChannel` (plan 32 / A7a) land in S3 and get their own real
 * implementation then; `onboarding-service.ts` binds those two to the mock in
 * the meantime (S0 MOCK).
 */
export const realOnboardingService: Pick<OnboardingService, 'completeOnboarding' | 'manualConnect'> = {
  completeOnboarding(workspaceId, result: EmbeddedSignupResult) {
    return apiFetch<Channel>('/omnichannel/onboarding/oauth-callback', {
      method: 'POST',
      body: JSON.stringify({ workspaceId, ...result }),
    });
  },
  manualConnect(input: ManualConnectInput) {
    return apiFetch<Channel>('/omnichannel/onboarding/manual-connect', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },
};
