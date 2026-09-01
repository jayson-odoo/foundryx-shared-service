/**
 * Real omnichannel media-caps settings service - talks to FastAPI via the shared
 * api-client (`GET/PUT /omnichannel/settings?workspaceId=`, gated channels.manage).
 */
import { apiFetch } from '@/lib/api-client';
import type {
  OmnichannelSettings,
  OmnichannelSettingsService,
  OmnichannelSettingsUpdate,
} from './omnichannel-settings-service';

/** `?workspaceId=` only when scoping to a workspace; omitted = tenant default. */
function scopeQuery(workspaceId?: string | null): string {
  if (!workspaceId) return '';
  return `?workspaceId=${encodeURIComponent(workspaceId)}`;
}

export const realOmnichannelSettingsService: OmnichannelSettingsService = {
  get(workspaceId) {
    return apiFetch<OmnichannelSettings>(`/omnichannel/settings${scopeQuery(workspaceId)}`);
  },
  update(overrides: OmnichannelSettingsUpdate, workspaceId) {
    return apiFetch<OmnichannelSettings>(`/omnichannel/settings${scopeQuery(workspaceId)}`, {
      method: 'PUT',
      body: JSON.stringify(overrides),
    });
  },
};
