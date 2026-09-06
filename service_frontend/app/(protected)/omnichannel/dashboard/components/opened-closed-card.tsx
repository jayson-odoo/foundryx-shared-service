import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ReportChart } from '@/components/platform/report-chart';
import type { DashboardResponse } from '@/types/omnichannel';

/**
 * Opened vs closed trend (plan 30, AC-RPT-42) - a two-series bar chart
 * through the shared `ReportChart` adapter (filled `opened`, outlined
 * `closed` - readable in greyscale per §3.1).
 */
export function OpenedClosedCard({ buckets, series }: { buckets: DashboardResponse['buckets']; series: DashboardResponse['series'] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Opened vs closed</CardTitle>
      </CardHeader>
      <CardContent>
        <ReportChart
          buckets={buckets}
          series={[
            { key: 'opened', label: 'Opened', points: series.opened },
            { key: 'closed', label: 'Closed', points: series.closed },
          ]}
          className="h-64 w-full"
        />
      </CardContent>
    </Card>
  );
}
