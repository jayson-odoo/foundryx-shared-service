import { apiFetch } from '@/lib/api-client';
import type { ClientApp, CreateClientAppInput, UpdateClientAppInput } from '@/types/omnichannel';
import type { ClientAppsService } from './client-apps-service';

interface ClientAppListResponse {
  data: ClientApp[];
}

export const realClientAppsService: ClientAppsService = {
  async list() {
    const res = await apiFetch<ClientAppListResponse>('/omnichannel/client-apps');
    return res.data;
  },

  async create(input: CreateClientAppInput) {
    return apiFetch<ClientApp>('/omnichannel/client-apps', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  async rename(id, input: UpdateClientAppInput) {
    return apiFetch<ClientApp>(`/omnichannel/client-apps/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    });
  },

  async moveWorkspace(targetClientAppId, workspaceId) {
    return apiFetch<ClientApp>(`/omnichannel/client-apps/${targetClientAppId}/workspaces/move`, {
      method: 'POST',
      body: JSON.stringify({ workspaceId }),
    });
  },
};
