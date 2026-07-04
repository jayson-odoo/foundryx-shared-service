/**
 * Real API-keys service — talks to FastAPI via the shared api-client. Bound by
 * the `api-keys-service.ts` barrel. Endpoints per omnichannel Slice 3.
 */
import { apiFetch } from '@/lib/api-client';
import type { ApiKeyItem, MintApiKeyResult } from '@/types/api-keys';
import type { ApiKeysService } from './api-keys-service';

export const realApiKeysService: ApiKeysService = {
  async list(workspaceId) {
    const res = await apiFetch<{ data: ApiKeyItem[] }>(
      `/omnichannel/workspaces/${workspaceId}/api-keys`,
    );
    return res.data;
  },
  mint(workspaceId, name) {
    return apiFetch<MintApiKeyResult>(`/omnichannel/workspaces/${workspaceId}/api-keys`, {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
  },
  revoke(workspaceId, keyId) {
    return apiFetch<ApiKeyItem>(
      `/omnichannel/workspaces/${workspaceId}/api-keys/${keyId}/revoke`,
      { method: 'POST' },
    );
  },
};
