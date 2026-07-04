/**
 * Real persona service (Cluster E, slice 0b). Hits the `ems` module routers via
 * the STAFF api-client (gated by personas.read / personas.manage on the server).
 */
import { apiFetch } from '@/lib/api-client';
import type {
  Persona,
  PersonaMembership,
  PortalInviteResult,
  PortalPermission,
} from '@/types/persona';
import type { PersonaService } from './persona-service';

export const realPersonaService: PersonaService = {
  list() {
    return apiFetch<Persona[]>('/ems/personas');
  },
  get(id) {
    return apiFetch<Persona>(`/ems/personas/${id}`);
  },
  create(body) {
    return apiFetch<Persona>('/ems/personas', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },
  update(id, body) {
    return apiFetch<Persona>(`/ems/personas/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    });
  },
  async remove(id) {
    await apiFetch<void>(`/ems/personas/${id}`, { method: 'DELETE' });
  },
  portalPermissions() {
    return apiFetch<PortalPermission[]>('/ems/personas/portal-permissions');
  },
  async getPermissions(id) {
    const res = await apiFetch<{ keys: string[] }>(
      `/ems/personas/${id}/permissions`,
    );
    return res.keys;
  },
  async setPermissions(id, keys) {
    const res = await apiFetch<{ keys: string[] }>(
      `/ems/personas/${id}/permissions`,
      { method: 'PUT', body: JSON.stringify({ keys }) },
    );
    return res.keys;
  },
  listProfileMemberships(profileId) {
    return apiFetch<PersonaMembership[]>(`/ems/profiles/${profileId}/personas`);
  },
  assignMembership(profileId, body) {
    return apiFetch<PersonaMembership>(`/ems/profiles/${profileId}/personas`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },
  async revokeMembership(profileId, membershipId) {
    await apiFetch<void>(
      `/ems/profiles/${profileId}/personas/${membershipId}`,
      { method: 'DELETE' },
    );
  },
  sendPortalInvite(profileId, body) {
    return apiFetch<PortalInviteResult>(`/ems/profiles/${profileId}/invite`, {
      method: 'POST',
      body: JSON.stringify(body ?? {}),
    });
  },
};
