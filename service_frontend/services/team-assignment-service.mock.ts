/**
 * Mock team-assignment service (plan 28, S0 MOCK - swap to real in S5). See
 * `team-assignment-service.ts` for the design rationale (simplified pick,
 * sessionStorage overlay, delegates the actual user assignment to the real
 * `conversationService.assign`).
 */
import { conversationService } from '@/services/conversation-service';
import { teamService } from '@/services/team-service';
import { seededTeamsSync } from './team-service.mock';
import { delay } from './mock-query';
import type { TeamAssignmentOverlay, TeamAssignmentService } from './team-assignment-service';

const STORAGE_KEY = 'omnichannel:team-assignment-overlay:v1';

type OverlayMap = Record<string, { teamId: string; teamName: string }>;

function readStore(): OverlayMap {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as OverlayMap) : {};
  } catch {
    return {};
  }
}

function writeStore(map: OverlayMap): void {
  if (typeof window === 'undefined') return;
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(map));
  } catch {
    // sessionStorage unavailable (private browsing etc.) - the assignment
    // still applies for this render, it just won't survive a reload.
  }
}

export const mockTeamAssignmentService: TeamAssignmentService = {
  async assignTeam(contactId: string, teamId: string | null): Promise<void> {
    const map = readStore();
    if (teamId === null) {
      delete map[contactId];
      writeStore(map);
      await delay(undefined, 150);
      return;
    }

    const team = await teamService.get(teamId);
    map[contactId] = { teamId: team.id, teamName: team.name };
    writeStore(map);

    // D-A8-11 (mocked): an empty roster is a SUCCESS (team set, user stays
    // whatever it was) - the real strategy algorithm lands in S2. Here we
    // just deterministically pick the first member so the demo has SOMEONE
    // to show, and persist that pick through the REAL, already-working
    // assign endpoint (so a reload reflects a genuinely-assigned user).
    const pick = team.members[0];
    if (pick) {
      await conversationService.assign(contactId, pick.userId);
    }
    await delay(undefined, 150);
  },

  overlayFor(contactId: string): TeamAssignmentOverlay {
    const entry = readStore()[contactId];
    if (!entry) return { assignedTeamId: null, assignedTeamName: null };
    // Re-validate against the LIVE seeded list (mirrors `team.resolve@1`
    // tenant-scoped resolution, AC-TEM-29): a team deleted/renamed since the
    // overlay was written must never keep rendering the stale stored name -
    // a foreign/unknown id renders `null`, the id still round-trips.
    const known = seededTeamsSync();
    const live = known?.find((t) => t.id === entry.teamId);
    if (known && !live) return { assignedTeamId: entry.teamId, assignedTeamName: null };
    return { assignedTeamId: entry.teamId, assignedTeamName: live?.name ?? entry.teamName };
  },
};
