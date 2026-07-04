/**
 * PHASE 1 MOCK — in-memory API-keys service.
 *
 * Retained for tests + frontend-first iteration; the app binds the REAL impl
 * (see `api-keys-service.ts`). Mirrors the backend's mint-once contract: `mint`
 * returns the full plaintext key exactly once, `list` only ever yields the
 * masked item (never the plaintext), and `revoke` stamps `revokedAt`.
 */
import type { ApiKeyItem, MintApiKeyResult } from '@/types/api-keys';
import type { ApiKeysService } from './api-keys-service';
import { delay } from './mock-query';

/** Product key scheme — matches the backend `KEY_SCHEME`. */
const KEY_SCHEME = 'fxw_live_';
const PREFIX_LEN = 8;

const store: Record<string, ApiKeyItem[]> = {};
let counter = 0;

function randomToken(len: number): string {
  const alphabet = 'abcdefghijklmnopqrstuvwxyz0123456789';
  let out = '';
  for (let i = 0; i < len; i += 1) {
    out += alphabet[Math.floor(Math.random() * alphabet.length)];
  }
  return out;
}

function maskOf(prefix: string): string {
  return `${KEY_SCHEME}${prefix}••••`;
}

/** Reset the in-memory store (test helper). */
export function __resetApiKeysMock(): void {
  for (const k of Object.keys(store)) delete store[k];
  counter = 0;
}

export const mockApiKeysService: ApiKeysService = {
  async list(workspaceId) {
    const rows = store[workspaceId] ?? [];
    // Newest-first, mirroring the server ordering.
    return delay([...rows].sort((a, b) => b.createdAt.localeCompare(a.createdAt)), 200);
  },

  async mint(workspaceId, name) {
    counter += 1;
    const prefix = randomToken(PREFIX_LEN);
    const secret = randomToken(24);
    const fullKey = `${KEY_SCHEME}${prefix}${secret}`;
    const item: ApiKeyItem = {
      id: `key-${String(counter).padStart(3, '0')}`,
      workspaceId,
      name,
      keyPrefix: prefix,
      maskedKey: maskOf(prefix),
      status: 'ACTIVE',
      lastUsedAt: null,
      revokedAt: null,
      createdAt: new Date().toISOString(),
    };
    store[workspaceId] = [item, ...(store[workspaceId] ?? [])];
    // fullKey rides ONLY this response — no stored copy, never re-derivable.
    return delay({ key: item, fullKey } satisfies MintApiKeyResult);
  },

  async revoke(workspaceId, keyId) {
    const rows = store[workspaceId] ?? [];
    const idx = rows.findIndex((r) => r.id === keyId);
    if (idx === -1) throw new Error('API key not found');
    const revoked: ApiKeyItem = {
      ...rows[idx],
      status: 'REVOKED',
      revokedAt: new Date().toISOString(),
    };
    rows[idx] = revoked;
    return delay(revoked, 200);
  },
};
