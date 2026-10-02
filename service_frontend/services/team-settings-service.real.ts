/**
 * Real team-assignment-settings service (plan 28 S5, AC-TEM-28) - talks to
 * `modules/omnichannel/routers/team_settings.py`:
 *
 *   GET /omnichannel/workspaces/{wsId}/team-settings          (conversations.read)
 *   PUT /omnichannel/workspaces/{wsId}/team-settings/{teamId} (conversations.assign)
 */
import { apiFetch } from '@/lib/api-client';
import type { TeamAssignmentSetting, TeamAssignmentStrategy } from '@/types/omnichannel';
import type { TeamSettingsService } from './team-settings-service';

export const realTeamSettingsService: TeamSettingsService = {
  list(workspaceId: string) {
    return apiFetch<TeamAssignmentSetting[]>(`/omnichannel/workspaces/${workspaceId}/team-settings`);
  },
  setStrategy(workspaceId: string, teamId: string, strategy: TeamAssignmentStrategy) {
    return apiFetch<TeamAssignmentSetting>(
      `/omnichannel/workspaces/${workspaceId}/team-settings/${teamId}`,
      { method: 'PUT', body: JSON.stringify({ strategy }) },
    );
  },
};
