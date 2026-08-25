/**
 * Workspace public-gateway API-key types (omnichannel Slice 3).
 *
 * Mirrors the backend `app_omnichannel` key-management contract. Per-workspace
 * keys (`fxw_live_…`) external consumers use to call the public send API: minted
 * once (the full plaintext key is returned ONCE at mint), listed masked, and
 * revocable. Kept framework-agnostic so the service + UI share one source.
 */

/** Key lifecycle - ACTIVE until revoked. */
export type ApiKeyStatus = 'ACTIVE' | 'REVOKED';

/** A workspace API key as surfaced to the management UI (never the plaintext). */
export interface ApiKeyItem {
  id: string;
  workspaceId: string;
  name: string;
  /** Non-secret leading segment of the key (used to build the masked display). */
  keyPrefix: string;
  /** Display-safe masked form, e.g. "fxw_live_xxxxxxxx••••". */
  maskedKey: string;
  status: ApiKeyStatus;
  lastUsedAt: string | null; // ISO
  revokedAt: string | null; // ISO
  createdAt: string; // ISO
}

/**
 * Mint result - carries the ONE-TIME full plaintext key alongside the stored
 * (masked) item. `fullKey` is never returned by any later read.
 */
export interface MintApiKeyResult {
  key: ApiKeyItem;
  fullKey: string;
}
