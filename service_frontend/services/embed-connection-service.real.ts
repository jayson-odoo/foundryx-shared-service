/**
 * Real embed-connection service - talks to the FastAPI shared-service via the
 * shared api-client. Bound by the `embed-connection-service.ts` barrel.
 *
 * Endpoint map (modules/ideation/routers/embed_admin.py, gated
 * `ideation.triage.manage`):
 * - list      → GET    /ideation/embed-connections
 * - create    → POST   /ideation/embed-connections            {signing_secret,…}
 * - rotate    → POST   /ideation/embed-connections/{id}/rotate {signing_secret}
 * - setActive → PATCH  /ideation/embed-connections/{id}        {is_active}
 * - remove    → DELETE /ideation/embed-connections/{id}         (204)
 *
 * The admin router returns snake_case JSON (plain pydantic BaseModel), so we map
 * it to the camelCase `EmbedConnectionItem` here - the UI never sees the wire
 * shape. The signing secret is write-only: it rides create/rotate payloads and
 * is never present in any response.
 */
import { apiFetch } from '@/lib/api-client';
import type { EmbedConnectionItem } from '@/types/embed-connection';
import type { EmbedConnectionService } from './embed-connection-service';

/** Wire shape returned by the admin router (snake_case). */
interface EmbedConnectionRow {
  connection_id: string;
  tenant_id: string;
  allowed_origins: string[];
  product_id: string | null;
  is_active: boolean;
  has_secret: boolean;
  created_at: string | null;
  updated_at: string | null;
}

function toItem(row: EmbedConnectionRow): EmbedConnectionItem {
  return {
    connectionId: row.connection_id,
    tenantId: row.tenant_id,
    allowedOrigins: row.allowed_origins ?? [],
    productId: row.product_id ?? null,
    isActive: row.is_active,
    hasSecret: row.has_secret,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

const base = '/ideation/embed-connections';
const one = (id: string) => `${base}/${encodeURIComponent(id)}`;

export const realEmbedConnectionService: EmbedConnectionService = {
  async list() {
    const rows = await apiFetch<EmbedConnectionRow[]>(base);
    return rows.map(toItem);
  },
  async create(input) {
    const row = await apiFetch<EmbedConnectionRow>(base, {
      method: 'POST',
      body: JSON.stringify({
        connection_id: input.connectionId,
        signing_secret: input.signingSecret,
        allowed_origins: input.allowedOrigins,
        product_id: input.productId ?? null,
        is_active: input.isActive ?? true,
      }),
    });
    return toItem(row);
  },
  async rotate(connectionId, signingSecret) {
    const row = await apiFetch<EmbedConnectionRow>(`${one(connectionId)}/rotate`, {
      method: 'POST',
      body: JSON.stringify({ signing_secret: signingSecret }),
    });
    return toItem(row);
  },
  async setActive(connectionId, isActive) {
    const row = await apiFetch<EmbedConnectionRow>(one(connectionId), {
      method: 'PATCH',
      body: JSON.stringify({ is_active: isActive }),
    });
    return toItem(row);
  },
  async remove(connectionId) {
    await apiFetch<void>(one(connectionId), { method: 'DELETE' });
  },
};
