/**
 * Real business hours service (plan 31 S6). Written against the exact
 * `business-hours-service.ts` contract - the backend routes shipped in S5.
 */
import { apiFetch } from '@/lib/api-client';
import type { BusinessHours, UpdateBusinessHoursInput } from '@/types/omnichannel';
import type { BusinessHoursService } from './business-hours-service';

export const realBusinessHoursService: BusinessHoursService = {
  async get(workspaceId) {
    return apiFetch<BusinessHours>(`/omnichannel/workspaces/${workspaceId}/business-hours`);
  },

  async update(workspaceId, input: UpdateBusinessHoursInput) {
    return apiFetch<BusinessHours>(`/omnichannel/workspaces/${workspaceId}/business-hours`, {
      method: 'PUT',
      body: JSON.stringify(input),
    });
  },
};
