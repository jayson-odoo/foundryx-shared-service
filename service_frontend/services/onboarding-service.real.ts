/**
 * Real onboarding service - POSTs the Embedded Signup result to FastAPI, which
 * exchanges the code for a permanent token and provisions the channel. Wired in
 * Phase B (plan 04 §5.2 → `POST /omnichannel/onboarding/oauth-callback`).
 *
 * `listMetaPages`/`connectMetaChannel` (plan 32 / A7a) hit the real
 * `/onboarding/meta/*` routes landed in S3 - wired here in S6.
 */
import { apiFetch } from '@/lib/api-client';
import type {
  Channel,
  EmbeddedSignupResult,
  ListMetaPagesInput,
  ManualConnectInput,
  MetaConnectInput,
  MetaPagesResult,
} from '@/types/omnichannel';
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
  listMetaPages(input: ListMetaPagesInput) {
    return apiFetch<MetaPagesResult>('/omnichannel/onboarding/meta/pages', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },
  connectMetaChannel(input: MetaConnectInput) {
    return apiFetch<Channel>('/omnichannel/onboarding/meta/connect', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },
};
