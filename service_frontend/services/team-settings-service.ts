/**
 * Team-assignment-settings service - the boundary the workspace "Team
 * assignment" tab talks to (plan 28, roadmap A8, AC-TEM-28). Backed by the
 * real `modules/omnichannel/routers/team_settings.py` routes since S5 (this
 * surface has no S0 mock - it lands directly against the real backend).
 */
import type { TeamAssignmentSetting, TeamAssignmentStrategy } from '@/types/omnichannel';
import { realTeamSettingsService } from './team-settings-service.real';

export interface TeamSettingsService {
  /** One row per ACTIVE core team (review round 1, finding 4/5/6) - already
   *  merged with this workspace's configured strategy rows server-side, so
   *  no separate `GET /teams` call is needed to populate the tab. */
  list(workspaceId: string): Promise<TeamAssignmentSetting[]>;
  /** 404 when the team id fails `team.resolve@1` (unknown, foreign-tenant,
   *  deleted, or the capability not registered). */
  setStrategy(
    workspaceId: string,
    teamId: string,
    strategy: TeamAssignmentStrategy,
  ): Promise<TeamAssignmentSetting>;
}

export const teamSettingsService: TeamSettingsService = realTeamSettingsService;
