/**
 * Real onboarding service — POSTs the Embedded Signup result to FastAPI, which
 * exchanges the code for a permanent token and provisions the channel. Wired in
 * Phase B (plan 04 §5.2 → `POST /omnichannel/onboarding/oauth-callback`).
 */
import { apiFetch } from '@/lib/api-client';
import type { Channel, EmbeddedSignupResult, ManualConnectInput } from '@/types/omnichannel';
import type { OnboardingService } from './onboarding-service';

export const realOnboardingService: OnboardingService = {
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
