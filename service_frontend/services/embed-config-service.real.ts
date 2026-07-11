/**
 * Real embed-access config service — talks to FastAPI via the shared api-client
 * (`/omnichannel/embed-config*`, gated `workspaces.manage`).
 */
import { apiFetch } from '@/lib/api-client';
import type {
  EmbedConfig,
  EmbedConfigService,
  EmbedRotateSecretResult,
} from './embed-config-service';

const BASE = '/omnichannel/embed-config';

export const realEmbedConfigService: EmbedConfigService = {
  get() {
    return apiFetch<EmbedConfig>(BASE);
  },
  enable() {
    return apiFetch<EmbedConfig>(`${BASE}/enable`, { method: 'POST' });
  },
  rotateSecret() {
    return apiFetch<EmbedRotateSecretResult>(`${BASE}/rotate-secret`, { method: 'POST' });
  },
  setOrigins(allowedOrigins: string[]) {
    return apiFetch<EmbedConfig>(`${BASE}/origins`, {
      method: 'PUT',
      body: JSON.stringify({ allowedOrigins }),
    });
  },
};
