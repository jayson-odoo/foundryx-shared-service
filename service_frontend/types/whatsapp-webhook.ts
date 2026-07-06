/**
 * Consumer-webhook types (omnichannel Slice 4).
 *
 * Mirrors the backend `app_omnichannel` consumer-webhook contract. A tenant
 * registers webhook endpoints PER CHANNEL; FoundryX POSTs signed events to those
 * URLs on inbound messages / delivery receipts / contact updates. The signing
 * secret is returned ONCE at create/rotate and never re-read. Kept
 * framework-agnostic so the service + UI share one source.
 */

/** The three event kinds an endpoint may subscribe to. */
export type WebhookEventType = 'message.inbound' | 'message.status' | 'contact.updated';

/** Endpoint lifecycle — AUTO_DISABLED = the delivery pipeline gave up after repeated failures. */
export type WebhookStatus = 'ACTIVE' | 'DISABLED' | 'AUTO_DISABLED';

/** A registered consumer-webhook endpoint (never carries the signing secret). */
export interface WebhookEndpoint {
  id: string;
  tenantId: string;
  workspaceId: string;
  channelId: string;
  name: string;
  url: string;
  events: WebhookEventType[];
  status: WebhookStatus;
  consecutiveFailures: number;
  lastSuccessAt: string | null; // ISO
  disabledAt: string | null; // ISO
  disabledReason: string | null;
  createdAt: string; // ISO
  updatedAt: string; // ISO
}

/** Create/edit payload — a subset of the endpoint's editable fields. */
export interface WebhookEndpointInput {
  name: string;
  url: string;
  events: WebhookEventType[];
}

/** Patch payload — every field optional. */
export interface WebhookEndpointPatch {
  name?: string;
  url?: string;
  events?: WebhookEventType[];
}

/**
 * Create result — carries the ONE-TIME signing secret alongside the stored
 * endpoint. `signingSecret` is never returned by any later read.
 */
export interface WebhookCreateResult {
  endpoint: WebhookEndpoint;
  signingSecret: string;
}

/** Rotate result — the fresh one-time signing secret. */
export interface WebhookSecretResult {
  signingSecret: string;
}

/** Delivery attempt lifecycle. */
export type WebhookDeliveryStatus = 'PENDING' | 'SUCCESS' | 'FAILED';

/** A single delivery-attempt record for an endpoint (read-only log). */
export interface WebhookDelivery {
  id: string;
  eventId: string;
  eventType: WebhookEventType;
  status: WebhookDeliveryStatus;
  attemptCount: number;
  responseStatus: number | null;
  responseMs: number | null;
  error: string | null;
  lastAttemptAt: string | null; // ISO
  nextAttemptAt: string | null; // ISO
  createdAt: string; // ISO
}
