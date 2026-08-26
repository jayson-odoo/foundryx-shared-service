/**
 * Consumer-webhook service - the boundary the UI talks to (via hooks/configs).
 * The barrel binds the REAL api-client implementation; the mock (`*.mock.ts`) is
 * retained for tests + frontend-first iteration. The interface IS the backend
 * contract (omnichannel Slice 4 - per-channel consumer webhooks).
 *
 * Namespaced `whatsappWebhook*` to avoid colliding with the core template
 * engine's `template-service` / the module's `whatsapp-template-service`.
 */
import type {
  WebhookEndpoint,
  WebhookEndpointInput,
  WebhookEndpointPatch,
  WebhookCreateResult,
  WebhookSecretResult,
  WebhookDelivery,
} from '@/types/whatsapp-webhook';
import { realWhatsappWebhookService } from './whatsapp-webhook-service.real';

export interface WhatsappWebhookService {
  /** All endpoints registered for a channel (newest-first by the backend). */
  list(channelId: string): Promise<WebhookEndpoint[]>;
  /** Register a new endpoint - returns the ONE-TIME signing secret. */
  create(channelId: string, input: WebhookEndpointInput): Promise<WebhookCreateResult>;
  /** Update an endpoint's name / url / events. */
  update(endpointId: string, patch: WebhookEndpointPatch): Promise<WebhookEndpoint>;
  /** Rotate the signing secret - returns the fresh ONE-TIME secret. */
  rotate(endpointId: string): Promise<WebhookSecretResult>;
  /** Re-enable a disabled / auto-disabled endpoint. */
  enable(endpointId: string): Promise<WebhookEndpoint>;
  /** Pause deliveries to an endpoint. */
  disable(endpointId: string): Promise<WebhookEndpoint>;
  /** Permanently remove an endpoint. */
  remove(endpointId: string): Promise<void>;
  /** Recent delivery attempts for an endpoint (read-only log). */
  deliveries(endpointId: string): Promise<WebhookDelivery[]>;
}

// Real api-client implementation (mock retained in *.mock.ts for tests).
export const whatsappWebhookService: WhatsappWebhookService = realWhatsappWebhookService;
