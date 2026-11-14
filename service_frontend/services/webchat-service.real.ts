/**
 * Real web chat admin service - talks to FastAPI via the shared api-client.
 * Endpoints per plan 34 / A7b §5.1 - NOT wired at runtime until slice S6
 * (AC-WEB-63); `webchat-service.ts` binds `mockWebchatService` until then.
 * Written now so the S6 swap is a one-line export change, no call-site edits.
 */
import { apiFetch } from '@/lib/api-client';
import type {
  ConnectWebchatResult,
  RotateWidgetSecretResult,
  SignOutVisitorsResult,
  UpdateWebchatConfigInput,
  WebchatConfig,
} from '@/types/omnichannel';
import type { WebchatService } from './webchat-service';

export const realWebchatService: WebchatService = {
  connect(input) {
    return apiFetch<ConnectWebchatResult>('/omnichannel/onboarding/webchat/connect', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },
  getConfig(channelId) {
    return apiFetch<WebchatConfig>(`/omnichannel/channels/${channelId}/widget`);
  },
  updateConfig(channelId, input: UpdateWebchatConfigInput) {
    return apiFetch<WebchatConfig>(`/omnichannel/channels/${channelId}/widget`, {
      method: 'PUT',
      body: JSON.stringify(input),
    });
  },
  rotateSecret(channelId) {
    return apiFetch<RotateWidgetSecretResult>(
      `/omnichannel/channels/${channelId}/widget/rotate-secret`,
      { method: 'POST' },
    );
  },
  signOutVisitors(channelId) {
    return apiFetch<SignOutVisitorsResult>(
      `/omnichannel/channels/${channelId}/widget/sign-out-visitors`,
      { method: 'POST' },
    );
  },
};
