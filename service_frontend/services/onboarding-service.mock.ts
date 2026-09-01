/**
 * Mock onboarding service (Phase A). Simulates the backend token-exchange +
 * auto-provision step: turns an Embedded Signup result into a channel row in the
 * shared mock channel store.
 *
 * MOCK_WABA_OPTIONS feeds the simulated Embedded Signup popup so the prototype
 * can demonstrate "pick your WhatsApp number" without the real Meta SDK.
 */
import type { MockWabaOption } from '@/types/omnichannel';
import type { OnboardingService } from './onboarding-service';
import { __mockProvisionChannel } from './channel-service.mock';
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
};
