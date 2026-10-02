/**
 * Business hours service (plan 31 S6, §5.7) - the boundary the workspace
 * "Business hours" tab talks to.
 *
 *   GET /omnichannel/workspaces/{wsId}/business-hours   (workspaces.read)
 *   PUT /omnichannel/workspaces/{wsId}/business-hours   (workspaces.manage)
 *
 * `PUT` validates server-side first (nothing written on a 422) and returns
 * the SAME shape as `GET` - the tab always re-syncs its baseline from the
 * response, never from the request it just sent.
 */
import type { BusinessHours, UpdateBusinessHoursInput } from '@/types/omnichannel';
import { realBusinessHoursService } from './business-hours-service.real';

export interface BusinessHoursService {
  get(workspaceId: string): Promise<BusinessHours>;
  update(workspaceId: string, input: UpdateBusinessHoursInput): Promise<BusinessHours>;
}

export const businessHoursService: BusinessHoursService = realBusinessHoursService;
