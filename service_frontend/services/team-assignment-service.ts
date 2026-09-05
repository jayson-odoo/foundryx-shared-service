/**
 * Team-assignment service - the boundary the inbox rail + conversation drawer
 * talk to for "assign this thread to a team" (plan 28, roadmap A8, D-A8-3/4).
 *
 * S0 MOCK - swap to real in S5 (plan 28). The real contract lands in S2
 * (`PATCH /omnichannel/contacts/{id} {assignedTeamId}`, §5.2/5.3 of the plan -
 * a per-team pick strategy, a locked cursor, the full precedence matrix). The
 * S0 mock is a DELIBERATELY SIMPLIFIED stand-in so the UI (rail + drawer) is
 * tunable against no backend: it picks the team's first member (not the real
 * round-robin/least-open strategies) and persists ONLY the team association
 * client-side (`sessionStorage`, keyed by contact id) - the picked MEMBER is
 * set through the EXISTING, already-real `conversationService.assign` so a
 * page reload still shows a real, backend-persisted assignee.
 */
import { mockTeamAssignmentService } from './team-assignment-service.mock';

export interface TeamAssignmentOverlay {
  assignedTeamId: string | null;
  assignedTeamName: string | null;
}

export interface TeamAssignmentService {
  /**
   * Assign (`teamId`) or clear (`null`) the team on a thread. Clearing a team
   * never touches the user assignee (D-A8-12 "assignedTeamId: null keeps the
   * user"); setting a team calls the real assign endpoint for the picked
   * member so realtime/WS + the assignee dropdown stay consistent.
   */
  assignTeam(contactId: string, teamId: string | null): Promise<void>;
  /** The stored team overlay for a contact, or nulls when never team-assigned
   *  in this mock layer. */
  overlayFor(contactId: string): TeamAssignmentOverlay;
}

// S0 MOCK - swap to real in S5 (plan 28). No `assignedTeamId` column exists on
// the backend yet (S2).
export const teamAssignmentService: TeamAssignmentService = mockTeamAssignmentService;
