/**
 * PHASE 1 MOCK — in-memory consumer-webhook service.
 *
 * Retained for tests + frontend-first iteration; the app binds the REAL impl
 * (see `whatsapp-webhook-service.ts`). Mirrors the backend's create-once
 * contract: `create`/`rotate` return the signing secret exactly once, `list`
 * only ever yields the endpoint (never the secret). Seeds a spread of states
 * (ACTIVE / DISABLED / AUTO_DISABLED, with/without failures) so the tab renders
 * every surface with no backend running.
 */
import type {
  WebhookEndpoint,
  WebhookCreateResult,
  WebhookSecretResult,
  WebhookDelivery,
} from '@/types/whatsapp-webhook';
import type { WhatsappWebhookService } from './whatsapp-webhook-service';
import { delay } from './mock-query';

let counter = 0;
const endpoints: Record<string, WebhookEndpoint[]> = {};
const deliveries: Record<string, WebhookDelivery[]> = {};

function randomToken(len: number): string {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  let out = '';
  for (let i = 0; i < len; i += 1) {
    out += alphabet[Math.floor(Math.random() * alphabet.length)];
  }
  return out;
}

function secret(): string {
  return `whsec_${randomToken(40)}`;
}

/** Reset the in-memory store (test helper). */
export function __resetWebhookMock(): void {
  for (const k of Object.keys(endpoints)) delete endpoints[k];
  for (const k of Object.keys(deliveries)) delete deliveries[k];
  counter = 0;
}

function seed(channelId: string): void {
  if (endpoints[channelId]) return;
  const now = Date.now();
  const iso = (offsetMs: number) => new Date(now - offsetMs).toISOString();
  endpoints[channelId] = [
    {
      id: 'wh-001',
      tenantId: 'tnt-001',
      workspaceId: 'wsp-001',
      channelId,
      name: 'CRM sync',
      url: 'https://hooks.example.com/crm/whatsapp/inbound-and-status-updates',
      events: ['message.inbound', 'message.status'],
      status: 'ACTIVE',
      consecutiveFailures: 0,
      lastSuccessAt: iso(60_000),
      disabledAt: null,
      disabledReason: null,
      createdAt: iso(86_400_000 * 9),
      updatedAt: iso(60_000),
    },
    {
      id: 'wh-002',
      tenantId: 'tnt-001',
      workspaceId: 'wsp-001',
      channelId,
      name: 'Contact enrichment',
      url: 'https://api.partner.io/v2/contacts/webhook',
      events: ['contact.updated'],
      status: 'DISABLED',
      consecutiveFailures: 0,
      lastSuccessAt: iso(86_400_000 * 2),
      disabledAt: iso(86_400_000),
      disabledReason: null,
      createdAt: iso(86_400_000 * 20),
      updatedAt: iso(86_400_000),
    },
    {
      id: 'wh-003',
      tenantId: 'tnt-001',
      workspaceId: 'wsp-001',
      channelId,
      name: 'Analytics pipeline',
      url: 'https://collect.analytics.example.org/ingest/webhooks/whatsapp',
      events: ['message.inbound', 'message.status', 'contact.updated'],
      status: 'AUTO_DISABLED',
      consecutiveFailures: 12,
      lastSuccessAt: iso(86_400_000 * 5),
      disabledAt: iso(3_600_000),
      disabledReason: 'Endpoint returned HTTP 500 for 12 consecutive attempts.',
      createdAt: iso(86_400_000 * 30),
      updatedAt: iso(3_600_000),
    },
  ];
  deliveries['wh-001'] = [
    {
      id: 'dlv-001',
      eventId: 'evt-9001',
      eventType: 'message.inbound',
      status: 'SUCCESS',
      attemptCount: 1,
      responseStatus: 200,
      responseMs: 142,
      error: null,
      lastAttemptAt: iso(60_000),
      nextAttemptAt: null,
      createdAt: iso(60_000),
    },
    {
      id: 'dlv-002',
      eventId: 'evt-9002',
      eventType: 'message.status',
      status: 'FAILED',
      attemptCount: 3,
      responseStatus: 503,
      responseMs: 8021,
      error: 'Service Unavailable — upstream timed out after 8s.',
      lastAttemptAt: iso(120_000),
      nextAttemptAt: iso(-300_000),
      createdAt: iso(180_000),
    },
    {
      id: 'dlv-003',
      eventId: 'evt-9003',
      eventType: 'contact.updated',
      status: 'PENDING',
      attemptCount: 0,
      responseStatus: null,
      responseMs: null,
      error: null,
      lastAttemptAt: null,
      nextAttemptAt: iso(-30_000),
      createdAt: iso(20_000),
    },
  ];
}

export const mockWhatsappWebhookService: WhatsappWebhookService = {
  async list(channelId) {
    seed(channelId);
    const rows = endpoints[channelId] ?? [];
    return delay(
      [...rows].sort((a, b) => b.createdAt.localeCompare(a.createdAt)),
      200,
    );
  },

  async create(channelId, input) {
    seed(channelId);
    counter += 1;
    const nowIso = new Date().toISOString();
    const endpoint: WebhookEndpoint = {
      id: `wh-new-${String(counter).padStart(3, '0')}`,
      tenantId: 'tnt-001',
      workspaceId: 'wsp-001',
      channelId,
      name: input.name,
      url: input.url,
      events: input.events,
      status: 'ACTIVE',
      consecutiveFailures: 0,
      lastSuccessAt: null,
      disabledAt: null,
      disabledReason: null,
      createdAt: nowIso,
      updatedAt: nowIso,
    };
    endpoints[channelId] = [endpoint, ...(endpoints[channelId] ?? [])];
    return delay({ endpoint, signingSecret: secret() } satisfies WebhookCreateResult);
  },

  async update(endpointId, patch) {
    const row = findEndpoint(endpointId);
    Object.assign(row, patch, { updatedAt: new Date().toISOString() });
    return delay({ ...row }, 200);
  },

  async rotate(endpointId) {
    findEndpoint(endpointId); // 404 parity
    return delay({ signingSecret: secret() } satisfies WebhookSecretResult);
  },

  async enable(endpointId) {
    const row = findEndpoint(endpointId);
    row.status = 'ACTIVE';
    row.disabledAt = null;
    row.disabledReason = null;
    row.consecutiveFailures = 0;
    row.updatedAt = new Date().toISOString();
    return delay({ ...row }, 200);
  },

  async disable(endpointId) {
    const row = findEndpoint(endpointId);
    row.status = 'DISABLED';
    row.disabledAt = new Date().toISOString();
    row.updatedAt = row.disabledAt;
    return delay({ ...row }, 200);
  },

  async remove(endpointId) {
    for (const channelId of Object.keys(endpoints)) {
      endpoints[channelId] = (endpoints[channelId] ?? []).filter((r) => r.id !== endpointId);
    }
    return delay(undefined, 200);
  },

  async deliveries(endpointId) {
    const rows = deliveries[endpointId] ?? [];
    return delay(
      [...rows].sort((a, b) => b.createdAt.localeCompare(a.createdAt)),
      200,
    );
  },
};

function findEndpoint(endpointId: string): WebhookEndpoint {
  for (const channelId of Object.keys(endpoints)) {
    const row = (endpoints[channelId] ?? []).find((r) => r.id === endpointId);
    if (row) return row;
  }
  throw new Error('Webhook endpoint not found');
}
