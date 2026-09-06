/**
 * Team domain types (plan 28, roadmap A8). Mirrors the backend contract
 * (`documentation/plans/sprint-4/28-teams-core-and-omnichannel-assignment.md`
 * §5.1) a core `public.teams` grouping of tenant users, platform-wide, so any
 * Service (omnichannel first) can assign work to a team instead of only a
 * single user. `team-service.ts` binds to the real backend since S5.
 */

/** A team member's role - a label only in this slice (D-A8-17): no extra
 * permission, no assignment priority (B1 owns access levels). */
export type TeamMemberRole = 'member' | 'lead';

/** One member row on a team (`TeamMemberRef` in the backend contract). */
export interface TeamMemberRef {
  userId: string;
  name: string;
  email: string;
  role: TeamMemberRole;
}

/** A core team - tenant-scoped, shared by every Service. */
export interface Team {
  id: string;
  name: string;
  description: string | null;
  isActive: boolean;
  sortOrder: number;
  members: TeamMemberRef[];
  memberCount: number;
  createdAt: string; // ISO
  updatedAt: string; // ISO
}

/** One entry in the create/update `members` payload. */
export interface TeamMemberInput {
  userId: string;
  role: TeamMemberRole;
}

/** `GET /teams/mine` member shape (review round 1, finding 7) - NO `email`.
 * That route is authenticated-only (no `teams.read`), so it must never leak
 * teammates' email addresses to every signed-in user. */
export interface MyTeamMemberRef {
  userId: string;
  name: string;
  role: TeamMemberRole;
}

/** Trimmed `GET /teams/mine` team shape - no `description`/`sortOrder`/
 * timestamps and no member emails. */
export interface MyTeam {
  id: string;
  name: string;
  isActive: boolean;
  memberCount: number;
  members: MyTeamMemberRef[];
}

export interface CreateTeamInput {
  name: string;
  description?: string | null;
  isActive?: boolean;
  sortOrder?: number;
  members: TeamMemberInput[];
}

export interface UpdateTeamInput {
  name?: string;
  description?: string | null;
  isActive?: boolean;
  sortOrder?: number;
  members?: TeamMemberInput[];
}
