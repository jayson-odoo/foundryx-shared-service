'use client';

/**
 * Team assignment tab (plan 28, roadmap A8, AC-TEM-28) - one row per ACTIVE
 * core team with its per-workspace pick strategy. Clones the
 * `WorkspaceCloseReasonsTab` shape (a small settings list hanging off a real
 * workspace id, hidden while creating) but skips the Resource-shell list -
 * this is a handful of rows with ONE editable field (a strategy
 * `SearchSelect`), not a sortable/searchable/paginated catalog.
 */
import { useState } from 'react';
import { Info, Users } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { SearchSelect } from '@/components/platform/search-select';
import { useCan } from '@/hooks/use-can';
import { useTeamSettings } from '@/hooks/use-team-settings';
import { toast } from '@/lib/toast';
import { useDatetime } from '@/hooks/use-datetime';
import type { TeamAssignmentStrategy } from '@/types/omnichannel';

const STRATEGY_OPTIONS: { value: TeamAssignmentStrategy; label: string }[] = [
  { value: 'round_robin', label: 'Round robin' },
  { value: 'least_open', label: 'Least open threads' },
];

function describeError(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.';
}

export function WorkspaceTeamSettingsTab({
  workspaceId,
  creating,
}: {
  workspaceId: string | null;
  creating: boolean;
}) {
  const { can } = useCan();
  const canAssign = can('conversations.assign');
  const { formatDateTime } = useDatetime();
  const { rows, isLoading, setStrategy } = useTeamSettings(workspaceId);
  const [pending, setPending] = useState<string | null>(null);

  if (creating || !workspaceId) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center gap-2 py-16 text-center">
          <Info className="size-8 text-muted-foreground" />
          <p className="text-sm font-medium">Save the workspace to manage team assignment.</p>
        </CardContent>
      </Card>
    );
  }

  if (!isLoading && rows.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center gap-2 py-16 text-center">
          <Users className="size-8 text-muted-foreground" />
          <p className="text-sm font-medium">No teams yet.</p>
        </CardContent>
      </Card>
    );
  }

  const onChange = async (teamId: string, strategy: TeamAssignmentStrategy) => {
    setPending(teamId);
    try {
      await setStrategy(teamId, strategy);
    } catch (error) {
      toast.error(describeError(error));
    } finally {
      setPending(null);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      {rows.map((row) => (
        <Card key={row.teamId}>
          <CardContent className="flex flex-wrap items-center justify-between gap-3 py-4">
            <div className="flex flex-col gap-0.5">
              <span className="font-medium text-foreground">{row.teamName ?? row.teamId}</span>
              {row.isConfigured && (
                <span className="text-xs text-muted-foreground">
                  Last picked cursor updated {formatDateTime(row.updatedAt)}
                </span>
              )}
            </div>
            <SearchSelect
              className="w-56"
              options={STRATEGY_OPTIONS}
              value={row.strategy}
              onChange={(v) => onChange(row.teamId, v as TeamAssignmentStrategy)}
              disabled={!canAssign || pending === row.teamId}
              ariaLabel={`${row.teamName ?? row.teamId} assignment strategy`}
            />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
