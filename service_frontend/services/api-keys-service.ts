/**
 * API-keys service - the boundary the UI talks to (via hooks/configs). The
 * barrel binds the REAL api-client implementation; the mock (`*.mock.ts`) is
 * retained for tests + frontend-first iteration. The interface IS the backend
 * contract (omnichannel Slice 3 - workspace public-gateway keys).
 */
import type { ApiKeyItem, MintApiKeyResult } from '@/types/api-keys';
import { realApiKeysService } from './api-keys-service.real';

export interface ApiKeysService {
  /** All keys for a workspace (masked; ordered newest-first by the backend). */
  list(workspaceId: string): Promise<ApiKeyItem[]>;
  /** Mint a new key - returns the ONE-TIME full plaintext key. */
  mint(workspaceId: string, name: string): Promise<MintApiKeyResult>;
  /** Revoke a key (irreversible; the key stops authenticating immediately). */
  revoke(workspaceId: string, keyId: string): Promise<ApiKeyItem>;
}

// Real api-client implementation (mock retained in *.mock.ts for tests).
export const apiKeysService: ApiKeysService = realApiKeysService;
