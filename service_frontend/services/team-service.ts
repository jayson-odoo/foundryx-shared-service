/**
 * Team service - the boundary the Teams admin UI (and the omnichannel inbox
 * rail/drawer) talks to (plan 28, roadmap A8). Talks to the core `/teams`
 * routes (`app/api/v1/teams.py`, S1) via `team-service.real.ts`:
 *
 *   GET    /teams               ?page&page_size&search&sort_by&sort_dir -> {data, total}
 *   GET    /teams/mine                                -> TeamItem[]
 *   GET    /teams/{id}                                -> TeamItem
 *   POST   /teams               {name, description?, isActive?, sortOrder?, members[]}
 *   PATCH  /teams/{id}          {name?, description?, isActive?, sortOrder?, members?}
 *   DELETE /teams/{id}                                -> 204 | 409 team_in_use
 *
 * `team-service.mock.ts` is retained for component/hook tests only.
 */
import type { CreateTeamInput, MyTeam, Team, UpdateTeamInput } from '@/types/team';
import type { ListQuery, ListResult } from '@/types/resource';
import { realTeamService } from './team-service.real';

export interface TeamService {
  list(query: ListQuery): Promise<ListResult<Team>>;
  get(id: string): Promise<Team>;
  /** Record-nav: the team at `index` within the ordered query, plus the total. */
  getAt(query: ListQuery, index: number): Promise<{ team: Team | null; total: number }>;
  /** The caller's own teams (AC-TEM-08/16 - no `teams.read` required backend-
   *  side; the mock has no permission concept so this is just a member filter).
   *  Trimmed shape (review round 1, finding 7) - no member emails. */
  mine(): Promise<MyTeam[]>;
  create(input: CreateTeamInput): Promise<Team>;
  update(id: string, input: UpdateTeamInput): Promise<Team>;
  /** 409 `{error:"team_in_use", counts}` when a reference guard reports usage
   *  (AC-TEM-06); nothing is removed in that case. */
  remove(id: string): Promise<void>;
}

export const teamService: TeamService = realTeamService;
