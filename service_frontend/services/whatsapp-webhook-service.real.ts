/**
 * Real consumer-webhook service — talks to FastAPI via the shared api-client.
 * Bound by the `whatsapp-webhook-service.ts` barrel. Endpoints per omnichannel
 * Slice 4.
 */
import { apiFetch } from '@/lib/api-client';
import type {
  WebhookEndpoint,
  WebhookCreateResult,
  WebhookSecretResult,
  WebhookDelivery,
} from '@/types/whatsapp-webhook';
import type { WhatsappWebhookService } from './whatsapp-webhook-service';

export const realWhatsappWebhookService: WhatsappWebhookService = {
  async list(channelId) {
    const res = await apiFetch<{ data: WebhookEndpoint[] }>(
      `/omnichannel/channels/${channelId}/webhooks`,
    );
    return res.data;
  },
  create(channelId, input) {
    return apiFetch<WebhookCreateResult>(`/omnichannel/channels/${channelId}/webhooks`, {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },
  update(endpointId, patch) {
    return apiFetch<WebhookEndpoint>(`/omnichannel/webhooks/${endpointId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    });
  },
  rotate(endpointId) {
    return apiFetch<WebhookSecretResult>(`/omnichannel/webhooks/${endpointId}/rotate`, {
      method: 'POST',
    });
  },
  enable(endpointId) {
    return apiFetch<WebhookEndpoint>(`/omnichannel/webhooks/${endpointId}/enable`, {
      method: 'POST',
    });
  },
  disable(endpointId) {
    return apiFetch<WebhookEndpoint>(`/omnichannel/webhooks/${endpointId}/disable`, {
      method: 'POST',
    });
  },
  async remove(endpointId) {
    await apiFetch<void>(`/omnichannel/webhooks/${endpointId}`, { method: 'DELETE' });
  },
  async deliveries(endpointId) {
    const res = await apiFetch<{ data: WebhookDelivery[] }>(
      `/omnichannel/webhooks/${endpointId}/deliveries`,
    );
    return res.data;
  },
};
