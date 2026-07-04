'use client';

import { useCallback, useState } from 'react';
import { apiKeysService } from '@/services/api-keys-service';
import type { MintApiKeyResult } from '@/types/api-keys';

export interface UseApiKeysResult {
  /** True while a mint request is in flight. */
  minting: boolean;
  /** Mint a new key; resolves with the one-time full key. */
  mint: (name: string) => Promise<MintApiKeyResult>;
}

/**
 * Mint operation for a workspace's API keys (UI → hook → service). Revoke +
 * list live in the list config's action registry / fetcher. Keeping mint here
 * lets the dialog stay a pure UI component that never touches the service.
 */
export function useApiKeys(workspaceId: string): UseApiKeysResult {
  const [minting, setMinting] = useState(false);

  const mint = useCallback(
    async (name: string) => {
      setMinting(true);
      try {
        return await apiKeysService.mint(workspaceId, name);
      } finally {
        setMinting(false);
      }
    },
    [workspaceId],
  );

  return { minting, mint };
}
