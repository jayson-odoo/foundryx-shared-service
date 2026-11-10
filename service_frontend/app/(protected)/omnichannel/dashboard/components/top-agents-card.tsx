import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ClampedText } from '@/components/platform/clamped-text';
import { formatDuration } from '@/lib/duration';
import type { DashboardTopAgent } from '@/types/omnichannel';

/**
 * Top-agents list (plan 30, AC-RPT-42) - already ordered by the service
 * (closedCount desc, name asc). Empty state is a plain status line.
 */
export function TopAgentsCard({ agents }: { agents: DashboardTopAgent[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Top agents</CardTitle>
      </CardHeader>
      <CardContent>
        {agents.length === 0 ? (
          <div className="flex h-24 items-center justify-center text-sm text-muted-foreground">No data in this range.</div>
        ) : (
          <ul className="flex flex-col divide-y divide-border">
            {agents.map((agent) => (
              <li key={agent.userId} className="flex items-center justify-between gap-3 py-2.5">
                <ClampedText text={agent.name} className="text-sm font-medium" />
                <div className="flex shrink-0 items-center gap-4 text-sm text-muted-foreground">
                  <span>{agent.closedCount} closed</span>
                  <span>{formatDuration(agent.medianResponseSeconds)} median</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
