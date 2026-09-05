'use client';

/**
 * Team Inbox rail (plan 28, roadmap A8, D-A8-4) - a SEAM component: plan-27's
 * `inbox-view-rail.tsx` (the full saved-views rail) does not exist on this
 * branch yet, so this ships as a small, self-contained nav that the inbox
 * page mounts directly. When plan 27 merges, its rail should absorb this
 * Teams section (same data via `useMyTeams`/`useTeams`) rather than the two
 * living side by side - noted in the plan-28 S0 report.
 *
 * >= 1024px: a left rail column (My teams, each with a nested Unassigned
 * entry, plus an "All teams" group for `conversations.assign` holders).
 * Below 1024px: the SAME entries as a single searchable `SearchSelect` (no
 * new layout - AC-TEM-44).
 */
import { useMemo } from 'react';

import { SearchSelect, type SearchSelectGroup } from '@/components/platform/search-select';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { useCan } from '@/hooks/use-can';
import { useMediaQuery } from '@/hooks/use-media-query';
import { useMyTeams } from '@/hooks/use-my-teams';
import { useTeams } from '@/hooks/use-teams';
import { cn } from '@/lib/utils';
import type { Team } from '@/types/team';

export interface TeamRailProps {
  selectedTeamId: string | null;
  selectedAssignee: 'all' | 'me' | 'unassigned';
  onSelect: (teamId: string | null, unassignedOnly: boolean) => void;
}

const ALL_VALUE = '__all__';
const unassignedValue = (teamId: string) => `${teamId}::unassigned`;

function teamOptions(team: Team) {
  return [
    { label: team.name, value: team.id },
    { label: `${team.name} - Unassigned`, value: unassignedValue(team.id) },
  ];
}

export function TeamRail({ selectedTeamId, selectedAssignee, onSelect }: TeamRailProps) {
  const { can } = useCan();
  const privileged = can('conversations.assign');
  const { teams: myTeams, isLoading: myLoading } = useMyTeams();
  const { teams: allTeams, isLoading: allLoading } = useTeams();
  const isDesktop = useMediaQuery('(min-width: 1024px)');

  const otherTeams = useMemo(() => {
    if (!privileged) return [];
    const mine = new Set(myTeams.map((t) => t.id));
    return allTeams.filter((t) => !mine.has(t.id));
  }, [privileged, myTeams, allTeams]);

  if (myLoading || (privileged && allLoading)) return null;
  if (myTeams.length === 0 && otherTeams.length === 0) return null; // nothing to route to (foolproof-UI)

  if (isDesktop) {
    return (
      <div
        className="flex h-full w-[200px] shrink-0 flex-col overflow-y-auto border-e"
        data-testid="team-rail"
      >
        <div className="px-3 py-2.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Teams
        </div>
        <button
          type="button"
          onClick={() => onSelect(null, false)}
          className={cn(
            PRESSED_CLASS,
            'px-3 py-2 text-start text-sm hover:bg-accent',
            !selectedTeamId && 'bg-accent font-medium',
          )}
          data-testid="team-rail-all"
        >
          All conversations
        </button>
        {myTeams.map((team) => (
          <div key={team.id}>
            <button
              type="button"
              onClick={() => onSelect(team.id, false)}
              className={cn(
                PRESSED_CLASS,
                'flex w-full items-center px-3 py-2 text-start text-sm hover:bg-accent',
                selectedTeamId === team.id && selectedAssignee !== 'unassigned' && 'bg-accent font-medium',
              )}
              data-testid={`team-rail-${team.id}`}
            >
              {team.name}
            </button>
            <button
              type="button"
              onClick={() => onSelect(team.id, true)}
              className={cn(
                PRESSED_CLASS,
                'flex w-full items-center py-1.5 ps-6 pe-3 text-start text-xs text-muted-foreground hover:bg-accent',
                selectedTeamId === team.id && selectedAssignee === 'unassigned' && 'bg-accent font-medium text-foreground',
              )}
              data-testid={`team-rail-${team.id}-unassigned`}
            >
              Unassigned
            </button>
          </div>
        ))}
        {otherTeams.length > 0 && (
          <>
            <div className="px-3 pt-3 pb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              All teams
            </div>
            {otherTeams.map((team) => (
              <div key={team.id}>
                <button
                  type="button"
                  onClick={() => onSelect(team.id, false)}
                  className={cn(
                    PRESSED_CLASS,
                    'flex w-full items-center px-3 py-2 text-start text-sm hover:bg-accent',
                    selectedTeamId === team.id && selectedAssignee !== 'unassigned' && 'bg-accent font-medium',
                  )}
                  data-testid={`team-rail-${team.id}`}
                >
                  {team.name}
                </button>
                <button
                  type="button"
                  onClick={() => onSelect(team.id, true)}
                  className={cn(
                    PRESSED_CLASS,
                    'flex w-full items-center py-1.5 ps-6 pe-3 text-start text-xs text-muted-foreground hover:bg-accent',
                    selectedTeamId === team.id && selectedAssignee === 'unassigned' && 'bg-accent font-medium text-foreground',
                  )}
                  data-testid={`team-rail-${team.id}-unassigned`}
                >
                  Unassigned
                </button>
              </div>
            ))}
          </>
        )}
      </div>
    );
  }

  // Below 1024px: the same entries, as one searchable select (no new layout).
  const groups: SearchSelectGroup[] = [
    {
      label: 'Teams',
      options: [{ label: 'All conversations', value: ALL_VALUE }, ...myTeams.flatMap(teamOptions)],
    },
    ...(otherTeams.length > 0
      ? [{ label: 'All teams', options: otherTeams.flatMap(teamOptions) }]
      : []),
  ];
  const currentValue = !selectedTeamId
    ? ALL_VALUE
    : selectedAssignee === 'unassigned'
      ? unassignedValue(selectedTeamId)
      : selectedTeamId;

  return (
    <div className="border-b p-2" data-testid="team-rail-mobile">
      <SearchSelect
        groups={groups}
        value={currentValue}
        onChange={(v) => {
          if (v === ALL_VALUE) onSelect(null, false);
          else if (v.endsWith('::unassigned')) onSelect(v.slice(0, -'::unassigned'.length), true);
          else onSelect(v, false);
        }}
        ariaLabel="Team Inbox"
        placeholder="All conversations"
        searchPlaceholder="Search teams…"
      />
    </div>
  );
}
