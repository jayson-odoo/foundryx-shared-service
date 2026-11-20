import { Card, CardContent } from '@/components/ui/card';
import type { DashboardResponse } from '@/types/omnichannel';

/**
 * Current-state tiles (plan 30, AC-RPT-42/49) - stack one per row at ~375px,
 * four across at ~1280px. `tiles` reflects CURRENT state and ignores the
 * selected date range (D-A9-2 dashboard content).
 */
export function StateTiles({ tiles }: { tiles: DashboardResponse['tiles'] }) {
  const items: { label: string; value: number }[] = [
    { label: 'Open', value: tiles.open },
    { label: 'Assigned', value: tiles.assigned },
    { label: 'Unassigned', value: tiles.unassigned },
    { label: 'Snoozed', value: tiles.snoozed },
  ];

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {items.map((item) => (
        <Card key={item.label}>
          <CardContent className="flex flex-col gap-1 py-5">
            <span className="text-sm text-muted-foreground">{item.label}</span>
            <span className="text-2xl font-heading font-semibold">{item.value}</span>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
