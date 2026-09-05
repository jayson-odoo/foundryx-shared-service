/**
 * Team service - the boundary the Teams admin UI (and, later, the omnichannel
 * inbox rail/drawer) talks to (plan 28, roadmap A8). Mirrors the backend
 * contract in `documentation/plans/sprint-4/28-teams-core-and-omnichannel-
 * assignment.md` §5.1:
 *
 *   GET    /teams               ?q&sort&page&pageSize -> {data, total}
 *   GET    /teams/mine                                -> TeamItem[]
 *   GET    /teams/{id}                                -> TeamItem
 *   POST   /teams               {name, description?, isActive?, sortOrder?, members[]}
 *   PATCH  /teams/{id}          {name?, description?, isActive?, sortOrder?, members?}
 *   DELETE /teams/{id}                                -> 204 | 409 team_in_use
 *
 * S0 MOCK - swap to real in S5 (plan 28). No backend exists yet (S1 lands the
 * core `teams`/`team_members` tables + router) - every call below is served by
 * `team-service.mock.ts`, an in-memory store seeded ONCE from the REAL tenant
 * users list (`userService.list`) so members/leads are real people.
 */
import type { CreateTeamInput, Team, UpdateTeamInput } from '@/types/team';
import type { ListQuery, ListResult } from '@/types/resource';
import { mockTeamService } from './team-service.mock';

export interface TeamService {
  list(query: ListQuery): Promise<ListResult<Team>>;
  get(id: string): Promise<Team>;
  /** Record-nav: the team at `index` within the ordered query, plus the total. */
  getAt(query: ListQuery, index: number): Promise<{ team: Team | null; total: number }>;
  /** The caller's own teams (AC-TEM-08/16 - no `teams.read` required backend-
   *  side; the mock has no permission concept so this is just a member filter). */
  mine(): Promise<Team[]>;
  create(input: CreateTeamInput): Promise<Team>;
  update(id: string, input: UpdateTeamInput): Promise<Team>;
  /** 409 `{error:"team_in_use", counts}` when a reference guard reports usage
   *  (AC-TEM-06); nothing is removed in that case. */
  remove(id: string): Promise<void>;
}

// S0 MOCK - swap to real in S5 (plan 28). Team CRUD has no backend yet.
export const teamService: TeamService = mockTeamService;
