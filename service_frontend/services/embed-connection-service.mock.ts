/**
 * In-memory mock embed-connection service - retained for tests + frontend-first
 * iteration. Mirrors the real service's contract (never returns the plaintext
 * secret; only reports `hasSecret`). Not bound by the barrel; import directly.
 */
import type { EmbedConnectionCreateInput, EmbedConnectionItem } from '@/types/embed-connection';
import type { EmbedConnectionService } from './embed-connection-service';

function seed(): EmbedConnectionItem[] {
  return [
    {
      connectionId: 'sorento-ideation',
      tenantId: 'default',
      allowedOrigins: ['https://fe-sorento.foundryx.my'],
      productId: null,
      isActive: true,
      hasSecret: true,
      createdAt: '2026-07-10T02:00:00Z',
      updatedAt: '2026-07-12T02:00:00Z',
    },
  ];
}

export function createMockEmbedConnectionService(
  initial: EmbedConnectionItem[] = seed(),
): EmbedConnectionService {
  let rows = [...initial];
  const now = () => new Date().toISOString();
  const find = (id: string) => rows.find((r) => r.connectionId === id);

  return {
    async list() {
      return [...rows].sort((a, b) => (b.createdAt ?? '').localeCompare(a.createdAt ?? ''));
    },
    async create(input: EmbedConnectionCreateInput) {
      const existing = find(input.connectionId);
      const item: EmbedConnectionItem = {
        connectionId: input.connectionId,
        tenantId: 'default',
        allowedOrigins: input.allowedOrigins,
        productId: input.productId ?? null,
        isActive: input.isActive ?? true,
        hasSecret: Boolean(input.signingSecret),
        createdAt: existing?.createdAt ?? now(),
        updatedAt: now(),
      };
      rows = [item, ...rows.filter((r) => r.connectionId !== input.connectionId)];
      return item;
    },
    async rotate(connectionId, signingSecret) {
      const row = find(connectionId);
      if (!row) throw new Error('Embed connection not found.');
      row.hasSecret = Boolean(signingSecret);
      row.updatedAt = now();
      return { ...row };
    },
    async setActive(connectionId, isActive) {
      const row = find(connectionId);
      if (!row) throw new Error('Embed connection not found.');
      row.isActive = isActive;
      row.updatedAt = now();
      return { ...row };
    },
    async remove(connectionId) {
      rows = rows.filter((r) => r.connectionId !== connectionId);
    },
  };
}

export const mockEmbedConnectionService = createMockEmbedConnectionService();
