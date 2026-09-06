import { Badge, BadgeDot } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { DashboardLifecycleStage } from '@/types/omnichannel';

/**
 * Lifecycle stage tiles (plan 30, AC-RPT-42/49) - one card per stage, in
 * `sortOrder`; a stage with zero contacts is still listed (never dropped).
 * Wraps onto multiple rows at ~375px instead of overflowing.
 */
export function LifecycleTiles({ stages }: { stages: DashboardLifecycleStage[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Lifecycle</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-3">
        {stages.map((stage) => (
          <div key={stage.statusId} className="flex min-w-32 flex-1 flex-col gap-1 rounded-lg border border-border p-3">
            <Badge variant="secondary" appearance="light" size="sm" className="w-fit">
              <BadgeDot style={stage.color ? { backgroundColor: stage.color } : undefined} />
              {stage.label}
            </Badge>
            <span className="text-lg font-heading font-semibold">{stage.count}</span>
            <span className="text-xs text-muted-foreground">{stage.percent}%</span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
